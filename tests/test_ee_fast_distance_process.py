"""Fast-distance public wire, raster lineage and optimizer boundaries."""
import json

import pytest

from gee.backend import Processes
from gee.fast_distance_spec import decode_fast_distance_spec, prepare_fast_distance_spec
from gee.graph import validate
from gee.local_processes import validate_local_process


PROCESS = "local_ee_fast_distance_transform"


def graph(spec=None, **extra):
    return {
        "load": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "distance": {"process_id": PROCESS, "result": True, "arguments": {
            "data": {"from_node": "load"},
            "spec": prepare_fast_distance_spec() if spec is None else spec,
            **extra,
        }},
    }


@pytest.mark.parametrize("metric", ["squared_euclidean", "manhattan", "chebyshev"])
@pytest.mark.parametrize("neighborhood", [1, 17, 256, 4096])
def test_canonical_metric_and_integer_neighborhood_pass_public_graph(metric, neighborhood):
    text = prepare_fast_distance_spec(metric, neighborhood)
    assert decode_fast_distance_spec(text) == {
        "metric": metric, "neighborhood": neighborhood, "v": 1,
    }
    validate(graph(text))


@pytest.mark.parametrize("value", [None, True, [], {}, "256", 0, -1, 1.5,
                                  256.0, 4097, float("inf"), 10**1000])
def test_wire_requires_bounded_integer_neighborhood(value):
    with pytest.raises(ValueError):
        prepare_fast_distance_spec(neighborhood=value)


@pytest.mark.parametrize("field,value", [
    ("metric", "euclidean"), ("metric", []), ("metric", None),
    ("neighborhood", 256.0), ("neighborhood", True), ("neighborhood", 0),
    ("neighborhood", 4097), ("v", True), ("v", 1.0), ("v", 2),
])
def test_public_graph_revalidates_wire_fields(field, value):
    spec = decode_fast_distance_spec(prepare_fast_distance_spec())
    spec[field] = value
    with pytest.raises(ValueError):
        validate(graph(json.dumps(spec, sort_keys=True, separators=(",", ":"))))


@pytest.mark.parametrize("text", [None, {}, "[]", "{}", "é", "x" * 1025,
                                  "[" * 1001, '{"v":1,"v":1}'])
def test_malformed_or_unbounded_wire_rejects(text):
    with pytest.raises(ValueError):
        decode_fast_distance_spec(text)


def test_noncanonical_order_whitespace_extra_and_trailing_content_reject():
    text = prepare_fast_distance_spec()
    for invalid in (text + " ", text + text, text[:-1] + ',"extra":true}',
                    json.dumps(decode_fast_distance_spec(text), indent=2),
                    '{"v":1,"neighborhood":256,"metric":"squared_euclidean"}'):
        with pytest.raises(ValueError):
            decode_fast_distance_spec(invalid)


def test_only_top_level_direct_raster_producers_enter_transform():
    for value in (None, "/tmp/example.tif", {"from_parameter": "data"},
                  {"from_node": "load", "extra": 1}):
        with pytest.raises(ValueError):
            validate(graph(data=value))
    with pytest.raises(ValueError, match="top-level"):
        validate_local_process(PROCESS, graph()["distance"]["arguments"], 1)
    with pytest.raises(ValueError):
        validate(graph(extra=True))
    for process, arguments in [("add", {"x": 1, "y": 2}),
                               ("save_result", {"data": {"from_node": "load"}, "format": "GTiff"})]:
        nodes = graph(data={"from_node": "other"})
        nodes["other"] = {"process_id": process, "arguments": arguments}
        with pytest.raises(ValueError, match="raster cube"):
            validate(nodes)
    spec = Processes().get_process_registry("1.2.0").get_spec(PROCESS)
    assert spec["experimental"] is True
    assert [p["name"] for p in spec["parameters"]] == ["data", "spec"]
    assert spec["parameters"][1]["schema"] == {"type": "string", "maxLength": 1024}
    assert "Local v1 policy" in spec["description"]
    assert "Google same-data" in spec["description"]
