"""Strict binary coefficient wire and typed public convolution graph contracts."""
import json
import math
import struct

import pytest

from gee.backend import Processes
from gee.convolve_spec import decode_convolve_spec, prepare_convolve_spec
from gee.graph import validate
from gee.local_processes import validate_local_process


def graph(spec=None, **extra):
    return {
        "load": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "convolve": {"process_id": "local_ee_convolve", "result": True, "arguments": {
            "data": {"from_node": "load"},
            "spec": spec if spec is not None else prepare_convolve_spec([(0, 0, 1.0)]),
            **extra,
        }},
    }


def test_exact_coefficient_roundtrip_and_owned_canonical_order():
    values = [[32, 0, math.ulp(0.0)], [-32, -1, -1.0], [0, 0, -0.0]]
    text = prepare_convolve_spec(values)
    values[0][2] = 3.0
    assert decode_convolve_spec(text) == {"v": 1, "coefficients": [
        [-32, -1, "bff0000000000000"], [0, 0, "0000000000000000"],
        [32, 0, "0000000000000001"],
    ]}
    validate(graph(text))


def test_maximum_kernel_and_extreme_finite_weights_fit_wire():
    weight = float.fromhex("0x1.fffffffffffffp+1023")
    text = prepare_convolve_spec([(x, y, weight) for y in range(-16, 17) for x in range(-16, 17)])
    assert len(text) <= 32768
    assert len(decode_convolve_spec(text)["coefficients"]) == 1089
    assert struct.unpack(">d", bytes.fromhex(decode_convolve_spec(text)["coefficients"][0][2]))[0] == weight


@pytest.mark.parametrize("coefficients", [
    [], iter([(0, 0, 1.0)]), [(0, 0, 1.0)] * 1090,
    [[True, 0, 1.0]], [[0, 0.0, 1.0]], [[33, 0, 1.0]],
    [[0, 0, 1]], [[0, 0, True]], [[0, 0, float("nan")]],
    [[0, 0, float("inf")]], [[0, 0, 1.0], [0, 0, -1.0]], [[0, 0]],
])
def test_encoder_rejects_invalid_shapes_types_or_unbounded_sources(coefficients):
    with pytest.raises(ValueError):
        prepare_convolve_spec(coefficients)


@pytest.mark.parametrize("field,value", [
    ("v", True), ("v", 1.0), ("v", 2), ("coefficients", []),
    ("coefficients", [[True, 0, "3ff0000000000000"]]),
    ("coefficients", [[0, 0, "7ff0000000000000"]]),
    ("coefficients", [[0, 0, "7ff8000000000000"]]),
    ("coefficients", [[0, 0, "fff0000000000000"]]),
    ("coefficients", [[0, 0, "8000000000000000"]]),
    ("coefficients", [[0, 0, "3FF0000000000000"]]),
    ("coefficients", [[0, 0, " 3ff0000000000000"]]),
    ("coefficients", [[0, 0, 1.0]]),
    ("coefficients", [[1, 0, "3ff0000000000000"], [0, 0, "3ff0000000000000"]]),
    ("coefficients", [[0, 0, "3ff0000000000000"]] * 2),
    ("coefficients", [[0, 0, "3ff0000000000000"]] * 1090),
])
def test_decoder_and_public_graph_reject_malformed_wire(field, value):
    spec = decode_convolve_spec(prepare_convolve_spec([(0, 0, 1.0)]))
    spec[field] = value
    with pytest.raises(ValueError):
        validate(graph(json.dumps(spec, sort_keys=True, separators=(",", ":"))))


@pytest.mark.parametrize("text", [
    "{}", "[]", "[" * 1001, "x" * 32769, "é", None, {},
    '{"v":1,"v":1}', '{"coefficients":[[0,0,"3ff0000000000000"]],"v":1} ',
])
def test_decoder_rejects_noncanonical_or_unbounded_json(text):
    with pytest.raises(ValueError):
        decode_convolve_spec(text)


@pytest.mark.parametrize("data", [None, "/tmp/a.tif", {"from_parameter": "data"},
                                  {"from_node": "load", "extra": 1}])
def test_convolve_requires_only_direct_cube_references(data):
    with pytest.raises(ValueError):
        validate(graph(data=data))


def test_callbacks_and_extra_arguments_are_not_convolution_parameters():
    with pytest.raises(ValueError, match="top-level"):
        validate_local_process("local_ee_convolve", graph()["convolve"]["arguments"], 1)
    with pytest.raises(ValueError):
        validate(graph(extra=True))


@pytest.mark.parametrize("source", [
    {"process_id": "save_result", "arguments": {"data": {"from_node": "load"}, "format": "GTiff"}},
    {"process_id": "add", "arguments": {"x": 1, "y": 2}},
    {"process_id": "aggregate_spatial", "arguments": {"data": {"from_node": "load"}, "geometries": {}}},
])
def test_convolve_rejects_scalar_table_or_saved_result_producers(source):
    nodes = graph()
    nodes["other"] = source
    nodes["convolve"]["arguments"]["data"] = {"from_node": "other"}
    with pytest.raises(ValueError, match="raster cube"):
        validate(nodes)


def test_public_spec_has_only_cube_and_bounded_text():
    spec = Processes().get_process_registry("1.2.0").get_spec("local_ee_convolve")
    assert [p["name"] for p in spec["parameters"]] == ["data", "spec"]
    assert spec["parameters"][1]["schema"] == {"type": "string", "maxLength": 32768}
    assert spec["returns"]["schema"]["subtype"] == "raster-cube"
