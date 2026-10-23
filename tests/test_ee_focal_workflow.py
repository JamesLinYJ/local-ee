"""Official SDK composition and actual driver metadata/optimizer integration.

These checks execute no Spark job. The separate native probe computes real
tiles; the dry-run here detects source cropping and duplicate band dimensions.
"""
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
        "neighborhood_example", ROOT / "examples/47_GEE_python_neighborhood.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    metadata, items = catalog()
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                               signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        outputs = module.build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))
        results = {key: compile_expression(ee.serializer.encode(value, for_cloud_api=False),
                                          [metadata], items, options=options)
                   for key, value in outputs.items()}
    assert guard.evidence()["attempt_count"] == 0
    return results


def run_driver_metadata(nodes):
    values = {}
    tracer = None
    for key, node in nodes.items():
        process, arguments = node["process_id"], dict(node["arguments"])
        if process == "load_collection":
            result, _, tracer = _dry_cube(tracer=tracer, bands=arguments["bands"], temporal=True)
            result = result.filter_bbox(**arguments["spatial_extent"])
            result = result.filter_bands(arguments["bands"])
        else:
            data = values[arguments.pop("data")["from_node"]]
            if process in {"local_ee_focal", "local_ee_drop_single_time"}:
                result = getattr(adapters, process)({"data": data, **arguments}, None)
            elif process == "local_ee_to_double":
                result = data  # Cast preserves metadata; native values tested separately.
            elif process == "mask_polygon":
                result = data.mask_polygon(shape(arguments["mask"]))
            else:
                result = getattr(data, process)(**arguments)
        values[key] = result
    return result, tracer.get_source_constraints()


def test_twelve_workflows_preserve_dimensions_and_focal_input_extent():
    results = python_results({"region": REGION, "scale": 40, "crs": "EPSG:32649"})
    assert len(results) == 12
    for key, compiled in results.items():
        validate(compiled["process_graph"])
        result, constraints = run_driver_metadata(compiled["process_graph"])
        # Pinned DryRunDataCube.rename_labels is a documented no-op; native
        # band count/schema is checked here, compiled labels by SDK parity.
        assert result.metadata.band_names == ["v"], key
        assert result.metadata.has_temporal_dimension() == (key == "observations")
        for _, params in constraints:
            extent = params["spatial_extent"]
            assert (extent["west"], extent["south"], extent["east"], extent["north"]) == (100, 30, 101, 31)
            assert "resample" not in params and "weak_spatial_extent" not in params


def test_python_and_javascript_share_twelve_neighborhood_workflows():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for pinned JS SDK serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const collection=ee.ImageCollection('sentinel-2-l2a');
const image=collection.first().select('nir');
const square=ee.Kernel.square(1,'pixels',false);
const directional=ee.Kernel.fixed(3,1,[[0,1,1]],1,0);
const outputs={};
for (const operation of ['mean','min','max','median','mode']) {
 outputs[operation]=image['focal'+operation[0].toUpperCase()+operation.slice(1)](1,'square');
}
Object.assign(outputs,{
 opening:image.focalMin({kernel:square,iterations:2}).focalMax({kernel:square,iterations:2}),
 closing:image.focalMax({kernel:square}).focalMin({kernel:square}),
 directional:image.reduceNeighborhood(ee.Reducer.mean(),directional),
 fill:image.reduceNeighborhood({reducer:ee.Reducer.median(),kernel:square,skipMasked:false}),
 majority:image.reduceNeighborhood(ee.Reducer.mode(),square),
 normalized:image.reduceNeighborhood(ee.Reducer.mean(),ee.Kernel.circle(1)),
 observations:collection.map(item=>item.select('nir').focalMean(1))
});
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
    for name, value in decoded["outputs"].items():
        assert compile_expression(value, [metadata], items) == expected[name]


def test_mixed_output_order_cannot_crop_a_shared_source_before_focal():
    metadata, items, _ = synthetic_inputs()
    ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48)
    source = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    image = source.addBands(source.focalMean().rename("smooth"))
    result = compile_expression(ee.serializer.encode(image, for_cloud_api=False),
                                [metadata], items, options={"region": REGION})
    loads = [n for n in result["process_graph"].values() if n["process_id"] == "load_collection"]
    assert len(loads) == 1
    assert loads[0]["arguments"]["spatial_extent"] == {"west": 100, "south": 30, "east": 101, "north": 31}


def test_kernel_values_remain_opaque_at_public_json_and_condition_boundaries():
    from gee.ee_translate import UnsupportedEEError
    ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48)
    kernel = ee.Kernel.square(1)
    for value in (kernel, ee.Algorithms.If(kernel, 1, 0)):
        with pytest.raises(UnsupportedEEError):
            compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})
