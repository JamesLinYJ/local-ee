"""Public distance wire, producer and optimizer boundaries."""
import json
import math
import struct

import pytest

from gee.backend import Processes
from gee.distance_spec import decode_distance_spec, prepare_distance_spec
from gee.graph import validate
from gee.local_processes import validate_local_process


def graph(spec=None, **extra):
    return {
        "load": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "distance": {"process_id": "local_ee_distance", "result": True, "arguments": {
            "data": {"from_node": "load"},
            "spec": prepare_distance_spec("euclidean", 2) if spec is None else spec,
            **extra,
        }},
    }


@pytest.mark.parametrize("metric", ["euclidean", "manhattan", "chebyshev"])
@pytest.mark.parametrize("radius", [0, -0.0, 5e-324, 0.5, math.nextafter(math.sqrt(2), 0), 16])
def test_canonical_distance_preserves_exact_radius_and_masks(metric, radius):
    text = prepare_distance_spec(metric, radius, False)
    spec = decode_distance_spec(text)
    assert spec == {"metric": metric, "radius": struct.pack(">d", radius or 0).hex(),
                    "skip_masked": False, "v": 1}
    validate(graph(text))


@pytest.mark.parametrize("radius", [True, None, [], {}, "2", -1, -5e-324,
                                     16.000000000000004, float("nan"), float("inf"), 10**1000])
def test_encoder_rejects_invalid_radius_before_conversion(radius):
    with pytest.raises(ValueError):
        prepare_distance_spec("euclidean", radius)


@pytest.mark.parametrize("field,value", [
    ("v", True), ("v", 1.0), ("v", 2), ("metric", []), ("metric", "squared_euclidean"),
    ("skip_masked", 1), ("skip_masked", None), ("radius", 2), ("radius", []),
    ("radius", "8000000000000000"), ("radius", "c000000000000000"),
    ("radius", "4030000000000001"), ("radius", "7ff0000000000000"),
    ("radius", "7ff8000000000000"), ("radius", "3FF0000000000000"),
])
def test_graph_revalidates_untrusted_wire(field, value):
    spec = decode_distance_spec(prepare_distance_spec("euclidean", 2))
    spec[field] = value
    with pytest.raises(ValueError):
        validate(graph(json.dumps(spec, sort_keys=True, separators=(",", ":"))))


@pytest.mark.parametrize("text", ["{}", "[]", "[" * 1001, "x" * 1025, "é", None, {},
                                  '{"v":1,"v":1}'])
def test_malformed_unbounded_or_duplicate_wire_rejects(text):
    with pytest.raises(ValueError):
        decode_distance_spec(text)


def test_canonical_order_extra_fields_and_trailing_content_reject():
    text = prepare_distance_spec("manhattan", 16)
    for invalid in (text + " ", text + text, text[:-1] + ',"extra":true}',
                    json.dumps(decode_distance_spec(text), indent=2)):
        with pytest.raises(ValueError):
            decode_distance_spec(invalid)


def test_only_direct_top_level_raster_producer_is_accepted():
    for value in (None, "/tmp/a.tif", {"from_parameter": "data"},
                  {"from_node": "load", "extra": 1}):
        with pytest.raises(ValueError):
            validate(graph(data=value))
    with pytest.raises(ValueError, match="top-level"):
        validate_local_process("local_ee_distance", graph()["distance"]["arguments"], 1)
    with pytest.raises(ValueError):
        validate(graph(extra=True))
    for process, arguments in [("add", {"x": 1, "y": 2}),
                               ("save_result", {"data": {"from_node": "load"}, "format": "GTiff"})]:
        nodes = graph(data={"from_node": "other"})
        nodes["other"] = {"process_id": process, "arguments": arguments}
        with pytest.raises(ValueError, match="raster cube"):
            validate(nodes)
    spec = Processes().get_process_registry("1.2.0").get_spec("local_ee_distance")
    assert [p["name"] for p in spec["parameters"]] == ["data", "spec"]
    assert spec["parameters"][1]["schema"] == {"type": "string", "maxLength": 1024}
