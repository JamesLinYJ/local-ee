"""Offline dual-client composition checks for Image.distance workflows."""
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
EXAMPLE = ROOT / "examples/52_GEE_python_distance.py"
ROI = {"type": "Polygon", "coordinates": [[
    [100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
    [100.2, 30.8], [100.2, 30.2],
]]}
OUTPUT_NAMES = {
    "euclidean", "manhattan", "chebyshev", "water_distance", "water_buffer",
    "masked_clipped_distance", "multi_band_distance", "observation_distance",
    "clipped_water_buffer",
}


def _example():
    spec = importlib.util.spec_from_file_location("distance_workflow_example", EXAMPLE)
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


def _encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def python_results():
    metadata, items = _catalog()
    captured_maps = []
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert ee.__version__ == "1.7.49"
        outputs = _example().build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))
        assert set(outputs) == OUTPUT_NAMES
        compiled = {
            name: compile_expression(_encode(ee, value), [metadata], items)
            for name, value in outputs.items()
        }
        original_send = ee.Map._send
        ee.Map._send = lambda payload: captured_maps.append(payload) or {"job_id": "wave47-distance-map"}
        try:
            ee.Map.addLayer(
                outputs["clipped_water_buffer"],
                {"min": 0, "max": 1, "palette": ["000000", "00aaff"]},
                "Water within two pixels",
            )
        finally:
            ee.Map._send = original_send

        task = _example().build_export_task(ee, outputs["clipped_water_buffer"])
        exported = {
            key: (_encode(ee, value) if key in {"expression", "region"} else value)
            for key, value in task.config.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    assert len(captured_maps) == 1
    map_result = compile_expression(captured_maps[0]["expression"], [metadata], items)
    return compiled, map_result, captured_maps[0]["options"], exported, metadata, items


def javascript_results():
    node = shutil.which("node") or str(
        ROOT / ".native/toolchains/node-v24.22.1-darwin-arm64/bin/node"
    )
    if not Path(node).is_file():
        pytest.skip("Node is required for pinned JavaScript SDK serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const collection = ee.ImageCollection('sentinel-2-l2a');
const scene = collection.first();
const roi = ee.Geometry.Rectangle([100.2, 30.2, 100.8, 30.8], 'EPSG:4326', false);
const euclidean = ee.Kernel.euclidean({radius:3, units:'pixels', normalize:false, magnitude:1});
const manhattan = ee.Kernel.manhattan({radius:3, units:'pixels', normalize:false, magnitude:1});
const chebyshev = ee.Kernel.chebyshev({radius:3, units:'pixels', normalize:false, magnitude:1});
const waterTargets = scene.select('SCL').eq(6).rename('water_target');
const waterDistance = waterTargets.distance(euclidean, true);
const waterBuffer = waterDistance.toFloat().lte(2).rename('water_within_2_pixels');
const maskedClippedDistance = scene.select('nir')
  .updateMask(scene.select('SCL').gte(0)).clip(roi).distance(euclidean);
const outputs = {
  euclidean: scene.select('nir').distance(euclidean),
  manhattan: scene.select('nir').distance(manhattan),
  chebyshev: scene.select('nir').distance(chebyshev),
  water_distance: waterDistance,
  water_buffer: waterBuffer,
  masked_clipped_distance: maskedClippedDistance,
  multi_band_distance: scene.select(['nir','red']).distance(euclidean),
  observation_distance: collection.select('SCL').map(image =>
    image.eq(6).distance(euclidean).rename('water_distance')),
  clipped_water_buffer: waterBuffer.clip(roi)
};
const task = ee.batch.Export.image.toDrive({
  image:outputs.clipped_water_buffer,
  description:'synthetic_water_distance_buffer',
  folder:'distance',
  fileNamePrefix:'synthetic_water_distance_buffer',
  region:[[[100.2,30.2],[100.8,30.2],[100.8,30.8],[100.2,30.8],[100.2,30.2]]],
  scale:10,
  crs:'EPSG:32649',
  maxPixels:100000
});
console.log(JSON.stringify({
  attempts,
  outputs:Object.fromEntries(Object.entries(outputs).map(([name,value]) =>
    [name,ee.Serializer.encode(value)])),
  export:{
      expression:ee.Serializer.encode(task.config_.element),
      region:(() => {
        const value = JSON.parse(task.config_.region);
        return Array.isArray(value) ? {type:'Polygon', coordinates:value} : value;
      })(),
    scale:task.config_.scale,
    crs:task.config_.crs,
    maxPixels:task.config_.maxPixels,
      fileFormat:task.config_.fileFormat === 'GEO_TIFF' ? 'GeoTIFF' : task.config_.fileFormat,
      folder:task.config_.driveFolder,
      fileNamePrefix:task.config_.driveFileNamePrefix
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


def _depends_on(graph, node_id, ancestor_id):
    pending, seen = [node_id], set()
    while pending:
        current = pending.pop()
        if current == ancestor_id:
            return True
        if current in seen or current not in graph:
            continue
        seen.add(current)
        pending.extend(
            value["from_node"]
            for value in graph[current]["arguments"].values()
            if isinstance(value, dict) and set(value) == {"from_node"}
        )
    return False


def _nodes(compiled, process_id):
    return [(key, node) for key, node in compiled["process_graph"].items()
            if node["process_id"] == process_id]


def test_python_and_javascript_sdk_1749_build_the_same_distance_graphs():
    python, map_result, map_options, python_export, metadata, items = python_results()
    javascript = javascript_results()
    assert set(javascript["outputs"]) == OUTPUT_NAMES == set(python)
    for name, expression in javascript["outputs"].items():
        compiled = compile_expression(expression, [metadata], items)
        assert compiled == python[name], name

    assert map_result == python["clipped_water_buffer"]
    assert map_options == {
        "vis_params": {"min": 0, "max": 1, "palette": ["000000", "00aaff"]},
        "name": "Water within two pixels",
        "shown": True,
        "opacity": 1,
    }

    js_export = javascript["export"]
    assert js_export["scale"] == python_export["scale"] == 10
    assert js_export["crs"] == python_export["crs"] == "EPSG:32649"
    assert js_export["maxPixels"] == python_export["maxPixels"] == 100_000
    assert js_export["folder"] == python_export["folder"] == "distance"
    assert js_export["fileNamePrefix"] == python_export["fileNamePrefix"] == \
        "synthetic_water_distance_buffer"
    assert js_export["region"]["type"] == python_export["region"]["type"] == "Polygon"
    assert js_export["region"]["coordinates"] == python_export["region"]["coordinates"]
    assert compile_expression(js_export["expression"], [metadata], items,
                              options={"region": ROI, "scale": 10,
                                       "crs": "EPSG:32649"}) == \
        compile_expression(python_export["expression"], [metadata], items,
                           options={"region": ROI, "scale": 10,
                                    "crs": "EPSG:32649"})
    exported = compile_expression(
        python_export["expression"], [metadata], items,
        options={"region": ROI, "scale": 10, "crs": "EPSG:32649"},
    )
    graph = exported["process_graph"]
    distance_ids = [key for key, _ in _nodes(exported, "local_ee_distance")]
    clip_ids = [key for key, _ in _nodes(exported, "mask_polygon")]
    assert distance_ids and clip_ids
    assert any(_depends_on(graph, clip_id, distance_id)
               for clip_id in clip_ids for distance_id in distance_ids)
    assert python["multi_band_distance"]["bands"] == ["nir", "red"]
    assert python["observation_distance"]["kind"] == "collection"
    assert python["observation_distance"]["source_item_ids"] == ["scene-a", "scene-b", "scene-c"]

    masked_graph = python["masked_clipped_distance"]["process_graph"]
    masked_distance_ids = [key for key, node in masked_graph.items()
                           if node["process_id"] == "local_ee_distance"]
    assert len(masked_distance_ids) == 1
    distance_data = masked_graph[masked_distance_ids[0]]["arguments"]["data"]
    assert isinstance(distance_data, dict) and set(distance_data) == {"from_node"}
    source_id = distance_data["from_node"]
    assert masked_graph[source_id]["process_id"] == "mask_polygon"
    mask_id = masked_graph[source_id]["arguments"]["data"]["from_node"]
    assert masked_graph[mask_id]["process_id"] == "mask"
    selected_id = masked_graph[mask_id]["arguments"]["data"]["from_node"]
    assert masked_graph[selected_id]["process_id"] == "local_ee_drop_single_time"
    cast_id = masked_graph[selected_id]["arguments"]["data"]["from_node"]
    assert masked_graph[cast_id]["process_id"] == "local_ee_to_double"


def test_distance_compiler_rejects_noncanonical_kernels_and_float64_comparison():
    metadata, items = _catalog()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        image = ee.ImageCollection("sentinel-2-l2a").first().select("SCL").eq(6)
        invalid = [
            lambda: image.distance(ee.Kernel.square(radius=1)),
            lambda: image.distance(ee.Kernel.euclidean(radius=2, normalize=True)),
            lambda: image.distance(ee.Kernel.euclidean(radius=2, magnitude=2)),
            lambda: image.distance(ee.Kernel.euclidean(radius=2, units="meters")),
            lambda: image.distance(ee.Kernel.euclidean(radius=2), skipMasked=1),
            lambda: image.distance(ee.Kernel.euclidean(radius=2)).lte(1),
        ]
        for make_expression in invalid:
            with pytest.raises(UnsupportedEEError):
                expression = make_expression()
                compile_expression(_encode(ee, expression), [metadata], items)

        valid = image.distance(ee.Kernel.euclidean(radius=2)).toFloat().lte(1)
        result = compile_expression(_encode(ee, valid), [metadata], items)
    assert guard.evidence()["attempt_count"] == 0
    assert _nodes(result, "local_ee_distance")
