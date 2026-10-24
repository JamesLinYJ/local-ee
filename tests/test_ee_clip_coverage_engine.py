"""Exercise the actual openEO bridge and its source constraint boundary."""
from __future__ import annotations

import json

import pytest

from engine import ee_clip_coverage
from ee_sampling_bridge_helpers import _dry_cube, _metadata


def wire():
    return json.dumps({
        "version": 1, "model": "great-circle",
        "polygons": [[[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]]],
    }, sort_keys=True, separators=(",", ":"))


def test_dry_run_clip_preserves_source_keys_and_returns_independent_weight_band():
    cube, source, tracer = _dry_cube(bands=("raw",), temporal=True)
    result = ee_clip_coverage.local_ee_clip_coverage({"data": cube, "spec": wire()}, None)
    assert result.metadata.band_names == ["v"]
    assert result.metadata.has_temporal_dimension()
    assert result._traces[0].get_source() is source
    assert result._data_tracer is tracer


def test_actual_clip_bridge_forwards_only_the_validated_wire(monkeypatch):
    from openeo_driver.datacube import DriverDataCube
    from engine import ee_process_adapters

    cube = DriverDataCube(metadata=_metadata(("raw",), temporal=True))
    calls = []

    def apply(actual, process_id, arguments, metadata):
        calls.append((actual, process_id, arguments, metadata))
        return "native-result"

    monkeypatch.setattr(ee_process_adapters, "_apply_native", apply)
    assert ee_clip_coverage.local_ee_clip_coverage({"data": cube, "spec": wire()}, None) == "native-result"
    assert len(calls) == 1
    assert calls[0][:3] == (cube, "local_ee_clip_coverage", {"spec": wire()})
    assert calls[0][3].band_names == ["v"]
    assert calls[0][3].has_temporal_dimension()


@pytest.mark.parametrize("bands", [("raw", "extra"), ()])
def test_clip_requires_one_actual_ordered_band(bands):
    cube, _, _ = _dry_cube(bands=bands)
    with pytest.raises(ValueError, match="exactly one"):
        ee_clip_coverage.local_ee_clip_coverage({"data": cube, "spec": wire()}, None)


@pytest.mark.parametrize("text", [None, {}, "{}", wire() + " ", wire().replace('"version":1', '"version":true')])
def test_invalid_clip_specs_do_not_reach_native_dispatch(text, monkeypatch):
    from engine import ee_process_adapters

    cube, _, _ = _dry_cube(bands=("raw",))

    def unexpected(*args, **kwargs):
        pytest.fail("Invalid clip specification reached the native bridge")

    monkeypatch.setattr(ee_process_adapters, "_apply_native", unexpected)
    with pytest.raises((ValueError, TypeError)):
        ee_clip_coverage.local_ee_clip_coverage({"data": cube, "spec": text}, None)


def test_selected_dry_run_band_is_recovered_without_relying_on_stale_metadata():
    cube, source, tracer = _dry_cube(bands=("raw", "unused"))
    selected = cube.filter_bands(["raw"])
    assert selected.metadata.band_names == ["raw", "unused"]
    result = ee_clip_coverage.local_ee_clip_coverage({"data": selected, "spec": wire()}, None)
    assert result.metadata.band_names == ["v"]
    assert result._data_tracer is tracer
    assert result._traces[0].get_source() is source
    assert tracer.get_source_constraints()[0][1]["bands"] == ["raw"]


def test_clip_blocks_output_band_resampling_and_region_pushdown():
    from openeo_driver.dry_run import PROPAGATION_RULES

    ee_clip_coverage.register_clip_coverage_pushdown_boundary()
    expected = {"bands", "resample", "spatial_extent", "weak_spatial_extent",
                "aggregate_spatial", "filter_spatial"}
    selected = [rule for rule in PROPAGATION_RULES if rule.constraint_key in expected]
    assert {rule.constraint_key for rule in selected} == expected
    assert all("local_ee_clip_coverage" in rule.blockers for rule in selected)


def test_clip_bridge_rejects_unknown_arguments():
    cube, _, _ = _dry_cube(bands=("raw",))
    with pytest.raises(ValueError, match="accepts exactly"):
        ee_clip_coverage.local_ee_clip_coverage({"data": cube, "spec": wire(), "url": "external"}, None)


def test_pinned_evaluator_keeps_the_output_selector_after_coverage(monkeypatch):
    from test_ee_integer_values_bridge import _evaluator_env

    collection = {
        "id": "synthetic-clip-coverage",
        "cube:dimensions": {
            "x": {"type": "spatial", "axis": "x", "extent": [0, 4], "reference_system": 4326},
            "y": {"type": "spatial", "axis": "y", "extent": [0, 3], "reference_system": 4326},
            "t": {"type": "temporal", "extent": ["2025-01-01", "2025-01-02"]},
            "bands": {"type": "bands", "values": ["raw", "unused"]},
        },
    }
    evaluate, env, tracer = _evaluator_env(monkeypatch, [collection])
    graph = {
        "source": {"process_id": "load_collection", "arguments": {"id": collection["id"]}},
        "selected": {"process_id": "filter_bands", "arguments": {
            "data": {"from_node": "source"}, "bands": ["raw"],
        }},
        "coverage": {"process_id": "local_ee_clip_coverage", "arguments": {
            "data": {"from_node": "selected"}, "spec": wire(),
        }},
        "output": {"process_id": "filter_bands", "result": True, "arguments": {
            "data": {"from_node": "coverage"}, "bands": ["v"],
        }},
    }
    result = evaluate(graph, env=env, do_dry_run=False)
    assert result.metadata.band_names == ["v"]
    constraints = tracer.get_source_constraints()
    assert len(constraints) == 1
    assert constraints[0][1]["bands"] == ["raw"]
