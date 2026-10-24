"""Pinned SDK serialization and bounded Image.distance compiler checks."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import struct

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.image_distance import invoke_image_distance
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError
from gee.compat.earthengine.kernel_values import KernelSpec, invoke_kernel
from gee.distance_spec import decode_distance_spec, prepare_distance_spec
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
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


def distance_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_distance"]


def distance_specs(result):
    return [decode_distance_spec(node["arguments"]["spec"])
            for node in distance_nodes(result)]


def radius_hex(value):
    return struct.pack(">d", 0.0 if value == 0 else float(value)).hex()


def source(ee):
    return ee.ImageCollection("sentinel-2-l2a").first()


@pytest.mark.parametrize("metric", ["euclidean", "manhattan", "chebyshev"])
def test_raw_distance_kernels_lower_their_actual_metric_and_radius(ee, metric):
    image = source(ee).select("nir")
    kernel = getattr(ee.Kernel, metric)(1.5)
    result = compile_sdk(ee, image.distance(kernel=kernel))

    assert result["kind"] == "image"
    assert result["bands"] == ["nir"]
    assert distance_specs(result) == [{
        "metric": metric, "radius": radius_hex(1.5),
        "skip_masked": True, "v": 1,
    }]
    assert distance_nodes(result)[0]["arguments"]["data"]
    processes = [node["process_id"] for node in result["process_graph"].values()]
    assert processes.index("local_ee_to_double") < processes.index("local_ee_distance")


def test_zero_radius_and_fractional_radius_are_preserved_without_kernel_extent_leak(ee):
    image = source(ee).select("nir")
    zero = compile_sdk(
        ee, image.distance(kernel=ee.Kernel.euclidean(0)),
    )
    fractional = compile_sdk(
        ee, image.distance(kernel=ee.Kernel.euclidean(0.5)),
    )

    assert distance_specs(zero)[0]["radius"] == radius_hex(0)
    assert distance_specs(fractional)[0]["radius"] == radius_hex(0.5)
    assert len(distance_nodes(zero)) == len(distance_nodes(fractional)) == 1


def test_each_band_properties_and_following_mask_chain_are_preserved(ee):
    image = source(ee).select(["red", "nir"]).set("local-tag", "retained")
    kernel = ee.Kernel.manhattan(2)
    result = compile_sdk(
        ee, image.distance(kernel=kernel, skipMasked=False)
        .updateMask(image.select("red").gt(0)),
    )

    assert result["bands"] == ["red", "nir"]
    assert result["properties"]["local-tag"] == "retained"
    assert len(distance_nodes(result)) == 2
    assert {spec["skip_masked"] for spec in distance_specs(result)} == {False}
    assert any(node["process_id"] == "mask" for node in result["process_graph"].values())


def test_distance_preserves_mapped_time_and_full_input_bounds_before_output_roi(ee):
    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    kernel = ee.Kernel.chebyshev(1)
    collection = ee.ImageCollection("sentinel-2-l2a").map(
        lambda image: image.select("nir").distance(kernel=kernel),
    )
    mapped = compile_expression(encode(ee, collection), [metadata], items)

    assert mapped["kind"] == "collection"
    assert mapped["has_time_dimension"] is True
    assert mapped["bands"] == ["nir"]
    assert len(distance_nodes(mapped)) == 1

    clipped = (source(ee).select("nir")
               .clip(ee.Geometry.Rectangle([100.1, 30.1, 100.9, 30.9]))
               .distance(kernel=kernel))
    with pytest.raises(UnsupportedEEError, match="Fractional image masks require a mask-aware consumer"):
        compile_sdk(ee, clipped, options={"region": EXPORT_REGION, "scale": 40})
    clipped = (source(ee).select("nir")
               .clip(ee.Geometry.Rectangle([100.1, 30.1, 100.9, 30.9], geodesic=False))
               .distance(kernel=kernel))
    exported = compile_sdk(
        ee, clipped, options={"region": EXPORT_REGION, "scale": 40},
    )
    nodes = list(exported["process_graph"].values())
    load = next(node for node in nodes if node["process_id"] == "load_collection")
    assert load["arguments"]["spatial_extent"] == {
        "west": 100, "south": 30, "east": 101, "north": 31,
    }
    process_ids = [node["process_id"] for node in nodes]
    assert (process_ids.index("mask_polygon") < process_ids.index("local_ee_distance")
            < process_ids.index("resample_spatial") < len(process_ids) - 1)
    assert process_ids[-1] == "mask_polygon"


def test_sdk_skipmasked_default_and_null_follow_pinned_serialization(ee):
    image = source(ee).select("nir")
    kernel = ee.Kernel.euclidean(1)
    omitted = encode(ee, image.distance(kernel=kernel))
    explicit_null = encode(ee, image.distance(kernel=kernel, skipMasked=None))
    omitted_invocation = next(
        node for _, node in reversed(omitted["scope"])
        if isinstance(node, dict) and node.get("functionName") == "Image.distance"
    )
    null_invocation = next(
        node for _, node in reversed(explicit_null["scope"])
        if isinstance(node, dict) and node.get("functionName") == "Image.distance"
    )
    assert omitted_invocation["arguments"]["skipMasked"] is True
    assert "skipMasked" not in null_invocation["arguments"]
    assert distance_specs(compile_sdk(ee, image.distance(kernel=kernel))) == [{
        "metric": "euclidean", "radius": radius_hex(1),
        "skip_masked": True, "v": 1,
    }]
    assert distance_specs(compile_sdk(
        ee, image.distance(kernel=kernel, skipMasked=None),
    )) == distance_specs(compile_sdk(ee, image.distance(kernel=kernel)))

    expression = deepcopy(omitted)
    invocation = next(
        node for _, node in reversed(expression["scope"])
        if isinstance(node, dict) and node.get("functionName") == "Image.distance"
    )
    invocation["arguments"]["skipMasked"] = None
    metadata, items, _ = synthetic_inputs()
    with pytest.raises(UnsupportedEEError, match="skipMasked must be a boolean"):
        compile_expression(expression, [metadata], items)


def test_missing_null_or_ineligible_kernels_are_rejected(ee):
    image = source(ee).select("nir")
    with pytest.raises(UnsupportedEEError, match="explicit kernel"):
        compile_sdk(ee, image.distance())
    with pytest.raises(UnsupportedEEError, match="explicit kernel"):
        compile_sdk(ee, image.distance(kernel=None))

    candidates = [
        ee.Kernel.fixed(width=3, height=3, weights=[[1] * 3] * 3, x=1, y=1),
        ee.Kernel.euclidean(1, normalize=True),
        ee.Kernel.euclidean(1, magnitude=2),
        ee.Kernel.euclidean(1).inverse(),
        ee.Kernel.euclidean(1).rotate(1),
        ee.Kernel.euclidean(1).rotate(4),
        ee.Kernel.euclidean(1).add(ee.Kernel.euclidean(1)),
    ]
    for kernel in candidates:
        with pytest.raises(UnsupportedEEError, match="raw Euclidean"):
            compile_sdk(ee, image.distance(kernel=kernel))


def test_distance_provenance_rejects_forged_metric_radius_and_weight_metadata():
    translator = Translator([], {}, None)
    raw = invoke_kernel(translator, "Kernel.euclidean", {"radius": 1})
    forged = (
        replace(raw, distance_metric="manhattan"),
        replace(raw, distance_radius=2.0),
        KernelSpec(((0.0, 1.0, 0.0), (1.0, 0.0, 1.0),
                    (0.0, 1.0, 0.0)), 1, 1, "euclidean", 1.0),
    )
    image = Image([("nir", Pixel("constant", (1.0,)))], {})
    for kernel in forged:
        with pytest.raises(UnsupportedEEError, match="provenance"):
            invoke_image_distance(
                translator,
                {"image": image, "kernel": kernel},
            )


def test_constants_arrays_and_unproven_mixed_grids_reject(ee):
    kernel = ee.Kernel.euclidean(1)
    with pytest.raises(UnsupportedEEError, match="finite bound raster source"):
        compile_sdk(ee, ee.Image.constant(5).distance(kernel=kernel))
    with pytest.raises(UnsupportedEEError, match="scalar Image"):
        compile_sdk(ee, source(ee).select("nir").toArray().distance(kernel=kernel))

    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    changed = deepcopy(items)
    changed["sentinel-2-l2a"][1]["properties"]["proj:transform"][2] += 5
    first = (ee.ImageCollection("sentinel-2-l2a")
             .filter(ee.Filter.eq(name="system:index", value="scene-a"))
             .first().select("nir"))
    second = (ee.ImageCollection("sentinel-2-l2a")
              .filter(ee.Filter.eq(name="system:index", value="scene-b"))
              .first().select("nir"))
    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        compile_expression(
            encode(ee, first.add(image2=second).distance(kernel=kernel)),
            [metadata], changed,
        )


def test_radius_and_compilation_limits_are_retained(ee):
    image = source(ee).select("nir")
    maximum = compile_sdk(
        ee, image.distance(kernel=ee.Kernel.euclidean(16)),
    )
    assert distance_specs(maximum)[0]["radius"] == radius_hex(16)
    with pytest.raises(UnsupportedEEError, match="33 by 33"):
        compile_sdk(ee, image.distance(kernel=ee.Kernel.euclidean(16.01)))

    translator = Translator([], {}, None)
    image_ir = Image([("nir", Pixel("constant", (1.0,)))], {})
    kernel_ir = invoke_kernel(translator, "Kernel.euclidean", {"radius": 0})
    # Kernel validation fits beneath the remaining work; reserving the bounded
    # wire specification itself reaches the original compilation cap.
    translator.steps = 49_900
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_image_distance(
            translator, {"image": image_ir, "kernel": kernel_ir},
        )


def test_cached_double_distance_operand_fits_last_process_graph_node():
    from gee.compat.earthengine.graph import Graph

    metadata, items, _ = synthetic_inputs()
    translator = Translator([metadata], items, None)
    compiler = Graph(translator)
    source_ir = Source("sentinel-2-l2a", ("scene-a",), ("nir",))
    operand = Pixel("to_double", (Pixel("band", (source_ir, "nir")),))
    compiler.expression(operand)
    assert 0 < len(compiler.graph) < 499

    for index in range(499 - len(compiler.graph)):
        compiler.graph[f"budget-{index}"] = {
            "process_id": "noop", "arguments": {},
        }
    result = compiler.expression(Pixel(
        "distance", (operand, prepare_distance_spec("euclidean", 0)),
    ))

    assert len(compiler.graph) == 500
    assert result[1] == "v"
