"""Pinned SDK and compiler contracts for Image.neighborhoodToBands."""
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError
from gee.compat.earthengine.kernel_values import KernelSpec
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.focal_spec import decode_focal_spec
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
EXPORT_REGION = {"type": "Polygon", "coordinates": [[
    [100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
    [100.2, 30.8], [100.2, 30.2],
]]}


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield guard
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture(scope="module")
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def compile_sdk(ee, value, *, items=None, options=None):
    metadata, default_items, _ = synthetic_inputs()
    encoded = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(
        encoded, [metadata], default_items if items is None else items,
        options=options,
    )


def focal_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_focal"]


def decoded_specs(result):
    return [decode_focal_spec(node["arguments"]["spec"])
            for node in focal_nodes(result)]


def test_pinned_sdk_compiles_signed_asymmetric_kernel_row_major_per_input_band(ee):
    image = (ee.ImageCollection("sentinel-2-l2a").first()
             .select(["red", "nir"]).set("local-tag", "kept"))
    kernel = ee.Kernel.fixed(
        width=3, height=2,
        weights=[[-2, 0, 0], [0, 3, -4]], x=1, y=1,
        normalize=False,
    )

    result = compile_sdk(ee, image.neighborhoodToBands(kernel))

    offsets = [[-1, -1], [0, 0], [1, 0]]
    expected_bands = [
        f"{band}_{dx}_{dy}"
        for band in ("red", "nir")
        for dx, dy in offsets
    ]
    assert result["kind"] == "image"
    assert result["bands"] == expected_bands
    assert result["properties"]["local-tag"] == "kept"
    assert len(decoded_specs(result)) == len(expected_bands)
    assert decoded_specs(result) == [
        {
            "v": 1, "operation": "mean", "offsets": [offset],
            "iterations": 1, "skip_masked": False,
        }
        for _band in ("red", "nir")
        for offset in offsets
    ]


def test_kernel_magnitudes_are_ignored_but_negative_nonzero_cells_are_kept(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    kernels = [
        ee.Kernel.fixed(
            width=3, height=2, weights=[[-1, 0, 0], [0, 2, 0]],
            x=1, y=0, normalize=False,
        ),
        ee.Kernel.fixed(
            width=3, height=2, weights=[[-999, 0, 0], [0, 0.25, 0]],
            x=1, y=0, normalize=False,
        ),
    ]
    results = [compile_sdk(ee, image.neighborhoodToBands(kernel))
               for kernel in kernels]

    assert [result["bands"] for result in results] == [
        ["nir_-1_0", "nir_0_1"],
        ["nir_-1_0", "nir_0_1"],
    ]
    assert decoded_specs(results[0]) == decoded_specs(results[1])


def test_zero_kernel_and_source_free_inputs_reject_explicitly(ee):
    zero_kernel = ee.Kernel.fixed(
        width=2, height=2, weights=[[0, 0], [0, 0]],
        x=0, y=0, normalize=False,
    )
    source = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    with pytest.raises(UnsupportedEEError, match="at least one nonzero cell"):
        compile_sdk(ee, source.neighborhoodToBands(zero_kernel))

    one_cell = ee.Kernel.fixed(
        width=1, height=1, weights=[[1]], x=0, y=0, normalize=False,
    )
    with pytest.raises(UnsupportedEEError, match="finite bound raster sources"):
        compile_sdk(ee, ee.Image.constant(5).neighborhoodToBands(one_cell))


def test_array_images_reject_and_output_names_cannot_collide(ee):
    kernel = ee.Kernel.fixed(
        width=1, height=1, weights=[[1]], x=0, y=0, normalize=False,
    )
    array_image = (ee.ImageCollection("sentinel-2-l2a").first()
                   .select("nir").toArray())
    with pytest.raises(UnsupportedEEError, match="nonempty scalar Image"):
        compile_sdk(ee, array_image.neighborhoodToBands(kernel))

    source = Source("sentinel-2-l2a", ("scene-a",), ("red",))
    pixel = Pixel("band", (source, "red"))
    duplicate_names = Image([("duplicate", pixel), ("duplicate", pixel)], {})
    from gee.compat.earthengine.neighborhood_bands import (
        invoke_image_neighborhood_bands,
    )

    with pytest.raises(UnsupportedEEError, match="output band names would collide"):
        invoke_image_neighborhood_bands(
            Translator([], {}, None),
            {"image": duplicate_names, "kernel": KernelSpec(((1.0,),), 0, 0)},
        )


def test_direct_output_owns_band_list_and_preserves_pixel_and_properties():
    source = Source("sentinel-2-l2a", ("scene-a",), ("red",))
    pixel = Pixel("band", (source, "red"))
    image = Image([("red", pixel)], {"tag": "unchanged"})
    kernel = KernelSpec(((0.0, -2.0), (0.5, 0.0)), 0, 0)
    from gee.compat.earthengine.neighborhood_bands import (
        invoke_image_neighborhood_bands,
    )

    result = invoke_image_neighborhood_bands(
        Translator([], {}, None), {"image": image, "kernel": kernel},
    )

    assert result is not image
    assert result.bands is not image.bands
    assert image.bands == [("red", pixel)]
    assert result.props is image.props
    assert result.props == {"tag": "unchanged"}
    assert [name for name, _ in result.bands] == ["red_1_0", "red_0_1"]
    assert all(node.op == "focal" and node.args[0] is pixel
               for _, node in result.bands)
    assert kernel.weights == ((0.0, -2.0), (0.5, 0.0))


def test_final_graph_work_and_json_budgets_are_enforced(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("red")
    dense = ee.Kernel.fixed(
        width=33, height=33, weights=[[1] * 33 for _ in range(33)],
        x=16, y=16, normalize=False,
    )
    with pytest.raises(UnsupportedEEError, match="shared 50000-step"):
        compile_sdk(ee, image.neighborhoodToBands(dense))

    # Large intermediate IRs may be narrowed by a later band selection. The
    # final Graph budget, rather than an eager expansion estimate, decides it.
    selectable = ee.Kernel.fixed(
        width=15, height=15, weights=[[1] * 15 for _ in range(15)],
        x=7, y=7, normalize=False,
    )
    narrowed = compile_sdk(
        ee, image.neighborhoodToBands(selectable).select("red_0_0"),
    )
    assert narrowed["bands"] == ["red_0_0"]

    from gee.compat.earthengine.neighborhood_bands import (
        invoke_image_neighborhood_bands,
    )

    source = Source("sentinel-2-l2a", ("scene-a",), ("red",))
    pixel = Pixel("band", (source, "red"))
    large_name = "n" * 260_000
    huge_image = Image([(large_name, pixel)], {})
    two_cells = KernelSpec(((1.0, 1.0),), 0, 0)
    with pytest.raises(UnsupportedEEError, match="shared 50000-step"):
        invoke_image_neighborhood_bands(
            Translator([], {}, None),
            {"image": huge_image, "kernel": two_cells},
        )

    # Escaped Unicode names can dominate public JSON even with only four
    # outputs; the wire estimate must reject them before output allocation.
    unicode_name = "é" * 24_950
    unicode_image = Image([(unicode_name, pixel)], {})
    four_cells = KernelSpec(((1.0, 1.0, 1.0, 1.0),), 0, 0)
    with pytest.raises(UnsupportedEEError, match="output exceeds 1 MB"):
        invoke_image_neighborhood_bands(
            Translator([], {}, None),
            {"image": unicode_image, "kernel": four_cells},
        )


def test_graph_node_limit_applies_to_large_neighborhood_expansion():
    names = tuple(chr(0xE000 + index) for index in range(160))
    source = Source("local", ("scene-a",), names)
    image = Image(
        [(name, Pixel("band", (source, name))) for name in names], {},
    )
    translator = Translator([], {"local": [{
        "id": "scene-a", "bbox": [0, 0, 1, 1],
    }]}, None)
    from gee.compat.earthengine.neighborhood_bands import (
        invoke_image_neighborhood_bands,
    )
    expanded = invoke_image_neighborhood_bands(
        translator,
        {"image": image, "kernel": KernelSpec(((1.0,),), 0, 0)},
    )
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        Graph(translator).image(expanded)


def test_neighborhood_chain_keeps_focal_and_convolve_source_branches(ee):
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    kernel = ee.Kernel.fixed(
        width=2, height=1, weights=[[-2, 0.5]], x=0, y=0,
        normalize=False,
    )
    focal_result = compile_sdk(
        ee, image.focalMean(radius=0).neighborhoodToBands(kernel),
    )
    convolve_result = compile_sdk(
        ee, image.convolve(kernel).neighborhoodToBands(kernel),
    )

    assert focal_result["bands"] == convolve_result["bands"] == [
        "nir_0_0", "nir_1_0",
    ]
    assert len(focal_nodes(focal_result)) == 3
    assert len(focal_nodes(convolve_result)) == 2
    assert any(node["process_id"] == "local_ee_convolve"
               for node in convolve_result["process_graph"].values())


def test_mapped_time_and_roi_keep_full_source_bounds_and_mask_after_neighborhood(ee):
    _, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    collection = ee.ImageCollection("sentinel-2-l2a").map(
        lambda image: image.select("red").neighborhoodToBands(
            ee.Kernel.fixed(
                width=2, height=1, weights=[[1, 1]], x=0, y=0,
                normalize=False,
            ),
        ),
    )

    result = compile_sdk(
        ee, collection, items=items,
        options={"region": EXPORT_REGION, "scale": 20, "crs": "EPSG:32610"},
    )

    assert result["kind"] == "collection"
    assert result["bands"] == ["red_0_0", "red_1_0"]
    assert result["source_item_ids"] == ["scene-a", "scene-b", "scene-c"]
    assert result["has_time_dimension"] is True
    graph = result["process_graph"]
    load = next(node for node in graph.values()
                if node["process_id"] == "load_collection")
    assert load["arguments"]["spatial_extent"] == {
        "west": 100, "south": 30, "east": 101, "north": 31,
    }
    ids = [node["process_id"] for node in graph.values()]
    assert ids.index("local_ee_focal") < ids.index("resample_spatial")
    assert ids.index("resample_spatial") < ids.index("mask_polygon")
