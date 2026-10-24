"""Image.remap compiler contract through the pinned offline Python SDK."""
import json
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from gee.integer_values_spec import constant_operand


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


@pytest.fixture
def local():
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["x", "y"]}},
    }]
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]],
    }
    items = {"sentinel-2-l2a": [
        {"id": name, "bbox": [0, 0, 2, 1], "geometry": geometry,
         "properties": {"system:index": name, "system:time_start": index * 1000}}
        for index, name in enumerate(("scene-a", "scene-b"), 1)
    ]}
    return catalog, items


def compile_value(ee, value, local):
    return compile_expression(ee.serializer.encode(value, for_cloud_api=False), *local)


def test_remap_compiles_selected_band_with_canonical_wire_and_preserved_metadata(ee, local):
    clip = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
    }
    base = ee.Image("scene-a").set("marker", "kept")
    with pytest.raises(UnsupportedEEError, match="Image.clip spherical geometry edges"):
        compile_value(ee, base.clip(clip).remap(
            [1, 2.5], [7.25, 8], defaultValue=0, bandName="y"), local)
    image = base.clip({**clip, "geodesic": False})
    result = compile_value(
        ee, image.remap([1, 2.5], [7.25, 8], defaultValue=0, bandName="y"), local,
    )

    assert result["kind"] == "image"
    assert result["bands"] == ["remapped"]
    assert result["properties"]["marker"] == "kept"
    assert result["source_item_ids"] == ["scene-a"]
    validate(result["process_graph"])
    graph = result["process_graph"]
    remap = [(key, node) for key, node in graph.items()
             if node["process_id"] == "local_ee_remap"]
    assert len(remap) == 1
    remap_id, remap_node = remap[0]
    assert set(remap_node["arguments"]) == {"data", "spec"}
    assert json.loads(remap_node["arguments"]["spec"]) == {
        "version": 1, "from": [1, 2.5], "to": [7.25, 8], "default": 0,
    }
    loads = [node["arguments"] for node in graph.values()
             if node["process_id"] == "load_collection"]
    assert len(loads) == 1 and loads[0]["bands"] == ["y"]
    assert any(node["process_id"] == "mask_polygon" for node in graph.values())
    assert any(node["process_id"] == "rename_labels"
               and node["arguments"].get("target") == ["remapped"]
               and node["arguments"].get("data") == {"from_node": remap_id}
               for node in graph.values())


def test_remap_empty_mapping_and_map_rebinding_keep_temporal_source(ee, local):
    collection = ee.ImageCollection("sentinel-2-l2a").filter(
        ee.Filter.eq("system:index", "scene-b")
    )
    result = compile_value(
        ee,
        collection.map(lambda image: ee.Image(image).remap([1], [2], bandName="x")),
        local,
    )

    assert result["kind"] == "collection"
    assert result["bands"] == ["remapped"]
    assert result["has_time_dimension"] is True
    assert result["source_item_ids"] == ["scene-b"]
    graph = result["process_graph"]
    remap = next(node for node in graph.values()
                 if node["process_id"] == "local_ee_remap")
    assert json.loads(remap["arguments"]["spec"]) == {
        "version": 1, "from": [1], "to": [2], "default": None,
    }


def test_empty_mapping_is_accepted_from_the_serialized_protocol(local):
    expression = {
        "type": "Invocation", "functionName": "Image.remap", "arguments": {
            "image": {"type": "Invocation", "functionName": "Image.load",
                      "arguments": {"id": "scene-a"}},
            "from": [], "to": [],
        },
    }
    result = compile_expression(expression, *local)
    remap = next(node for node in result["process_graph"].values()
                 if node["process_id"] == "local_ee_remap")
    assert json.loads(remap["arguments"]["spec"]) == {
        "version": 1, "from": [], "to": [], "default": None,
    }


@pytest.mark.parametrize("value, message", [
    (lambda ee: ee.Image("scene-a").remap([1, 2], [3]), "equal-length"),
    (lambda ee: ee.Image("scene-a").remap([0.0, -0.0], [3, 4]), "numerically unique"),
    (lambda ee: ee.Image("scene-a").remap([1], [True]), "finite numbers"),
    (lambda ee: ee.Image("scene-a").remap([1], [2], defaultValue=False), "finite numbers"),
    (lambda ee: ee.Image.constant(1).remap([1], [2]), "bound scalar input band"),
    (lambda ee: ee.Image("scene-a").toArray().remap([1], [2]), "array images"),
    (lambda ee: ee.Image("scene-a").remap([ee.Array([1])], [2]), "finite numbers"),
    (lambda ee: ee.Image("scene-a").remap([1] * 257, [2] * 257), "0..256"),
])
def test_remap_rejects_unsupported_values_and_array_inputs(ee, local, value, message):
    with pytest.raises(UnsupportedEEError, match=message):
        compile_value(ee, value(ee), local)


def test_remap_requires_unique_explicit_band_and_rejects_unknown_parameters(ee, local):
    with pytest.raises(UnsupportedEEError, match="exactly one input band"):
        compile_value(ee, ee.Image("scene-a").remap([1], [2], bandName="missing"), local)

    expression = ee.serializer.encode(
        ee.Image("scene-a").remap([1], [2]), for_cloud_api=False,
    )
    invocation = next(node for _, node in expression["scope"]
                      if isinstance(node, dict) and node.get("functionName") == "Image.remap")
    invocation["arguments"]["unexpected"] = 1
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(expression, *local)


def test_remap_marks_native_float64_and_bypasses_float32_callback(ee, local):
    remapped = ee.Image("scene-a").select("x").toDouble().remap([1], [2.5])
    result = compile_value(ee, remapped, local)
    process_ids = [node["process_id"] for node in result["process_graph"].values()]
    assert "local_ee_remap" in process_ids
    assert "local_ee_to_double" in process_ids
    assert all(not (node["process_id"] == "reduce_dimension"
                    and node["arguments"].get("dimension") == "bands")
               for node in result["process_graph"].values())

    arithmetic = compile_value(ee, remapped.add(1), local)
    validate(arithmetic["process_graph"])
    integer = [node for node in arithmetic["process_graph"].values()
               if node["process_id"] == "local_ee_integer_values"]
    assert len(integer) == 1
    integer_node = integer[0]
    assert json.loads(integer_node["arguments"]["spec"]) == {
        "dtype": None, "op": "add",
        "operands": [{"band": 0}, constant_operand(1)], "v": 1,
    }
    remap = [(key, node) for key, node in arithmetic["process_graph"].items()
             if node["process_id"] == "local_ee_remap"]
    assert len(remap) == 1
    input_ref = integer_node["arguments"]["data"]["from_node"]
    input_node = arithmetic["process_graph"][input_ref]
    assert input_node["process_id"] == "rename_labels"
    assert input_node["arguments"]["data"] == {"from_node": remap[0][0]}
    assert not any(node["process_id"] == "reduce_dimension"
                   for node in arithmetic["process_graph"].values())
