"""Canonical illumination wire and audited raster-producer validation."""
import json
import struct

import pytest

from gee.backend import Processes
from gee.graph import validate
from gee.local_processes import validate_local_process
from gee.terrain_spec import decode_terrain_spec, prepare_terrain_spec


def graph(spec=None, **extra):
    return {
        "load": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "terrain": {"process_id": "local_ee_terrain", "result": True, "arguments": {
            "data": {"from_node": "load"},
            "spec": prepare_terrain_spec("slope") if spec is None else spec, **extra,
        }},
    }


@pytest.mark.parametrize("operation", ["slope", "aspect", "hillshade"])
def test_supported_terrain_wire_is_canonical_and_default_angles_are_exact(operation):
    text = prepare_terrain_spec(operation)
    assert len(text) <= 1024
    assert decode_terrain_spec(text) == {
        "operation": operation, "v": 1,
        "azimuth": struct.pack(">d", 270.0).hex(),
        "elevation": struct.pack(">d", 45.0).hex(),
    }
    validate(graph(text))


@pytest.mark.parametrize("angle,expected", [(0, 0), (-0.0, 0), (360, 0), (-90, 270),
                                             (765, 45), (-5e-324, 0)])
def test_illumination_periodicity_and_positive_zero_are_explicit(angle, expected):
    text = prepare_terrain_spec("hillshade", angle, angle)
    spec = decode_terrain_spec(text)
    assert spec["azimuth"] == spec["elevation"] == struct.pack(">d", float(expected)).hex()
    validate(graph(text))


@pytest.mark.parametrize("value", [True, None, [], {}, "270", float("nan"), float("inf"), 2**53+1])
def test_invalid_illumination_does_not_silently_coerce(value):
    with pytest.raises(ValueError):
        prepare_terrain_spec("hillshade", value, 45)
    with pytest.raises(ValueError):
        prepare_terrain_spec("hillshade", 270, value)


@pytest.mark.parametrize("field,value", [
    ("v", True), ("v", 1.0), ("v", 2), ("operation", "products"), ("operation", []),
    ("azimuth", "8000000000000000"), ("azimuth", "c056800000000000"),
    ("azimuth", "4076800000000000"), ("azimuth", "7ff0000000000000"),
    ("azimuth", "7ff8000000000000"), ("azimuth", "3FF0000000000000"),
    ("azimuth", 270), ("elevation", None), ("elevation", "x" * 16),
])
def test_public_graph_revalidates_all_wire_fields(field, value):
    spec = decode_terrain_spec(prepare_terrain_spec("hillshade"))
    spec[field] = value
    with pytest.raises(ValueError):
        validate(graph(json.dumps(spec, sort_keys=True, separators=(",", ":"))))


def test_nonhillshade_illumination_fields_cannot_be_ignored():
    for operation in ("slope", "aspect"):
        with pytest.raises(ValueError, match="default"):
            prepare_terrain_spec(operation, 0, 45)
        spec = decode_terrain_spec(prepare_terrain_spec("hillshade", 20, 30))
        spec["operation"] = operation
        with pytest.raises(ValueError, match="default"):
            decode_terrain_spec(json.dumps(spec, sort_keys=True, separators=(",", ":")))


@pytest.mark.parametrize("text", ["{}", "[]", "[" * 1001, "x" * 1025, "é", None, {},
                                  '{"v":1,"v":1}'])
def test_malformed_or_unbounded_json_fails(text):
    with pytest.raises(ValueError):
        decode_terrain_spec(text)


def test_canonical_order_unknown_fields_and_whitespace_are_rejected():
    text = prepare_terrain_spec("slope")
    for invalid in (text + " ", text[:-1] + ',"extra":true}',
                    json.dumps(decode_terrain_spec(text), indent=2)):
        with pytest.raises(ValueError):
            decode_terrain_spec(invalid)


def test_terrain_requires_direct_raster_reference_and_no_callback_or_extra_options():
    for data in (None, "/tmp/a.tif", {"from_parameter": "data"}, {"from_node": "load", "x": 1}):
        with pytest.raises(ValueError):
            validate(graph(data=data))
    with pytest.raises(ValueError, match="top-level"):
        validate_local_process("local_ee_terrain", graph()["terrain"]["arguments"], 1)
    with pytest.raises(ValueError):
        validate(graph(spacing=1))
    for process, arguments in [("add", {"x": 1, "y": 2}),
                               ("save_result", {"data": {"from_node": "load"}, "format": "GTiff"})]:
        nodes = graph(data={"from_node": "other"})
        nodes["other"] = {"process_id": process, "arguments": arguments}
        with pytest.raises(ValueError, match="raster cube"):
            validate(nodes)
    spec = Processes().get_process_registry("1.2.0").get_spec("local_ee_terrain")
    assert [p["name"] for p in spec["parameters"]] == ["data", "spec"]
    assert spec["parameters"][1]["schema"]["maxLength"] == 1024
