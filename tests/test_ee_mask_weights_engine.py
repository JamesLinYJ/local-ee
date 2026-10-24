"""Trusted Python bridge checks for native fractional-mask weight projections."""
from __future__ import annotations

import pytest

from engine import ee_mask_weights
from gee.mask_weights_spec import mask_weights_spec
from ee_sampling_bridge_helpers import _dry_cube, _metadata
from openeo_driver.errors import ProcessParameterInvalidException


@pytest.mark.parametrize(
    "operation,bands",
    [("validity", ("raw",)), ("update", ("old_weight", "new_mask")),
     ("apply", ("raw", "weight"))],
)
def test_mask_weights_dry_run_returns_v_band_and_preserves_trace(operation, bands):
    cube, source, tracer = _dry_cube(bands=bands, temporal=True)

    result = ee_mask_weights.local_ee_mask_weights(
        {"data": cube, "spec": mask_weights_spec(operation)}, env=None
    )

    assert result.metadata.band_names == ["v"]
    assert result.metadata.has_temporal_dimension()
    assert result._traces[0].get_source() is source
    assert result._data_tracer is tracer


def test_mask_weights_actual_cube_forwards_only_canonical_spec(monkeypatch):
    from openeo_driver.datacube import DriverDataCube

    cube = DriverDataCube(metadata=_metadata(("raw", "weight"), temporal=True))
    text = mask_weights_spec("apply")
    calls = []

    def apply(actual, process_id, arguments, metadata, *, target_type=None):
        calls.append((actual, process_id, arguments, metadata, target_type))
        return "native-result"

    from engine import ee_process_adapters
    monkeypatch.setattr(ee_process_adapters, "_apply_native", apply)
    result = ee_mask_weights.local_ee_mask_weights({"data": cube, "spec": text}, env=None)

    assert result == "native-result"
    assert len(calls) == 1
    actual, process_id, arguments, metadata, target_type = calls[0]
    assert (actual, process_id, arguments, target_type) == (
        cube, "local_ee_mask_weights", {"spec": text}, None,
    )
    assert metadata.band_names == ["v"]
    assert metadata.has_temporal_dimension()


@pytest.mark.parametrize(
    "operation,bands",
    [("validity", ("raw", "extra")), ("update", ("old_weight",)),
     ("apply", ("raw", "weight", "extra"))],
)
def test_mask_weights_requires_the_exact_operation_band_count(operation, bands):
    cube, _, _ = _dry_cube(bands=bands)

    with pytest.raises(ValueError, match="exactly"):
        ee_mask_weights.local_ee_mask_weights(
            {"data": cube, "spec": mask_weights_spec(operation)}, env=None
        )


@pytest.mark.parametrize(
    "text",
    [
        "{}",
        '{"op":"validity","v":1} ',
        '{"op":"validity","v":true}',
        '{"op":"validity","v":2}',
        '{"op":"validity","v":1,"extra":0}',
        '{"op":"validity","op":"apply","v":1}',
        '{"op":"unknown","v":1}',
        '{"op":"validity","v":1}雪',
    ],
)
def test_mask_weights_rejects_noncanonical_or_invalid_specs_before_dispatch(text, monkeypatch):
    cube, _, _ = _dry_cube(bands=("raw",))
    from engine import ee_process_adapters

    def unexpected(*args, **kwargs):
        raise AssertionError("invalid specs must not reach native dispatch")

    monkeypatch.setattr(ee_process_adapters, "_apply_native", unexpected)
    with pytest.raises((ValueError, TypeError, ProcessParameterInvalidException)):
        ee_mask_weights.local_ee_mask_weights({"data": cube, "spec": text}, env=None)


def test_mask_weights_rejects_extra_arguments_and_non_string_spec():
    cube, _, _ = _dry_cube(bands=("raw",))
    with pytest.raises(ValueError, match="accepts exactly"):
        ee_mask_weights.local_ee_mask_weights(
            {"data": cube, "spec": mask_weights_spec("validity"), "extra": 1}, env=None
        )
    with pytest.raises((ValueError, TypeError, ProcessParameterInvalidException),
                       match="canonical JSON text"):
        ee_mask_weights.local_ee_mask_weights({"data": cube, "spec": {}}, env=None)


def test_mask_weights_recovers_selected_bands_from_the_pinned_dry_run_trace():
    cube, source, tracer = _dry_cube(bands=("red", "nir"), temporal=True)
    selected = cube.filter_bands(["nir"])

    result = ee_mask_weights.local_ee_mask_weights(
        {"data": selected, "spec": mask_weights_spec("validity")}, env=None
    )

    assert selected.metadata.band_names == ["red", "nir"]
    assert result.metadata.band_names == ["v"]
    assert result._data_tracer is tracer and result._traces[0].get_source() is source
    assert tracer.get_source_constraints()[0][1]["bands"] == ["nir"]


def test_real_process_graph_evaluator_keeps_output_band_filter_after_projection(monkeypatch):
    from test_ee_integer_values_bridge import _evaluator_env

    collection = {
        "id": "synthetic-mask-weights",
        "cube:dimensions": {
            "x": {"type": "spatial", "axis": "x", "extent": [0, 4], "reference_system": 4326},
            "y": {"type": "spatial", "axis": "y", "extent": [0, 3], "reference_system": 4326},
            "t": {"type": "temporal", "extent": ["2025-01-01", "2025-01-02"]},
            "bands": {"type": "bands", "values": ["raw", "weight", "unused"]},
        },
    }
    evaluate, env, tracer = _evaluator_env(monkeypatch, [collection])
    graph = {
        "source": {"process_id": "load_collection", "arguments": {"id": "synthetic-mask-weights"}},
        "inputs": {"process_id": "filter_bands", "arguments": {
            "data": {"from_node": "source"}, "bands": ["raw", "weight"],
        }},
        "weights": {"process_id": "local_ee_mask_weights", "arguments": {
            "data": {"from_node": "inputs"}, "spec": mask_weights_spec("apply"),
        }},
        "output": {"process_id": "filter_bands", "result": True, "arguments": {
            "data": {"from_node": "weights"}, "bands": ["v"],
        }},
    }

    result = evaluate(graph, env=env, do_dry_run=False)

    assert result.metadata.band_names == ["v"]
    constraints = tracer.get_source_constraints()
    assert len(constraints) == 1
    assert constraints[0][1]["bands"] == ["raw", "weight"]
