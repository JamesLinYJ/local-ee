"""Official-client composed convolution graphs and real dry-run propagation."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from shapely.geometry import shape

from ee_random_split_parity import JAVASCRIPT
from ee_sampling_bridge_helpers import _dry_cube
from engine import ee_process_adapters as adapters
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs

ROOT = Path(__file__).resolve().parents[1]
REGION = {"type": "Polygon", "coordinates": [[
    [100.2, 30.2], [100.8, 30.2], [100.5, 30.8], [100.2, 30.2],
]]}


def catalog():
    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"].update({"proj:code": "EPSG:32649",
                                   "proj:transform": [10, 0, 0, 0, -10, 100]})
    return metadata, items


def python_results(options=None):
    spec = importlib.util.spec_from_file_location(
        "convolution_example", ROOT / "examples/48_GEE_python_convolution.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    metadata, items = catalog()
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48)
        outputs = module.build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))
        results = {key: compile_expression(ee.serializer.encode(value, for_cloud_api=False),
                                          [metadata], items, options=options)
                   for key, value in outputs.items()}
    assert guard.evidence()["attempt_count"] == 0
    return results


def driver_metadata(nodes):
    values = {}
    tracer = None
    for key, node in nodes.items():
        process, arguments = node["process_id"], dict(node["arguments"])
        if process == "load_collection":
            result, _, tracer = _dry_cube(tracer=tracer, bands=arguments["bands"], temporal=True)
            result = result.filter_bbox(**arguments["spatial_extent"]).filter_bands(arguments["bands"])
        else:
            for name in ("data", "cube1", "cube2"):
                if name in arguments:
                    arguments[name] = values[arguments[name]["from_node"]]
            if process in {"local_ee_convolve", "local_ee_focal", "local_ee_drop_single_time"}:
                result = getattr(adapters, process)(arguments, None)
            elif process == "local_ee_to_double":
                result = arguments["data"]  # Cast metadata only; native probe checks actual values.
            elif process == "merge_cubes":
                first, second = arguments.pop("cube1"), arguments.pop("cube2")
                result = first.merge_cubes(second, arguments.pop("overlap_resolver", None), **arguments)
            else:
                data = arguments.pop("data")
                if process == "mask_polygon":
                    result = data.mask_polygon(shape(arguments["mask"]))
                else:
                    result = getattr(data, process)(**arguments)
        values[key] = result
    return result, tracer.get_source_constraints()


def test_composed_workflows_preserve_native_grid_and_dimensions():
    results = python_results({"region": REGION, "scale": 40, "crs": "EPSG:32649"})
    assert len(results) == 15
    for key, compiled in results.items():
        validate(compiled["process_graph"])
        result, constraints = driver_metadata(compiled["process_graph"])
        # Pinned dry-run rename_labels is a no-op and merge retains the first
        # cube's metadata. Check actual native one-band output here; compiler
        # tests verify logical output names/order separately.
        assert result.metadata.band_names == ["v"], key
        assert result.metadata.has_temporal_dimension() == (key == "observations")
        for _, params in constraints:
            extent = params["spatial_extent"]
            assert (extent["west"], extent["south"], extent["east"], extent["north"]) == (100, 30, 101, 31)
            assert "resample" not in params and "weak_spatial_extent" not in params


def test_official_python_and_javascript_share_fifteen_convolution_workflows():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for official SDK serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const collection=ee.ImageCollection('sentinel-2-l2a');
const image=collection.first().select('nir');
const gaussian=ee.Kernel.gaussian({radius:1,sigma:1});
const sobel=ee.Kernel.sobel();
const smooth=image.convolve(gaussian);
const outputs={
 boxcar:image.convolve(ee.Kernel.square(1)),gaussian:smooth,
 laplacian4:image.convolve(ee.Kernel.laplacian4()),
 laplacian8:image.convolve(ee.Kernel.laplacian8()),
 sobel_x:image.convolve(sobel),sobel_y:image.convolve(sobel.rotate(1)),
 prewitt:image.convolve(ee.Kernel.prewitt()),roberts:image.convolve(ee.Kernel.roberts()),
 sharpen:image.convolve(ee.Kernel.fixed(1,1,[[1]]).add(ee.Kernel.laplacian8(-1))),
 directional:image.convolve(ee.Kernel.fixed(3,1,[[-1,0,1]],0,0)),
 zero:image.convolve(ee.Kernel.fixed(1,1,[[0]])),
 smooth_edges:smooth.convolve(ee.Kernel.laplacian4()),morphology:smooth.focalMax(1),
 observations:collection.map(item=>item.select('nir').convolve(gaussian)),
 multiband:collection.first().select(['nir','red']).convolve(gaussian)
};
console.log(JSON.stringify({attempts,outputs:Object.fromEntries(
 Object.entries(outputs).map(([k,v])=>[k,ee.Serializer.encode(v)]))}));
"""
    result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    metadata, items = catalog()
    expected = python_results()
    assert set(decoded["outputs"]) == set(expected)
    for key, value in decoded["outputs"].items():
        assert compile_expression(value, [metadata], items) == expected[key], key
