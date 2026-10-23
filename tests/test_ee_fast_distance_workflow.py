"""Offline official-client graph checks for Image.fastDistanceTransform."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/53_GEE_python_fast_distance.py"
ROI = {"type": "Polygon", "coordinates": [[
    [100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
    [100.2, 30.8], [100.2, 30.2],
]]}
OUTPUT_NAMES = {"default_distance", "explicit_default_distance", "null_default_distance",
                "squared_euclidean", "manhattan", "chebyshev", "water_dilation",
                "water_erosion", "masked_double_distance", "multiband_distance",
                "observation_distance", "export_image"}


def _example():
    spec = importlib.util.spec_from_file_location("fast_distance_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalog():
    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"].update({
            "proj:code": "EPSG:32649",
            "proj:transform": [10, 0, 220000, 0, -10, 3420000],
        })
    return metadata, items


def _encode(ee, value, *, cloud=False):
    return ee.serializer.encode(value, for_cloud_api=cloud)


def _encoded_call_arguments(encoded, function_name):
    if "scope" not in encoded:
        call = encoded["values"][encoded["result"]]["functionInvocationValue"]
    else:
        calls = [node for _, node in encoded["scope"]
                 if isinstance(node, dict) and node.get("functionName") == function_name]
        assert len(calls) == 1
        call = calls[0]
    assert call["functionName"] == function_name
    return call["arguments"]


def python_results():
    metadata, items = _catalog()
    captured_maps = []
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert ee.__version__ == "1.7.49"
        example = _example()
        outputs = example.build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))
        assert set(outputs) == OUTPUT_NAMES

        # The pinned client omits missing and raw-null optional arguments in
        # both the legacy and cloud serializers. Keep this SDK behavior under
        # test because the compiler applies the official defaults afterward.
        for cloud in (False, True):
            default_wire = _encode(ee, outputs["default_distance"], cloud=cloud)
            null_wire = _encode(ee, outputs["null_default_distance"], cloud=cloud)
            assert default_wire == null_wire
            assert set(_encoded_call_arguments(
                default_wire, "Image.fastDistanceTransform",
            )) == {"image"}

        compiled = {
            name: compile_expression(_encode(ee, value), [metadata], items)
            for name, value in outputs.items()
        }
        original_send = ee.Map._send
        ee.Map._send = lambda payload: captured_maps.append(payload) or {
            "job_id": "wave48-fast-distance-map",
        }
        try:
            ee.Map.addLayer(
                outputs["water_dilation"],
                {"min": 0, "max": 1, "palette": ["000000", "00aaff"]},
                "Water dilation (three pixels)",
            )
        finally:
            ee.Map._send = original_send

        task = example.build_export_task(ee, outputs["export_image"])
        exported = {
            key: (_encode(ee, value) if key in {"expression", "region"} else value)
            for key, value in task.config.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    assert len(captured_maps) == 1
    map_result = compile_expression(
        captured_maps[0]["expression"], [metadata], items,
    )
    return compiled, map_result, captured_maps[0]["options"], exported, metadata, items


def javascript_results():
    node = shutil.which("node") or str(
        ROOT / ".native/toolchains/node-v24.22.1-darwin-arm64/bin/node"
    )
    if not Path(node).is_file():
        pytest.skip("Node is required for pinned JavaScript SDK serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const collection = ee.ImageCollection('sentinel-2-l2a'), scene = collection.first();
const scl = scene.select('SCL'), water = scl.eq(6).rename('water_target');
const defaultDistance = water.fastDistanceTransform();
const outputs = {
  default_distance: defaultDistance,
  explicit_default_distance: water.fastDistanceTransform(256, 'pixels', 'squared_euclidean'),
  null_default_distance: water.fastDistanceTransform(null, null, null),
  squared_euclidean: water.fastDistanceTransform(32, 'pixels', 'squared_euclidean'),
  manhattan: water.fastDistanceTransform(32, 'pixels', 'manhattan'),
  chebyshev: water.fastDistanceTransform(32, 'pixels', 'chebyshev'),
  water_dilation: defaultDistance.sqrt().lt(3).rename('water_dilation_3px'),
  water_erosion: water.multiply(scl.neq(6).fastDistanceTransform(32).sqrt().gt(1))
    .rename('water_erosion_1px'),
  masked_double_distance: water.toDouble().updateMask(scl.gte(0)).fastDistanceTransform(24),
  multiband_distance: scene.select(['nir', 'red']).fastDistanceTransform(32),
  observation_distance: collection.select('SCL').map(image => image.eq(6)
    .fastDistanceTransform(32).rename('water_distance')),
  export_image: defaultDistance.sqrt().lt(3).rename('water_dilation_3px')
    .clip(ee.Geometry.Rectangle([100.2, 30.2, 100.8, 30.8], 'EPSG:4326', false))
};
const task = ee.batch.Export.image.toDrive({
  image: outputs.export_image,
  description: 'synthetic_water_fast_distance',
  folder: 'distance', fileNamePrefix: 'synthetic_water_fast_distance',
  region: [[[100.2,30.2],[100.8,30.2],[100.8,30.8],[100.2,30.8],[100.2,30.2]]],
  scale: 10, crs: 'EPSG:32649', maxPixels: 100000
});
const exportRegion = JSON.parse(task.config_.region);
console.log(JSON.stringify({
  attempts,
  outputs: Object.fromEntries(Object.entries(outputs).map(([name, value]) => [name, ee.Serializer.encode(value)])),
  export: {
    expression: ee.Serializer.encode(task.config_.element),
    region: Array.isArray(exportRegion)
      ? {type: 'Polygon', coordinates: exportRegion} : exportRegion,
    scale: task.config_.scale, crs: task.config_.crs, maxPixels: task.config_.maxPixels,
    folder: task.config_.driveFolder, fileNamePrefix: task.config_.driveFileNamePrefix
  }
}));
"""
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["attempts"] == 0
    return value


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


def _nodes(compiled, process_id):
    return [(key, node) for key, node in compiled["process_graph"].items()
            if node["process_id"] == process_id]


def test_python_and_javascript_sdk_1749_build_the_same_fast_distance_workflows():
    python, map_result, map_options, python_export, metadata, items = python_results()
    javascript = javascript_results()
    assert set(javascript["outputs"]) == OUTPUT_NAMES == set(python)
    for name, expression in javascript["outputs"].items():
        compiled = compile_expression(expression, [metadata], items)
        assert compiled == python[name], name

    assert python["default_distance"] == python["null_default_distance"]
    assert python["default_distance"] == python["explicit_default_distance"]
    default_nodes = _nodes(python["default_distance"], "local_ee_fast_distance_transform")
    assert len(default_nodes) == 1
    assert json.loads(default_nodes[0][1]["arguments"]["spec"]) == {
        "metric": "squared_euclidean", "neighborhood": 256, "v": 1,
    }
    for name, metric in (("squared_euclidean", "squared_euclidean"),
                         ("manhattan", "manhattan"), ("chebyshev", "chebyshev")):
        specs = [json.loads(node["arguments"]["spec"])
                 for _, node in _nodes(python[name], "local_ee_fast_distance_transform")]
        assert specs and all(spec["metric"] == metric and spec["neighborhood"] == 32
                             for spec in specs)

    assert map_result == python["water_dilation"]
    assert map_options == {
        "vis_params": {"min": 0, "max": 1, "palette": ["000000", "00aaff"]},
        "name": "Water dilation (three pixels)",
        "shown": True,
        "opacity": 1,
    }
    js_export = javascript["export"]
    assert js_export["scale"] == python_export["scale"] == 10
    assert js_export["crs"] == python_export["crs"] == "EPSG:32649"
    assert js_export["maxPixels"] == python_export["maxPixels"] == 100_000
    assert js_export["folder"] == python_export["folder"] == "distance"
    assert js_export["fileNamePrefix"] == python_export["fileNamePrefix"] == \
        "synthetic_water_fast_distance"
    assert js_export["region"]["type"] == python_export["region"]["type"] == "Polygon"
    assert js_export["region"]["coordinates"] == python_export["region"]["coordinates"]

    options = {"region": ROI, "scale": 10, "crs": "EPSG:32649"}
    js_graph = compile_expression(js_export["expression"], [metadata], items, options=options)
    py_graph = compile_expression(python_export["expression"], [metadata], items, options=options)
    assert js_graph == py_graph
    graph = py_graph["process_graph"]
    fast_ids = [key for key, _ in _nodes(py_graph, "local_ee_fast_distance_transform")]
    clip_ids = [key for key, _ in _nodes(py_graph, "mask_polygon")]
    assert fast_ids and clip_ids
    assert all(set(fast_ids) & _ancestors(graph, clip_id) for clip_id in clip_ids)
    loads = _nodes(py_graph, "load_collection")
    assert loads and all(node["arguments"]["spatial_extent"] == {
        "west": 100, "south": 30, "east": 101, "north": 31,
    } for _, node in loads)

    assert python["multiband_distance"]["bands"] == ["nir", "red"]
    assert python["observation_distance"]["kind"] == "collection"
    assert python["observation_distance"]["source_item_ids"] == [
        "scene-a", "scene-b", "scene-c",
    ]
    masked_graph = python["masked_double_distance"]["process_graph"]
    masked_fast = _nodes(python["masked_double_distance"], "local_ee_fast_distance_transform")
    ancestor_processes = {masked_graph[key]["process_id"]
                          for key in _ancestors(masked_graph, masked_fast[0][0])}
    assert "local_ee_to_double" in ancestor_processes
    assert "mask" in ancestor_processes


def test_fast_distance_rejects_unknown_and_invalid_parameters():
    metadata, items = _catalog()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        image = ee.ImageCollection("sentinel-2-l2a").first().select("SCL").eq(6)
        invalid = [
            lambda: image.fastDistanceTransform(neighborhood=0),
            lambda: image.fastDistanceTransform(neighborhood=True),
            lambda: image.fastDistanceTransform(neighborhood=1.5),
            lambda: image.fastDistanceTransform(neighborhood=4097),
            lambda: image.fastDistanceTransform(units="meters"),
            lambda: image.fastDistanceTransform(metric="euclidean"),
        ]
        for make_expression in invalid:
            with pytest.raises(UnsupportedEEError):
                expression = make_expression()
                compile_expression(_encode(ee, expression), [metadata], items)

        with pytest.raises(TypeError):
            image.fastDistanceTransform(unrecognized=1)
        malformed = _encode(ee, image.fastDistanceTransform())
        call = next(node for _, node in malformed["scope"]
                    if isinstance(node, dict)
                    and node.get("functionName") == "Image.fastDistanceTransform")
        call["arguments"]["unrecognized"] = 1
        with pytest.raises(UnsupportedEEError):
            compile_expression(malformed, [metadata], items)

        for neighborhood in (1, 3.0, 4096):
            compiled = compile_expression(
                _encode(ee, image.fastDistanceTransform(neighborhood=neighborhood)),
                [metadata], items,
            )
            exact_processes = _nodes(compiled, "local_ee_fast_distance_transform")
            assert len(exact_processes) == 1
            assert json.loads(exact_processes[0][1]["arguments"]["spec"])["neighborhood"] == neighborhood
    assert guard.evidence()["attempt_count"] == 0
