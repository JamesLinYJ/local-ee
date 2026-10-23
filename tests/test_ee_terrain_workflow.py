"""Pinned SDK graph composition and metadata-only DryRun for terrain workflows."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess

import pytest
from shapely.geometry import shape

from ee_random_split_parity import JAVASCRIPT
from ee_sampling_bridge_helpers import _dry_cube
from engine import ee_process_adapters as adapters
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.terrain_spec import decode_terrain_spec
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
# The compiler recognizes this fixture ID; catalog() supplies only the local
# synthetic metadata below and never loads the named upstream collection.
COLLECTION_ID = "sentinel-2-l2a"
ROI = {"type": "Polygon", "coordinates": [[
    [100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
    [100.2, 30.8], [100.2, 30.2],
]]}
OUTPUT_NAMES = {
    "slope_default", "aspect_default", "hillshade_default",
    "hillshade_explicit_defaults", "hillshade_periodic_angles",
    "products_single_band", "products_multiband", "new_products_only",
    "products_multiband_masked", "hillshade_smoothed_convolved",
    "slope_observations", "mean_slope", "clip_before_products",
    "products_clip_after", "source_neighborhood_bands",
    "slope_neighborhood_bands", "terrain_context_statistics",
    "deprecated_products_alias",
}


def catalog():
    """Two metadata-only scenes on one declared 10 m projected grid."""
    metadata, by_id, _ = synthetic_inputs()
    metadata["id"] = COLLECTION_ID
    metadata["cube:dimensions"]["bands"]["values"] = ["elevation", "quality"]
    metadata["summaries"]["eo:bands"] = [
        {"name": "elevation"}, {"name": "quality"},
    ]
    metadata["extent"]["temporal"]["interval"] = [[
        "2023-11-14T00:00:00Z", "2023-11-16T00:00:00Z",
    ]]
    items = deepcopy(by_id["sentinel-2-l2a"][:2])
    for item in items:
        item["properties"].update({
            "proj:code": "EPSG:32649",
            "proj:transform": [10, 0, 220000, 0, -10, 3420000],
        })
    assert [item["id"] for item in items] == ["scene-a", "scene-b"]
    assert all(item["properties"]["proj:transform"] == [
        10, 0, 220000, 0, -10, 3420000,
    ] for item in items)
    return [metadata], {COLLECTION_ID: items}


def _example():
    spec = importlib.util.spec_from_file_location(
        "terrain_workflow_example", ROOT / "examples/50_GEE_python_terrain.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def python_results(options=None):
    metadata, items = catalog()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert ee.__version__ == "1.7.49"
        outputs = _example().build_workflow(ee, ee.ImageCollection(COLLECTION_ID))
        assert set(outputs) == OUTPUT_NAMES
        compiled = {
            name: compile_expression(
                ee.serializer.encode(value, for_cloud_api=False),
                metadata, items, options=options,
            )
            for name, value in outputs.items()
        }
        task = _example().build_export_task(ee, outputs["products_clip_after"])
        export = {
            key: (ee.serializer.encode(value, for_cloud_api=False)
                  if key in {"expression", "region"} else value)
            for key, value in task.config.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    for result in compiled.values():
        if result.get("kind") == "image" or result.get("kind") == "collection":
            validate(result["process_graph"])
    return compiled, export, metadata, items


def _javascript_expressions():
    node = shutil.which("node") or str(
        ROOT / ".native/toolchains/node-v24.22.1-darwin-arm64/bin/node"
    )
    if not Path(node).is_file():
        pytest.skip("Node is required for pinned JavaScript SDK serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const collection=ee.ImageCollection('sentinel-2-l2a');
const scene=collection.first();
const multiband=scene.select(['elevation','quality'])
 .set('workflow','synthetic-terrain');
const elevation=multiband.select('elevation');
const roi=ee.Geometry.Rectangle([100.2,30.2,100.8,30.8],'EPSG:4326',false);
const offsets=ee.Kernel.fixed(3,3,[[0,-2,0],[0,0,0],[3,0,0]],1,1,false);
const smooth=elevation.focalMean({radius:1,units:'pixels',kernelType:'square'});
const convolved=smooth.convolve(ee.Kernel.gaussian({radius:1,sigma:1}));
const slope=ee.Terrain.slope(elevation);
const neighborhoodSlope=slope.neighborhoodToBands(offsets);
const reducer=ee.Reducer.mean().combine({reducer2:ee.Reducer.stdDev(),sharedInputs:true});
const products=ee.Terrain.products(elevation);
const masked=multiband.updateMask(multiband.select('quality').gt(0));
const outputs={
 slope_default:slope,
 aspect_default:ee.Terrain.aspect(elevation),
 hillshade_default:ee.Terrain.hillshade(elevation),
 hillshade_explicit_defaults:ee.Terrain.hillshade(elevation,null,null),
 hillshade_periodic_angles:ee.Terrain.hillshade(elevation,630,-300),
 products_single_band:products,
 products_multiband:ee.Terrain.products(multiband),
 new_products_only:products.select(['slope','aspect','hillshade']),
 products_multiband_masked:ee.Terrain.products(masked),
 hillshade_smoothed_convolved:ee.Terrain.hillshade(convolved),
 slope_observations:collection.map(image=>ee.Terrain.slope(image.select('elevation'))),
 mean_slope:collection.map(image=>ee.Terrain.slope(image.select('elevation'))).mean(),
 clip_before_products:ee.Terrain.products(elevation.clip(roi)),
 products_clip_after:products.clip(roi),
 source_neighborhood_bands:elevation.neighborhoodToBands(offsets),
 slope_neighborhood_bands:neighborhoodSlope,
 terrain_context_statistics:slope.addBands(neighborhoodSlope)
   .reduceNeighborhood(reducer,ee.Kernel.square({radius:1})),
 deprecated_products_alias:ee.Algorithms.Terrain(elevation)
};
console.log(JSON.stringify({attempts,outputs:Object.fromEntries(
 Object.entries(outputs).map(([name,value])=>[name,ee.Serializer.encode(value)]))}));
"""
    completed = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True,
        text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["attempts"] == 0
    return result["outputs"]


def _nodes(compiled, process_id):
    return [node for node in compiled["process_graph"].values()
            if node["process_id"] == process_id]


def _terrain_specs(compiled):
    return [decode_terrain_spec(node["arguments"]["spec"])
            for node in _nodes(compiled, "local_ee_terrain")]


def _ids(compiled):
    return [node["process_id"] for node in compiled["process_graph"].values()]


def _depends_on(graph, node_id, ancestor_id):
    pending = [node_id]
    seen = set()
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


def _nested_process_ids(value):
    if isinstance(value, dict):
        if isinstance(value.get("process_id"), str):
            yield value["process_id"]
        for child in value.values():
            yield from _nested_process_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nested_process_ids(child)


def test_python_javascript_and_compiler_agree_for_eighteen_workflows():
    expected, _, _, items = python_results()
    actual = _javascript_expressions()
    metadata, _ = catalog()
    assert set(actual) == OUTPUT_NAMES == set(expected)
    for name, expression in actual.items():
        assert compile_expression(expression, metadata, items) == expected[name], name
    assert expected["slope_observations"]["source_item_ids"] == ["scene-a", "scene-b"]
    assert expected["slope_observations"]["has_time_dimension"] is True
    assert expected["mean_slope"]["source_item_ids"] == ["scene-a", "scene-b"]
    assert expected["mean_slope"]["has_time_dimension"] is False
    assert all(item["properties"]["proj:code"] == "EPSG:32649"
               and item["properties"]["proj:transform"] == [
                   10, 0, 220000, 0, -10, 3420000,
               ] for item in items[COLLECTION_ID])


def test_products_keep_input_bands_properties_masks_and_named_selection():
    results, _, _, _ = python_results()
    assert results["products_single_band"]["bands"] == [
        "elevation", "slope", "aspect", "hillshade",
    ]
    assert results["products_multiband"]["bands"] == [
        "elevation", "quality", "slope", "aspect", "hillshade",
    ]
    assert results["products_multiband"]["properties"]["workflow"] == "synthetic-terrain"
    assert results["new_products_only"]["bands"] == ["slope", "aspect", "hillshade"]
    masked_ids = _ids(results["products_multiband_masked"])
    assert "gt" in set(_nested_process_ids(results["products_multiband_masked"]["process_graph"]))
    assert "reduce_dimension" in masked_ids
    assert results["products_multiband_masked"]["bands"] == [
        "elevation", "quality", "slope", "aspect", "hillshade",
    ]
    assert [spec["operation"] for spec in _terrain_specs(results["products_multiband"])] == [
        "slope", "aspect", "hillshade",
    ]


def test_terrain_defaults_periodic_angles_and_clip_export_order_are_explicit():
    results, export, metadata, items = python_results()
    default = _terrain_specs(results["hillshade_default"])
    explicit = _terrain_specs(results["hillshade_explicit_defaults"])
    periodic = _terrain_specs(results["hillshade_periodic_angles"])
    assert default == explicit == [{
        "operation": "hillshade", "v": 1,
        "azimuth": struct.pack(">d", 270.0).hex(),
        "elevation": struct.pack(">d", 45.0).hex(),
    }]
    assert periodic == [{
        "operation": "hillshade", "v": 1,
        "azimuth": struct.pack(">d", 270.0).hex(),
        "elevation": struct.pack(">d", 60.0).hex(),
    }]
    before = _ids(results["clip_before_products"])
    after = _ids(results["products_clip_after"])
    assert before.index("mask_polygon") < before.index("local_ee_to_double")
    assert before.index("local_ee_to_double") < before.index("local_ee_terrain")
    graph = results["products_clip_after"]["process_graph"]
    terrain_ids = [key for key, node in graph.items()
                   if node["process_id"] == "local_ee_terrain"]
    clip_ids = [key for key, node in graph.items()
                if node["process_id"] == "mask_polygon"]
    assert any(_depends_on(graph, clip_id, terrain_id)
               for clip_id in clip_ids for terrain_id in terrain_ids)
    before_graph = results["clip_before_products"]["process_graph"]
    before_terrain = [key for key, node in before_graph.items()
                      if node["process_id"] == "local_ee_terrain"]
    before_clip = [key for key, node in before_graph.items()
                   if node["process_id"] == "mask_polygon"]
    assert any(_depends_on(before_graph, terrain_id, clip_id)
               for terrain_id in before_terrain for clip_id in before_clip)

    assert export["scale"] == 10 and export["crs"] == "EPSG:32649"
    assert export["fileFormat"] == "GeoTIFF" and export["maxPixels"] == 100_000
    region_wire = export["region"]
    scope = dict(region_wire["scope"])
    invocation = scope[region_wire["value"]["value"]]
    assert invocation["functionName"] == "GeometryConstructors.Rectangle"
    coordinates = invocation["arguments"]["coordinates"]
    assert scope[coordinates["value"]] == [100.2, 30.2, 100.8, 30.8]
    exported = compile_expression(
        export["expression"], metadata, items,
        options={"region": ROI, "scale": export["scale"], "crs": export["crs"]},
    )
    graph = exported["process_graph"]
    terrain_ids = [key for key, node in graph.items()
                   if node["process_id"] == "local_ee_terrain"]
    resample_ids = [key for key, node in graph.items()
                    if node["process_id"] == "resample_spatial"]
    roi_clips = [key for key, node in graph.items()
                 if node["process_id"] == "mask_polygon"]
    assert any(_depends_on(graph, resample_id, terrain_id)
               for resample_id in resample_ids for terrain_id in terrain_ids)
    assert any(_depends_on(graph, clip_id, resample_id)
               for clip_id in roi_clips for resample_id in resample_ids)


def test_signed_neighborhood_bands_and_terrain_statistics_keep_operation_order():
    results, _, _, _ = python_results()
    assert results["source_neighborhood_bands"]["bands"] == [
        "elevation_0_-1", "elevation_-1_1",
    ]
    assert results["slope_neighborhood_bands"]["bands"] == [
        "slope_0_-1", "slope_-1_1",
    ]
    for key in ("source_neighborhood_bands", "slope_neighborhood_bands"):
        specs = [json.loads(node["arguments"]["spec"])
                 for node in _nodes(results[key], "local_ee_focal")]
        assert [spec["offsets"] for spec in specs] == [[[0, -1]], [[-1, 1]]]
        assert all(spec["skip_masked"] is False for spec in specs)
    combined = results["terrain_context_statistics"]
    assert combined["bands"] == [
        "slope_mean", "slope_stdDev", "slope_0_-1_mean",
        "slope_0_-1_stdDev", "slope_-1_1_mean", "slope_-1_1_stdDev",
    ]
    graph = combined["process_graph"]
    terrain_ids = [key for key, node in graph.items()
                   if node["process_id"] == "local_ee_terrain"]
    focal = {key: node for key, node in graph.items()
             if node["process_id"] == "local_ee_focal"}
    neighborhood = {key: node for key, node in graph.items()
                    if node["process_id"] == "local_ee_neighborhood"}
    assert terrain_ids and focal and neighborhood
    assert any(_depends_on(graph, key, terrain_id)
               for key in focal for terrain_id in terrain_ids)
    assert any(_depends_on(graph, key, focal_id)
               for key in neighborhood for focal_id in focal)
    focal_specs = [json.loads(node["arguments"]["spec"])
                   for node in _nodes(combined, "local_ee_focal")]
    assert any(spec["skip_masked"] is False and len(spec["offsets"]) == 1
               for spec in focal_specs)


def _dry_run(compiled):
    """Evaluate only metadata adapters; no source pixels are supplied."""
    values, tracer = {}, None
    for name, node in compiled["process_graph"].items():
        process, arguments = node["process_id"], dict(node["arguments"])
        if process == "load_collection":
            cube, _, tracer = _dry_cube(
                tracer=tracer, bands=arguments["bands"], temporal=True,
                source_id=arguments["id"],
            )
            cube = cube.filter_bbox(**arguments["spatial_extent"])
            cube = cube.filter_bands(arguments["bands"])
            result = cube
        else:
            for key, value in tuple(arguments.items()):
                if isinstance(value, dict) and set(value) == {"from_node"}:
                    arguments[key] = values[value["from_node"]]
            if process in {"local_ee_terrain", "local_ee_focal",
                           "local_ee_neighborhood", "local_ee_drop_single_time"}:
                result = getattr(adapters, process)(arguments, None)
            elif process == "local_ee_to_double":
                result = arguments["data"]
            else:
                data = arguments.pop("data")
                if process == "mask_polygon":
                    result = data.mask_polygon(shape(arguments["mask"]))
                elif process == "merge_cubes":
                    other = arguments.pop("cube2")
                    arguments.pop("cube1", None)
                    result = data.merge_cubes(other, arguments.pop("overlap_resolver", None),
                                              **arguments)
                else:
                    result = getattr(data, process)(**arguments)
        values[name] = result
    return result, tracer


def test_compiled_slope_uses_pinned_dryrun_metadata_and_preserves_source_constraints():
    results, _, _, _ = python_results()
    result, tracer = _dry_run(results["slope_observations"])
    assert result.metadata.band_names == ["v"]
    assert result.metadata.has_temporal_dimension() is True
    constraints = tracer.get_source_constraints()
    assert len(constraints) == 1
    _, source = constraints[0]
    assert source["bands"] == ["elevation"]
    assert source["spatial_extent"] == {
        "west": 100, "south": 30, "east": 101, "north": 31,
        "crs": "EPSG:4326",
    }
    assert "resample" not in source and "weak_spatial_extent" not in source


def test_deprecated_alias_serializes_and_compiles_as_products():
    results, _, _, _ = python_results()
    alias = results["deprecated_products_alias"]
    assert alias["bands"] == ["elevation", "slope", "aspect", "hillshade"]
    assert [spec["operation"] for spec in _terrain_specs(alias)] == [
        "slope", "aspect", "hillshade",
    ]
    assert any("deprecated alias" in warning for warning in alias["warnings"])
