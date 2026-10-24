"""Bridge schema and pinned dry-run pushdown tests for native Image.unmix."""
import pytest

from ee_sampling_bridge_helpers import _metadata
from engine import ee_process_adapters as adapters
from engine.ee_unmix import local_ee_unmix, register_unmix_pushdown_boundary
from gee.spectral_unmix_spec import prepare_spectral_unmix_spec


def _spec():
    return prepare_spectral_unmix_spec(
        [[0.1, 0.2, 0.7], [0.1, 0.7, 0.2], [0.7, 0.1, 0.2]],
        sumToOne=True,
        nonNegative=True,
    )


def test_actual_bridge_forwards_canonical_spec_and_component_schema(monkeypatch):
    from openeo_driver.datacube import DriverDataCube

    cube = DriverDataCube(metadata=_metadata(("band0", "band1", "band2"), temporal=True))
    original = list(cube.metadata.band_names)
    calls = []
    monkeypatch.setattr(adapters, "_apply_native", lambda *args: calls.append(args) or "native-result")

    assert local_ee_unmix({"data": cube, "spec": _spec()}, None) == "native-result"
    actual, process_id, arguments, metadata = calls[0]
    assert actual is cube and process_id == "local_ee_unmix"
    assert arguments == {"spec": _spec()}
    assert metadata.band_names == ["unmix0", "unmix1", "unmix2"]
    assert metadata.has_temporal_dimension()
    assert metadata.spatial_dimensions == cube.metadata.spatial_dimensions
    assert cube.metadata.band_names == original


@pytest.mark.parametrize("bands", [
    ("band0", "band1"),
    ("band1", "band0", "band2"),
    ("band0", "band1", "band2", "extra"),
])
def test_actual_bridge_requires_all_input_bands_in_declared_order(bands):
    from openeo_driver.datacube import DriverDataCube

    cube = DriverDataCube(metadata=_metadata(bands))
    with pytest.raises(ValueError, match="ordered input bands"):
        local_ee_unmix({"data": cube, "spec": _spec()}, None)


def test_pinned_evaluator_does_not_push_component_labels_into_source_bands(monkeypatch):
    from test_ee_integer_values_bridge import _evaluator_env

    collection = {
        "id": "synthetic-unmix",
        "cube:dimensions": {
            "x": {"type": "spatial", "axis": "x", "extent": [0, 4], "reference_system": 4326},
            "y": {"type": "spatial", "axis": "y", "extent": [0, 3], "reference_system": 4326},
            "t": {"type": "temporal", "extent": ["2025-01-01", "2025-01-02"]},
            "bands": {"type": "bands", "values": ["band0", "band1", "band2"]},
        },
    }
    evaluate, env, tracer = _evaluator_env(monkeypatch, [collection])
    graph = {
        "source": {"process_id": "load_collection", "arguments": {
            "id": "synthetic-unmix", "bands": ["band0", "band1", "band2"],
        }},
        "unmix": {"process_id": "local_ee_unmix", "arguments": {
            "data": {"from_node": "source"}, "spec": _spec(),
        }},
        "select_component": {"process_id": "filter_bands", "arguments": {
            "data": {"from_node": "unmix"}, "bands": ["unmix0"],
        }},
        "external_name": {"process_id": "rename_labels", "arguments": {
            "data": {"from_node": "select_component"},
            "dimension": "bands", "target": ["unmix_0"],
        }},
        "select_external_name": {"process_id": "filter_bands", "result": True,
            "arguments": {"data": {"from_node": "external_name"}, "bands": ["unmix_0"]}},
    }

    result = evaluate(graph, env=env, do_dry_run=False)

    # The pinned dry-run keeps pre-rename band metadata stale; the producer itself
    # still owns unmix0..unmix2 and source constraints are checked independently.
    assert result.metadata.band_names == ["unmix0", "unmix1", "unmix2"]
    constraints = tracer.get_source_constraints()
    assert len(constraints) == 1
    assert constraints[0][0].arguments[0] == "synthetic-unmix"
    assert constraints[0][1]["bands"] == ["band0", "band1", "band2"]


def test_band_pushdown_registration_is_idempotent_and_scoped():
    from openeo_driver.dry_run import PROPAGATION_RULES

    before = {rule.constraint_key: [item for item in rule.blockers if item != "local_ee_unmix"]
              for rule in PROPAGATION_RULES}
    register_unmix_pushdown_boundary()
    register_unmix_pushdown_boundary()
    after = {rule.constraint_key: [item for item in rule.blockers if item != "local_ee_unmix"]
             for rule in PROPAGATION_RULES}
    rules = [rule for rule in PROPAGATION_RULES if rule.constraint_key == "bands"]
    assert before == after
    assert len(rules) == 1 and rules[0].blockers.count("local_ee_unmix") == 1
    assert all("local_ee_unmix" not in rule.blockers
               for rule in PROPAGATION_RULES if rule.constraint_key != "bands")
