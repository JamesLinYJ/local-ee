"""Pinned SDK serialization and bounded Image.convolve compiler checks."""
from copy import deepcopy
from pathlib import Path
import struct

import pytest

from gee.convolve_spec import decode_convolve_spec
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
EXPORT_REGION = {"type": "Polygon", "coordinates": [[
    [100.3, 30.3], [100.7, 30.3], [100.7, 30.7],
    [100.3, 30.3],
]]}


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield guard
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_sdk(ee, value, *, items=None, options=None):
    metadata, default_items, _ = synthetic_inputs()
    return compile_expression(
        encode(ee, value), [metadata],
        default_items if items is None else items, options=options,
    )


def convolve_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_convolve"]


def spec_for(node):
    return decode_convolve_spec(node["arguments"]["spec"])


def f64(value):
    return struct.pack(">d", value).hex()


def test_official_sdk_serializes_asymmetric_focus_and_signed_fixed_weights(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    kernel = ee.Kernel.fixed(
        width=3, height=2,
        weights=[[0, -2, 0], [1, 0.5, 0]], x=1, y=0,
    )
    result = compile_sdk(ee, image.convolve(kernel))

    assert result["kind"] == "image"
    assert result["bands"] == ["nir"]
    nodes = convolve_nodes(result)
    assert len(nodes) == 1
    assert spec_for(nodes[0]) == {
        "v": 1,
        "coefficients": [
            [0, 0, f64(-2.0)],
            [-1, 1, f64(1.0)],
            [0, 1, f64(0.5)],
        ],
    }
    assert nodes[0]["process_id"] == "local_ee_convolve"


def test_convolve_strips_zero_weights_and_encodes_an_all_zero_kernel(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    sparse = ee.Kernel.fixed(
        width=3, height=3,
        weights=[[0, 0, 0], [0, -3, 0], [0, 2, 0]], x=1, y=1,
    )
    sparse_result = compile_sdk(ee, image.convolve(sparse))
    assert spec_for(convolve_nodes(sparse_result)[0])["coefficients"] == [
        [0, 0, f64(-3.0)], [0, 1, f64(2.0)],
    ]

    zero = ee.Kernel.fixed(width=2, height=2, weights=[[0, -0.0], [0, 0]], x=1, y=0)
    zero_result = compile_sdk(ee, image.convolve(zero))
    assert spec_for(convolve_nodes(zero_result)[0])["coefficients"] == [
        [0, 0, "0000000000000000"],
    ]


def test_convolve_accepts_maximum_kernel_dimensions_and_offset_boundaries(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    weights = [[0] * 33 for _ in range(33)]
    weights[0][32] = 1
    weights[32][0] = -1
    kernel = ee.Kernel.fixed(width=33, height=33, weights=weights, x=0, y=32)
    result = compile_sdk(ee, image.convolve(kernel))

    assert spec_for(convolve_nodes(result)[0])["coefficients"] == [
        [32, -32, f64(1.0)], [0, 0, f64(-1.0)],
    ]


def test_each_input_band_gets_its_own_native_output_and_keeps_metadata(ee):
    kernel = ee.Kernel.fixed(width=1, height=1, weights=[[-2]], x=0, y=0)
    image = (ee.ImageCollection("sentinel-2-l2a").first()
             .select(["red", "nir"]).set("local-tag", "preserved"))
    result = compile_sdk(ee, image.convolve(kernel))

    assert result["bands"] == ["red", "nir"]
    assert result["properties"]["local-tag"] == "preserved"
    assert len(convolve_nodes(result)) == 2
    assert [spec_for(node)["coefficients"] for node in convolve_nodes(result)] == [
        [[0, 0, f64(-2.0)]], [[0, 0, f64(-2.0)]],
    ]


def test_mixed_plain_and_convolved_bands_keep_order_and_plan_full_source_bbox(ee):
    kernel = ee.Kernel.fixed(width=3, height=1, weights=[[1, 0, -1]], x=1, y=0)
    source = ee.ImageCollection("sentinel-2-l2a").first()
    image = source.select("red").addBands(
        srcImg=source.select("nir").convolve(kernel),
    )
    result = compile_sdk(ee, image, options={"region": EXPORT_REGION})
    nodes = list(result["process_graph"].values())
    load = next(node for node in nodes if node["process_id"] == "load_collection")

    assert result["bands"] == ["red", "nir"]
    assert len(convolve_nodes(result)) == 1
    assert load["arguments"]["spatial_extent"] == {
        "west": 100, "south": 30, "east": 101, "north": 31,
    }


def test_full_source_bbox_clip_convolve_resample_and_export_region_order(ee):
    kernel = ee.Kernel.fixed(width=3, height=1, weights=[[1, 0, -1]], x=1, y=0)
    clip = ee.Geometry.Rectangle([100.1, 30.1, 100.9, 30.9])
    image = (ee.ImageCollection("sentinel-2-l2a").first()
             .select("nir").clip(clip).convolve(kernel))
    with pytest.raises(UnsupportedEEError, match="Fractional image masks require a mask-aware consumer"):
        compile_sdk(ee, image, options={"region": EXPORT_REGION, "scale": 40})
    planar_clip = ee.Geometry.Rectangle([100.1, 30.1, 100.9, 30.9], geodesic=False)
    image = (ee.ImageCollection("sentinel-2-l2a").first()
             .select("nir").clip(planar_clip).convolve(kernel))
    result = compile_sdk(ee, image, options={"region": EXPORT_REGION, "scale": 40})
    graph = result["process_graph"]
    nodes = list(graph.values())
    process_ids = [node["process_id"] for node in nodes]

    source = next(node for node in nodes if node["process_id"] == "load_collection")
    assert source["arguments"]["spatial_extent"] == {
        "west": 100, "south": 30, "east": 101, "north": 31,
    }
    convolution = process_ids.index("local_ee_convolve")
    resample = process_ids.index("resample_spatial")
    polygon_masks = [index for index, process in enumerate(process_ids)
                     if process == "mask_polygon"]
    assert polygon_masks[0] < convolution < resample < polygon_masks[-1]


def test_mapped_convolution_keeps_time_dimension(ee):
    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    kernel = ee.Kernel.fixed(width=1, height=1, weights=[[1]], x=0, y=0)
    collection = ee.ImageCollection("sentinel-2-l2a").map(
        lambda image: image.select("nir").convolve(kernel),
    )
    result = compile_expression(
        encode(ee, collection), [metadata], items,
    )

    assert result["kind"] == "collection"
    assert result["has_time_dimension"] is True
    assert result["bands"] == ["nir"]
    assert len(convolve_nodes(result)) == 1
    assert "add_dimension" not in [
        node["process_id"] for node in result["process_graph"].values()
    ]


def test_convolve_rejects_unbound_constants_raster_arrays_and_extra_wire_parameters(ee):
    kernel = ee.Kernel.fixed(width=1, height=1, weights=[[1]], x=0, y=0)
    with pytest.raises(UnsupportedEEError, match="finite bound raster source"):
        compile_sdk(ee, ee.Image.constant(5).convolve(kernel))

    array_image = ee.ImageCollection("sentinel-2-l2a").first().select("nir").toArray()
    with pytest.raises(UnsupportedEEError, match="scalar Image"):
        compile_sdk(ee, array_image.convolve(kernel))

    expression = deepcopy(encode(
        ee, ee.ImageCollection("sentinel-2-l2a").first().select("nir").convolve(kernel),
    ))
    invocation = next(
        node for _, node in reversed(expression["scope"])
        if isinstance(node, dict) and node.get("functionName") == "Image.convolve"
    )
    invocation["arguments"]["unexpected"] = 1
    metadata, items, _ = synthetic_inputs()
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(expression, [metadata], items)


def test_convolve_proves_common_grid_for_combined_source_pixels(ee):
    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    second = deepcopy(items["sentinel-2-l2a"][1])
    second["properties"]["system:index"] = "scene-b"
    second["properties"]["proj:transform"][2] += 5
    left = ee.ImageCollection("sentinel-2-l2a").filter(
        ee.Filter.eq(name="system:index", value="scene-a"),
    ).first().select("nir")
    right = ee.ImageCollection("sentinel-2-l2a").filter(
        ee.Filter.eq(name="system:index", value="scene-b"),
    ).first().select("nir")
    kernel = ee.Kernel.fixed(width=1, height=1, weights=[[1]], x=0, y=0)

    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        compile_expression(
            encode(ee, left.add(image2=right).convolve(kernel)),
            [metadata], {"sentinel-2-l2a": [items["sentinel-2-l2a"][0], second]},
        )


def test_large_convolution_kernels_cannot_exceed_shared_work_budget(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    weights = [[1.0] * 33 for _ in range(33)]
    kernel = ee.Kernel.fixed(width=33, height=33, weights=weights, x=16, y=16)
    for _ in range(8):
        image = image.convolve(kernel)

    with pytest.raises(UnsupportedEEError, match="50000|compilation limits"):
        compile_sdk(ee, image)
