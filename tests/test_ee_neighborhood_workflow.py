"""Pinned Python/JavaScript SDK parity for local neighborhood compositions.

Compilation and pinned-driver DryRun assert graph/spec and metadata behavior;
they do not provide pixels or establish Google numerical equivalence.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import shutil
import struct
import subprocess

import pytest
from shapely.geometry import shape

from ee_random_split_parity import JAVASCRIPT
from ee_sampling_bridge_helpers import _dry_cube
from engine import ee_process_adapters as adapters
from gee.convolve_spec import decode_convolve_spec
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.focal_spec import decode_focal_spec
from gee.graph import validate
from gee.neighborhood_spec import decode_neighborhood_spec
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import COLLECTION_ID, synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
REGION = {"type": "Polygon", "coordinates": [[
    [100.2, 30.2], [100.8, 30.2], [100.5, 30.8], [100.2, 30.2],
]]}
OUTPUT_NAMES = {
    "ndvi", "weighted_gaussian", "weighted_sum_median", "weighted_count",
    "unit_product_sample_stats", "min_clipped_mask", "mask_weight_mean",
    "unweighted_mean", "shared_statistics", "collection_texture",
    "multiband_mean", "convolve_texture", "convolve_euclidean",
    "convolve_manhattan", "convolve_chebyshev", "convolve_compass",
    "convolve_kirsch", "convolve_inverse",
}


def catalog():
    metadata, items, _ = synthetic_inputs()
    assert len(items[COLLECTION_ID]) == 3
    for item in items[COLLECTION_ID]:
        millis = item["properties"]["system:time_start"]
        item["properties"]["datetime"] = datetime.fromtimestamp(
            millis / 1000, timezone.utc
        ).isoformat().replace("+00:00", "Z")
        item["properties"].update({
            "proj:code": "EPSG:32649",
            "proj:transform": [10, 0, 500000, 0, -10, 100],
        })
    assert [item["id"] for item in items[COLLECTION_ID]] == [
        "scene-a", "scene-b", "scene-c",
    ]
    assert [item["properties"]["datetime"] for item in items[COLLECTION_ID]] == [
        "2023-11-14T22:13:20Z", "2023-11-15T22:13:20Z", "2023-11-16T22:13:20Z",
    ]
    assert all(
        item["properties"]["proj:code"] == "EPSG:32649"
        and item["properties"]["proj:transform"] == [10, 0, 500000, 0, -10, 100]
        for item in items[COLLECTION_ID]
    )
    return metadata, items


def _example():
    spec = importlib.util.spec_from_file_location(
        "local_texture_example", ROOT / "examples/49_GEE_python_local_texture.py"
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
        outputs = _example().build_workflow(ee, ee.ImageCollection(COLLECTION_ID))
        assert set(outputs) == OUTPUT_NAMES
        results = {
            name: compile_expression(
                ee.serializer.encode(value, for_cloud_api=False),
                [metadata], items, options=options,
            )
            for name, value in outputs.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    for compiled in results.values():
        validate(compiled["process_graph"])
    return results


def _javascript_expressions():
    node = shutil.which("node") or str(
        ROOT / ".native/toolchains/node-v24.22.1-darwin-arm64/bin/node"
    )
    if not Path(node).is_file():
        pytest.skip("Node is required for pinned JavaScript SDK serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const collection=ee.ImageCollection('sentinel-2-l2a');
const source=collection.first().select(['red','nir']);
const ndvi=source.normalizedDifference(['nir','red']).rename('NDVI').toFloat();
const gaussian=ee.Kernel.gaussian({radius:1,sigma:1});
const unit=ee.Kernel.square({radius:1,units:'pixels',normalize:false});
const clipped=ndvi.clip(ee.Geometry.Rectangle([100.2,30.2,100.8,30.8],'EPSG:4326',false));
const weighted=ee.Reducer.sum()
 .combine({reducer2:ee.Reducer.mean(),sharedInputs:true})
 .combine({reducer2:ee.Reducer.variance(),sharedInputs:true})
 .combine({reducer2:ee.Reducer.stdDev(),sharedInputs:true});
const half=ee.Kernel.fixed(3,3,[[0.5,0.5,0.5],[0.5,0.5,0.5],[0.5,0.5,0.5]],1,1);
const sumMedian=ee.Reducer.sum().combine({reducer2:ee.Reducer.median(),sharedInputs:true});
const unitStats=ee.Reducer.product()
 .combine({reducer2:ee.Reducer.sampleVariance(),sharedInputs:true})
 .combine({reducer2:ee.Reducer.sampleStdDev(),sharedInputs:true});
const shared=ee.Reducer.mean()
 .combine({reducer2:ee.Reducer.stdDev(),sharedInputs:true})
 .combine({reducer2:ee.Reducer.minMax(),sharedInputs:true})
 .combine({reducer2:ee.Reducer.count(),sharedInputs:true})
 .setOutputs(['average','spread','low','high','observations']);
const capped=ee.Kernel.gaussian({radius:1,sigma:0.5,normalize:false,magnitude:4});
const inverse=ee.Kernel.gaussian({radius:1,sigma:0.5,normalize:false}).inverse();
const convolved=ndvi.convolve(gaussian);
const outputs={
 ndvi,
 weighted_gaussian:ndvi.reduceNeighborhood({reducer:weighted,kernel:gaussian}),
 weighted_sum_median:ndvi.reduceNeighborhood({reducer:sumMedian,kernel:half}),
 weighted_count:ndvi.reduceNeighborhood({reducer:ee.Reducer.count(),kernel:gaussian}),
 unit_product_sample_stats:ndvi.reduceNeighborhood({reducer:unitStats,kernel:unit}),
 min_clipped_mask:clipped.reduceNeighborhood({reducer:ee.Reducer.min(),kernel:capped,inputWeight:'min'}),
 mask_weight_mean:clipped.reduceNeighborhood({reducer:ee.Reducer.mean(),kernel:gaussian,inputWeight:'mask'}),
 unweighted_mean:ndvi.reduceNeighborhood({reducer:ee.Reducer.mean().unweighted(),kernel:capped}),
 shared_statistics:ndvi.reduceNeighborhood({reducer:shared,kernel:unit}),
 collection_texture:collection.map(image=>image.normalizedDifference(['nir','red']).rename('NDVI').toFloat()
   .reduceNeighborhood({reducer:ee.Reducer.stdDev(),kernel:unit})),
 multiband_mean:source.reduceNeighborhood({reducer:ee.Reducer.mean(),kernel:unit}),
 convolve_texture:convolved.reduceNeighborhood({reducer:ee.Reducer.stdDev(),kernel:unit}),
 convolve_euclidean:ndvi.convolve(ee.Kernel.euclidean({radius:1})),
 convolve_manhattan:ndvi.convolve(ee.Kernel.manhattan({radius:1})),
 convolve_chebyshev:ndvi.convolve(ee.Kernel.chebyshev({radius:1})),
 convolve_compass:ndvi.convolve(ee.Kernel.compass()),
 convolve_kirsch:ndvi.convolve(ee.Kernel.kirsch()),
 convolve_inverse:ndvi.convolve(inverse)
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


def test_official_python_and_javascript_compile_the_same_18_graphs():
    expected = python_results()
    actual = _javascript_expressions()
    metadata, items = catalog()
    assert set(actual) == OUTPUT_NAMES
    assert set(actual) == set(expected)
    for name, expression in actual.items():
        compiled = compile_expression(expression, [metadata], items)
        assert compiled == expected[name], name
    assert expected["collection_texture"]["source_item_ids"] == [
        "scene-a", "scene-b", "scene-c",
    ]
    assert expected["collection_texture"]["has_time_dimension"] is True
    assert expected["convolve_texture"]["source_item_ids"] == ["scene-a"]
    assert expected["convolve_texture"]["has_time_dimension"] is False


def _nodes(compiled, process_id):
    return [node for node in compiled["process_graph"].values()
            if node["process_id"] == process_id]


def _weight_map(spec):
    return {
        (dx, dy): struct.unpack(">d", bytes.fromhex(bits))[0]
        for dx, dy, bits in spec["coefficients"]
    }


def _neighborhood_by_operation(compiled):
    specs = [decode_neighborhood_spec(node["arguments"]["spec"])
             for node in _nodes(compiled, "local_ee_neighborhood")]
    return {spec["operation"]: spec for spec in specs}


def test_compiled_specs_preserve_weights_support_and_output_names():
    results = python_results()
    weighted = _neighborhood_by_operation(results["weighted_gaussian"])
    assert set(weighted) == {"sum", "mean", "variance", "stdDev"}
    gaussian_weights = _weight_map(weighted["sum"])
    assert len(gaussian_weights) == 9 and len(set(gaussian_weights.values())) > 1
    assert sum(gaussian_weights.values()) == pytest.approx(1.0)
    assert all(_weight_map(spec) == gaussian_weights for spec in weighted.values())
    assert results["weighted_gaussian"]["bands"] == [
        "NDVI_sum", "NDVI_mean", "NDVI_variance", "NDVI_stdDev",
    ]

    mixed = _neighborhood_by_operation(results["weighted_sum_median"])
    half_weights = _weight_map(mixed["sum"])
    assert set(half_weights.values()) == {0.5}
    assert _weight_map(mixed["median"]) == {key: 1.0 for key in half_weights}

    count = _neighborhood_by_operation(results["weighted_count"])["count"]
    assert _weight_map(count) == gaussian_weights
    unit_stats = _neighborhood_by_operation(results["unit_product_sample_stats"])
    assert set(unit_stats) == {"product", "sampleVariance", "sampleStdDev"}
    assert all(set(_weight_map(spec).values()) == {1.0} for spec in unit_stats.values())

    minimum = _neighborhood_by_operation(results["min_clipped_mask"])["min"]
    min_weights = _weight_map(minimum)
    assert len(min_weights) == 9 and max(min_weights.values()) == 1.0
    assert sum(weight > 1.0 for weight in min_weights.values()) == 0
    assert len(set(min_weights.values())) > 1

    unweighted_focal, = _nodes(results["unweighted_mean"], "local_ee_focal")
    unweighted_spec = decode_focal_spec(unweighted_focal["arguments"]["spec"])
    assert len(unweighted_spec["offsets"]) == 9
    assert len(_nodes(results["mask_weight_mean"], "local_ee_focal")) == 1
    mask_spec = decode_focal_spec(
        _nodes(results["mask_weight_mean"], "local_ee_focal")[0]["arguments"]["spec"]
    )
    assert len(mask_spec["offsets"]) == 9
    assert results["shared_statistics"]["bands"] == [
        "NDVI_average", "NDVI_spread", "NDVI_low", "NDVI_high",
        "NDVI_observations",
    ]
    assert set(_neighborhood_by_operation(results["shared_statistics"])) == {
        "mean", "stdDev", "min", "max", "count",
    }
    assert results["multiband_mean"]["bands"] == ["red_mean", "nir_mean"]


def test_six_new_kernel_matrices_are_serialized_into_convolve():
    results = python_results()
    expected = {
        "convolve_euclidean": {
            (-1, -1): math.sqrt(2), (0, -1): 1.0, (1, -1): math.sqrt(2),
            (-1, 0): 1.0, (1, 0): 1.0,
            (-1, 1): math.sqrt(2), (0, 1): 1.0, (1, 1): math.sqrt(2),
        },
        "convolve_manhattan": {
            (-1, -1): 2.0, (0, -1): 1.0, (1, -1): 2.0,
            (-1, 0): 1.0, (1, 0): 1.0,
            (-1, 1): 2.0, (0, 1): 1.0, (1, 1): 2.0,
        },
        "convolve_chebyshev": {
            (dx, dy): 1.0 for dy in (-1, 0, 1) for dx in (-1, 0, 1)
            if (dx, dy) != (0, 0)
        },
        "convolve_compass": {
            (dx, dy): weight
            for dy, row in zip((-1, 0, 1), ((1, 1, -1), (1, -2, -1), (1, 1, -1)))
            for dx, weight in zip((-1, 0, 1), row) if weight != 0
        },
        "convolve_kirsch": {
            (dx, dy): weight
            for dy, row in zip((-1, 0, 1), ((5, -3, -3), (5, 0, -3), (5, -3, -3)))
            for dx, weight in zip((-1, 0, 1), row) if weight != 0
        },
    }
    for name, weights in expected.items():
        node, = _nodes(results[name], "local_ee_convolve")
        spec = decode_convolve_spec(node["arguments"]["spec"])
        actual = {(dx, dy): struct.unpack(">d", bytes.fromhex(bits))[0]
                  for dx, dy, bits in spec["coefficients"]}
        assert actual == weights, name

    inverse_node, = _nodes(results["convolve_inverse"], "local_ee_convolve")
    inverse = decode_convolve_spec(inverse_node["arguments"]["spec"])
    inverse_weights = {(dx, dy): struct.unpack(">d", bytes.fromhex(bits))[0]
                       for dx, dy, bits in inverse["coefficients"]}
    assert set(inverse_weights) == {(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    assert inverse_weights[(0, 0)] == pytest.approx(math.pi / 2)
    assert inverse_weights[(1, 0)] > inverse_weights[(0, 0)]
    assert all(math.isfinite(weight) and weight > 0 for weight in inverse_weights.values())


def _dry_run_metadata(nodes):
    values = {}
    tracer = None
    for key, node in nodes.items():
        process, arguments = node["process_id"], dict(node["arguments"])
        if process == "load_collection":
            result, _, tracer = _dry_cube(
                tracer=tracer, bands=arguments["bands"], temporal=True,
            )
            result = result.filter_bbox(**arguments["spatial_extent"])
            result = result.filter_bands(arguments["bands"])
        else:
            for ref in ("data", "cube1", "cube2"):
                value = arguments.get(ref)
                if type(value) is dict and set(value) == {"from_node"}:
                    arguments[ref] = values[value["from_node"]]
            if process in {
                "local_ee_neighborhood", "local_ee_focal", "local_ee_convolve",
                "local_ee_drop_single_time",
            }:
                result = getattr(adapters, process)(arguments, None)
            elif process in {"local_ee_to_double", "local_ee_to_float"}:
                result = arguments["data"]
            elif process == "merge_cubes":
                first, second = arguments.pop("cube1"), arguments.pop("cube2")
                result = first.merge_cubes(
                    second, arguments.pop("overlap_resolver", None), **arguments,
                )
            else:
                data = arguments.pop("data") if "data" in arguments else None
                if process == "mask_polygon":
                    result = data.mask_polygon(shape(arguments["mask"]))
                else:
                    method = getattr(data, process)
                    if "env" in inspect.signature(method).parameters:
                        arguments.setdefault("env", None)
                    result = method(**arguments)
        values[key] = result
    return result, tracer.get_source_constraints()


def test_real_pinned_dry_run_keeps_neighborhood_before_downstream_resampling():
    results = python_results({"region": REGION, "scale": 40, "crs": "EPSG:32649"})
    compiled = results["convolve_texture"]
    process_ids = [node["process_id"] for node in compiled["process_graph"].values()]
    assert process_ids.index("local_ee_convolve") < process_ids.index("local_ee_neighborhood")
    assert process_ids.index("local_ee_neighborhood") < process_ids.index("resample_spatial")
    assert process_ids.index("resample_spatial") < process_ids.index("mask_polygon")
    loads = _nodes(compiled, "load_collection")
    assert loads and all(
        node["arguments"]["spatial_extent"] == {
            "west": 100, "south": 30, "east": 101, "north": 31,
        }
        for node in loads
    )
    assert all(node["arguments"].get("bands") == ["red", "nir"] for node in loads)
    mask_node, = _nodes(compiled, "mask_polygon")
    assert mask_node["arguments"]["mask"] == REGION
    dry_result, constraints = _dry_run_metadata(compiled["process_graph"])
    assert dry_result.metadata.band_names == ["v"]
    assert not dry_result.metadata.has_temporal_dimension()
    assert constraints
    for _, parameters in constraints:
        extent = parameters["spatial_extent"]
        assert (extent["west"], extent["south"], extent["east"], extent["north"]) == (
            100, 30, 101, 31,
        )
        assert parameters["bands"] == ["red", "nir"]
        assert "resample" not in parameters and "weak_spatial_extent" not in parameters


def test_nonuniform_weighted_median_and_unsupported_options_fail_closed():
    from gee.ee_translate import UnsupportedEEError

    ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48)
    image = ee.ImageCollection(COLLECTION_ID).first().select("nir")
    gaussian = ee.Kernel.gaussian(radius=1, sigma=1)
    invalid = (
        image.reduceNeighborhood(
            ee.Reducer.sum().combine(
                reducer2=ee.Reducer.median(), sharedInputs=True,
            ), gaussian,
        ),
        image.reduceNeighborhood(
            ee.Reducer.mean(), ee.Kernel.square(radius=1, units="meters"),
        ),
        image.reduceNeighborhood(
            ee.Reducer.mean(), gaussian, optimization="boxcar",
        ),
    )
    metadata, items = catalog()
    for value in invalid:
        with pytest.raises(UnsupportedEEError):
            compile_expression(
                ee.serializer.encode(value, for_cloud_api=False), [metadata], items,
            )
