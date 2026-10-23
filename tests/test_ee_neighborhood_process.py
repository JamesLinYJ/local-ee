"""Strict positive-weight statistics wire and raster producer boundaries."""
import json
import math

import pytest

from gee.backend import Processes
from gee.graph import validate
from gee.local_processes import validate_local_process
from gee.neighborhood_spec import (
    OPERATIONS, UNIT_WEIGHT_OPERATIONS, decode_neighborhood_spec, prepare_neighborhood_spec,
)


def graph(spec=None, **extra):
    return {
        "load": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "statistics": {"process_id": "local_ee_neighborhood", "result": True, "arguments": {
            "data": {"from_node": "load"},
            "spec": spec if spec is not None else prepare_neighborhood_spec("mean", [(0, 0, 1.0)]),
            **extra,
        }},
    }


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_all_actual_operations_accept_unit_weight_wire(operation):
    validate(graph(prepare_neighborhood_spec(operation, [(0, 0, 1.0)], skip_masked=False)))


def test_roundtrip_preserves_extreme_binary64_coefficients_and_owns_values():
    values = [[32, 0, math.ulp(0.0)], [-32, -1, float.fromhex("0x1.fffffffffffffp+1023")]]
    text = prepare_neighborhood_spec("mean", values, False)
    values[0][2] = 3.0
    assert decode_neighborhood_spec(text) == {
        "v": 1, "operation": "mean", "skip_masked": False,
        "coefficients": [[-32, -1, "7fefffffffffffff"], [32, 0, "0000000000000001"]],
    }
    validate(graph(text))
    maximal = prepare_neighborhood_spec("sum", [(x, y, 2.0) for y in range(-16, 17) for x in range(-16, 17)])
    assert len(maximal) <= 32768 and len(decode_neighborhood_spec(maximal)["coefficients"]) == 1089


@pytest.mark.parametrize("operation", sorted(UNIT_WEIGHT_OPERATIONS))
def test_sample_and_order_statistics_reject_ambiguous_nonunit_weights(operation):
    with pytest.raises(ValueError, match="unit weights"):
        prepare_neighborhood_spec(operation, [(0, 0, 0.5)])
    value = decode_neighborhood_spec(prepare_neighborhood_spec("mean", [(0, 0, 0.5)]))
    value["operation"] = operation
    with pytest.raises(ValueError, match="unit weights"):
        validate(graph(json.dumps(value, sort_keys=True, separators=(",", ":"))))


@pytest.mark.parametrize("coefficients", [
    [], iter([(0, 0, 1.0)]), [(0, 0, 1.0)] * 1090, [[True, 0, 1.0]],
    [[0, 0.0, 1.0]], [[33, 0, 1.0]], [[0, 0, 1]], [[0, 0, True]],
    [[0, 0, float("nan")]], [[0, 0, float("inf")]], [[0, 0, 0.0]],
    [[0, 0, -0.0]], [[0, 0, -1.0]], [[0, 0, 1.0]] * 2, [[0, 0]],
])
def test_invalid_coefficient_shapes_types_and_weights_reject(coefficients):
    with pytest.raises(ValueError):
        prepare_neighborhood_spec("sum", coefficients)


@pytest.mark.parametrize("field,value", [
    ("v", True), ("v", 1.0), ("v", 2), ("operation", "unknown"), ("operation", []),
    ("skip_masked", 1), ("skip_masked", None), ("coefficients", []),
    ("coefficients", [[0, 0, "7ff0000000000000"]]),
    ("coefficients", [[0, 0, "7ff8000000000000"]]),
    ("coefficients", [[0, 0, "8000000000000000"]]),
    ("coefficients", [[0, 0, "0000000000000000"]]),
    ("coefficients", [[0, 0, "bff0000000000000"]]),
    ("coefficients", [[0, 0, "3FF0000000000000"]]),
    ("coefficients", [[0, 0, 1.0]]),
    ("coefficients", [[1, 0, "3ff0000000000000"], [0, 0, "3ff0000000000000"]]),
])
def test_public_graph_revalidates_wire(field, value):
    spec = decode_neighborhood_spec(prepare_neighborhood_spec("mean", [(0, 0, 1.0)]))
    spec[field] = value
    with pytest.raises(ValueError):
        validate(graph(json.dumps(spec, sort_keys=True, separators=(",", ":"))))


@pytest.mark.parametrize("text", ["{}", "[]", "[" * 1001, "x" * 32769, "é", None, {},
                                  '{"v":1,"v":1}'])
def test_noncanonical_unbounded_and_duplicate_json_reject(text):
    with pytest.raises(ValueError):
        decode_neighborhood_spec(text)


def test_public_process_requires_direct_raster_references_and_no_callbacks():
    for data in (None, "/tmp/a.tif", {"from_parameter": "data"}, {"from_node": "load", "x": 1}):
        with pytest.raises(ValueError):
            validate(graph(data=data))
    with pytest.raises(ValueError, match="top-level"):
        validate_local_process("local_ee_neighborhood", graph()["statistics"]["arguments"], 1)
    with pytest.raises(ValueError):
        validate(graph(extra=True))
    for process, arguments in [("add", {"x": 1, "y": 2}),
                               ("save_result", {"data": {"from_node": "load"}, "format": "GTiff"})]:
        nodes = graph(data={"from_node": "other"})
        nodes["other"] = {"process_id": process, "arguments": arguments}
        with pytest.raises(ValueError, match="raster cube"):
            validate(nodes)
    spec = Processes().get_process_registry("1.2.0").get_spec("local_ee_neighborhood")
    assert [p["name"] for p in spec["parameters"]] == ["data", "spec"]
    assert spec["parameters"][1]["schema"]["maxLength"] == 32768
