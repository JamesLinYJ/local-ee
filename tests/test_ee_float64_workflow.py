"""Offline official Python/JavaScript SDK graph parity for Float64 Image math."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLE = ROOT / "examples/55_GEE_python_float64_analysis.py"
JAVASCRIPT_EXAMPLE = ROOT / "examples/javascript/09_双精度影像分析.js"
COLLECTION_ID = "sentinel-2-l2a"
TEMPERATURE_BAND = "synthetic_temperature_millikelvin"
TEMPERATURE_METADATA = {
    "name": TEMPERATURE_BAND,
    "description": "SYNTHETIC metadata-only millikelvin band; not ERA5 or Sentinel-2 data.",
    "unit": "mK",
    "scale": 0.001,
    "offset": 0.0,
}
EXPORT_REGION = {
    "type": "Polygon",
    "coordinates": [[
        [100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
        [100.2, 30.8], [100.2, 30.2],
    ]],
}
MAP_VIS = {"min": -1, "max": 1}
OUTPUT_NAMES = {
    "qa_packed", "qa_numeric", "qa_clear", "normalized_ndvi",
    "signed_ndvi", "signed_ndvi_core", "synthetic_temperature_celsius",
    "water_distance_pixels", "water_distance_metres", "float32_difference",
    "analysis",
}


def _example():
    spec = importlib.util.spec_from_file_location("float64_analysis_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalog():
    """Metadata-only fixture: optical sample schema plus one declared synthetic band."""
    source_metadata, source_items, _ = synthetic_inputs()
    metadata = copy.deepcopy(source_metadata)
    band_values = metadata["cube:dimensions"]["bands"]["values"]
    band_values.append(TEMPERATURE_BAND)
    metadata["summaries"]["eo:bands"].append(copy.deepcopy(TEMPERATURE_METADATA))
    items = copy.deepcopy(source_items["sentinel-2-l2a"])
    for item in items:
        item["properties"].update({
            "proj:code": "EPSG:32649",
            "proj:transform": [10, 0, 220000, 0, -10, 3420000],
        })
    return metadata, {COLLECTION_ID: items}


def _encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def _python_results():
    metadata, items = _catalog()
    captured_maps = []
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert ee.__version__ == "1.7.49"
        example = _example()
        outputs = example.build_workflow(ee, ee.ImageCollection(COLLECTION_ID))
        assert set(outputs) == OUTPUT_NAMES
        compiled = {
            name: compile_expression(_encode(ee, value), [metadata], items)
            for name, value in outputs.items()
        }

        original_send = ee.Map._send
        ee.Map._send = lambda payload: captured_maps.append(payload) or {
            "job_id": "wave50-float64-map",
        }
        try:
            ee.Map.addLayer(
                outputs["signed_ndvi"], MAP_VIS,
                "Signed Double NDVI (synthetic fixture)",
            )
        finally:
            ee.Map._send = original_send

        task = example.build_export_task(ee, outputs["analysis"])
        exported = {
            key: (_encode(ee, value) if key in {"expression", "region"} else value)
            for key, value in task.config.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    assert len(captured_maps) == 1
    map_result = compile_expression(captured_maps[0]["expression"], [metadata], items)
    return (compiled, map_result, captured_maps[0]["options"], exported,
            metadata, items)


def _javascript_results():
    pinned_node = ROOT / ".native/toolchains/node-v24.22.1-darwin-arm64/bin/node"
    node = str(pinned_node) if pinned_node.is_file() else shutil.which("node")
    if node is None or not Path(node).is_file():
        pytest.skip("Node is required for pinned JavaScript SDK serialization")
    prefix = JAVASCRIPT.split("const config =", 1)[0]
    script = prefix + rf"""
let capturedLayer = null;
const mapStub = {{addLayer: (image, visParams, name) => {{
  capturedLayer = {{image, visParams, name}};
}}}};
const exportStub = ee.batch.Export;
const exampleSource = fs.readFileSync(
  'examples/javascript/09_双精度影像分析.js', 'utf8');
const factory = new Function('Map', 'Export',
  exampleSource + '\nreturn {{outputs, task}};');
const {{outputs:workflow, task}} = factory(mapStub, exportStub);
const taskConfig = task.config_;
const encodedOutputs = Object.fromEntries(Object.entries(workflow).map(([key,value]) =>
  [key, ee.Serializer.encode(value)]));
const exportRegionValue = JSON.parse(taskConfig.region);
console.log(JSON.stringify({{
  attempts,
  outputs:encodedOutputs,
  map:{{expression:ee.Serializer.encode(capturedLayer.image),
    visParams:capturedLayer.visParams, name:capturedLayer.name}},
  export:{{expression:ee.Serializer.encode(taskConfig.element),
    region:Array.isArray(exportRegionValue)
      ? {{type:'Polygon', coordinates:exportRegionValue}} : exportRegionValue,
    scale:taskConfig.scale, crs:taskConfig.crs, maxPixels:taskConfig.maxPixels,
    folder:taskConfig.driveFolder,
    fileNamePrefix:taskConfig.driveFileNamePrefix}}
}}));
"""
    completed = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["attempts"] == 0
    return result


def _specs(compiled):
    return [json.loads(node["arguments"]["spec"])
            for node in _walk_nodes(compiled["process_graph"])
            if node["process_id"] == "local_ee_integer_values"]


def _processes(compiled):
    return [node["process_id"] for node in _walk_nodes(compiled["process_graph"])]


def _walk_nodes(value):
    """Traverse nested reducer subgraphs as well as the outer process graph."""
    if isinstance(value, dict):
        if isinstance(value.get("process_id"), str):
            yield value
        for child in value.values():
            yield from _walk_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_nodes(child)


def _ancestors(graph, node_id):
    pending, seen = [node_id], set()
    while pending:
        current = pending.pop()
        if current in seen or current not in graph:
            continue
        seen.add(current)
        pending.extend(
            value["from_node"]
            for value in graph[current]["arguments"].values()
            if isinstance(value, dict) and set(value) == {"from_node"}
        )
    return seen


def test_python_and_javascript_double_raster_workflow_graphs_match_offline():
    python, map_result, map_options, python_export, metadata, items = _python_results()
    javascript = _javascript_results()
    example = _example()

    assert metadata["id"] == COLLECTION_ID
    assert metadata["summaries"]["eo:bands"][-1] == TEMPERATURE_METADATA
    assert metadata["cube:dimensions"]["bands"]["values"][-1] == TEMPERATURE_BAND
    assert example.TEMPERATURE_SCALE == TEMPERATURE_METADATA["scale"]
    assert example.TEMPERATURE_OFFSET_K == TEMPERATURE_METADATA["offset"]
    assert all(item["properties"]["proj:transform"][0]
               == example.PIXEL_SIZE_METRES for item in items[COLLECTION_ID])
    assert set(javascript["outputs"]) == OUTPUT_NAMES == set(python)
    for name, expression in javascript["outputs"].items():
        assert compile_expression(expression, [metadata], items) == python[name], name

    assert map_result == python["signed_ndvi"]
    assert map_options == {
        "vis_params": MAP_VIS,
        "name": "Signed Double NDVI (synthetic fixture)",
        "shown": True,
        "opacity": 1,
    }
    assert javascript["map"]["visParams"] == MAP_VIS
    assert javascript["map"]["name"] == map_options["name"]
    assert compile_expression(
        javascript["map"]["expression"], [metadata], items,
    ) == python["signed_ndvi"]

    js_export = javascript["export"]
    assert js_export["scale"] == python_export["scale"] == 10
    assert js_export["crs"] == python_export["crs"] == "EPSG:32649"
    assert js_export["maxPixels"] == python_export["maxPixels"] == 100_000
    assert js_export["folder"] == python_export["folder"] == "float64-analysis"
    assert js_export["fileNamePrefix"] == python_export["fileNamePrefix"] == \
        "synthetic_float64_analysis"
    assert js_export["region"] == EXPORT_REGION
    assert python_export["region"]["type"] == "Polygon"
    assert python_export["region"]["coordinates"] == EXPORT_REGION["coordinates"]
    options = {"region": EXPORT_REGION, "scale": 10, "crs": "EPSG:32649"}
    js_export_graph = compile_expression(
        js_export["expression"], [metadata], items, options=options,
    )
    py_export_graph = compile_expression(
        python_export["expression"], [metadata], items, options=options,
    )
    assert js_export_graph == py_export_graph
    assert js_export_graph["bands"] == python["analysis"]["bands"]

    # QA casts carry the Double marker, so general arithmetic needs no toFloat.
    qa_ops = {spec["op"] for spec in _specs(python["qa_numeric"])}
    assert {"cast", "multiply", "add"} <= qa_ops
    assert "local_ee_to_float" not in _processes(python["qa_numeric"])

    # Double reflectance supports both APIs and explicit arithmetic; standard
    # normalizedDifference retains its negative-input mask path.
    for name in ("normalized_ndvi", "signed_ndvi", "signed_ndvi_core"):
        operations = {spec["op"] for spec in _specs(python[name])}
        assert {"add", "subtract", "divide"} <= operations, name
        assert "local_ee_to_float" not in _processes(python[name]), name
    normalized_ops = {spec["op"] for spec in _specs(python["normalized_ndvi"])}
    assert {"lt", "neq"} <= normalized_ops
    assert {"or", "not", "and"} <= set(_processes(python["normalized_ndvi"]))
    assert "mask" in _processes(python["normalized_ndvi"])

    temperature_ops = {spec["op"] for spec in _specs(
        python["synthetic_temperature_celsius"]
    )}
    assert {"multiply", "add", "subtract"} <= temperature_ops
    assert "local_ee_to_double" in _processes(python["synthetic_temperature_celsius"])

    distance_specs = _specs(python["water_distance_pixels"])
    assert any(spec["op"] == "sqrt" for spec in distance_specs)
    distance_processes = _processes(python["water_distance_pixels"])
    assert "local_ee_fast_distance_transform" in distance_processes
    assert "local_ee_to_double" in distance_processes

    # Explicit Float32 remains on the prior graph path and does not get routed
    # through the new Float64 arithmetic core.
    assert "local_ee_to_float" in _processes(python["float32_difference"])
    assert not any(spec["op"] == "subtract"
                   for spec in _specs(python["float32_difference"]))
    assert "local_ee_integer_values" not in _processes(python["float32_difference"])

    # The output graph carries the admitted source and grid evidence. This test
    # only compiles/captures graphs; it never runs a raster or starts an export.
    for output in python.values():
        graph = output.get("process_graph", {})
        for key, node in graph.items():
            if node["process_id"] == "local_ee_integer_values":
                ancestors = _ancestors(graph, key)
                assert any(graph[parent]["process_id"] == "load_collection"
                           for parent in ancestors if parent in graph)
