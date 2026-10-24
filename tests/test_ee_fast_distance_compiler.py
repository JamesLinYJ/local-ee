"""Bounded Image.fastDistanceTransform compiler contracts."""
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.image_fast_distance import invoke_image_fast_distance
from gee.compat.earthengine.ir import Image, Pixel, UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.fast_distance_spec import (
    decode_fast_distance_spec,
    prepare_fast_distance_spec,
)
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


def source(ee):
    return ee.ImageCollection("sentinel-2-l2a").first()


def transform_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_fast_distance_transform"]


def transform_specs(result):
    return [decode_fast_distance_spec(node["arguments"]["spec"])
            for node in transform_nodes(result)]


def _has_ancestor(process_graph, node, process_id):
    pending = []

    def refs(value):
        if isinstance(value, dict):
            if set(value) == {"from_node"}:
                pending.append(value["from_node"])
            else:
                for key, child in value.items():
                    if key != "process_graph":
                        refs(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                refs(child)

    refs(node["arguments"])
    seen = set()
    while pending:
        reference = pending.pop()
        if reference in seen:
            continue
        seen.add(reference)
        parent = process_graph[reference]
        if parent["process_id"] == process_id:
            return True
        refs(parent["arguments"])
    return False


def _sdk_call(ee, *, neighborhood="omitted", units="omitted", metric="omitted"):
    image = source(ee).select(["red", "nir"])
    kwargs = {}
    if neighborhood != "omitted":
        kwargs["neighborhood"] = neighborhood
    if units != "omitted":
        kwargs["units"] = units
    if metric != "omitted":
        kwargs["metric"] = metric
    return image.fastDistanceTransform(**kwargs)


def _invocation(encoded):
    return next(
        node for _, node in reversed(encoded["scope"])
        if isinstance(node, dict)
        and node.get("functionName") == "Image.fastDistanceTransform"
    )


def test_sdk_defaults_and_raw_nulls_match_versioned_spec(ee):
    omitted = encode(ee, _sdk_call(ee))
    raw_null = encode(ee, _sdk_call(
        ee, neighborhood=None, units=None, metric=None,
    ))
    assert _invocation(omitted)["arguments"] == _invocation(raw_null)["arguments"]

    default_result = compile_expression(
        omitted, [synthetic_inputs()[0]], synthetic_inputs()[1],
    )
    null_result = compile_expression(
        raw_null, [synthetic_inputs()[0]], synthetic_inputs()[1],
    )
    expected = {"metric": "squared_euclidean", "neighborhood": 256, "v": 1}
    assert transform_specs(default_result) == [expected, expected]
    assert transform_specs(null_result) == [expected, expected]
    assert default_result["bands"] == ["red", "nir"]


@pytest.mark.parametrize(
    "metric", ["squared_euclidean", "manhattan", "chebyshev"],
)
@pytest.mark.parametrize("neighborhood", [1, 7, 4096, 7.0])
def test_supported_metrics_and_integral_neighborhoods_are_canonical(
        ee, metric, neighborhood):
    result = compile_sdk(ee, source(ee).select("nir").fastDistanceTransform(
        neighborhood=neighborhood, units="pixels", metric=metric,
    ))
    assert transform_specs(result) == [{
        "metric": metric, "neighborhood": int(neighborhood), "v": 1,
    }]


@pytest.mark.parametrize(
    "neighborhood", [True, False, 0, -1, 4097, 2.5, float("inf"),
                     float("nan"), 10**1000],
)
def test_invalid_neighborhood_types_and_bounds_reject(neighborhood):
    translator = Translator([], {}, None)
    image = Image([("nir", Pixel("constant", (1.0,)))], {})
    with pytest.raises(UnsupportedEEError, match="integer in 1..4096"):
        invoke_image_fast_distance(
            translator, {"image": image, "neighborhood": neighborhood},
        )


@pytest.mark.parametrize("units", ["meters", "pixel", 1, False, []])
def test_only_pixel_units_are_accepted(units):
    translator = Translator([], {}, None)
    image = Image([("nir", Pixel("constant", (1.0,)))], {})
    with pytest.raises(UnsupportedEEError, match="pixel units only"):
        invoke_image_fast_distance(
            translator, {"image": image, "units": units},
        )


@pytest.mark.parametrize("metric", ["euclidean", "squaredEuclidean", "foo", 1, False])
def test_unknown_or_nonstring_metrics_reject(metric):
    translator = Translator([], {}, None)
    image = Image([("nir", Pixel("constant", (1.0,)))], {})
    with pytest.raises(UnsupportedEEError, match="metric must be"):
        invoke_image_fast_distance(
            translator, {"image": image, "metric": metric},
        )


def test_multiband_properties_and_pixel_callback_chain_are_preserved(ee):
    image = (source(ee).select(["red", "nir"])
             .set("local-tag", "retained")
             .fastDistanceTransform(neighborhood=16))
    result = compile_sdk(ee, image)
    assert result["bands"] == ["red", "nir"]
    assert result["properties"]["local-tag"] == "retained"
    assert len(transform_nodes(result)) == 2
    assert all(node["arguments"]["spec"] == transform_nodes(result)[0]["arguments"]["spec"]
               for node in transform_nodes(result))

    chained = compile_sdk(
        ee, source(ee).select("nir")
        .fastDistanceTransform(neighborhood=8).sqrt().lt(3),
    )
    assert chained["kind"] == "image"
    assert chained["bands"] == ["nir"]
    assert len(transform_nodes(chained)) == 1


def test_fast_distance_cast_keeps_existing_float32_arithmetic_boundary(ee):
    image = (source(ee).select("nir").toFloat().add(1)
             .fastDistanceTransform(neighborhood=2))
    graph = compile_sdk(ee, image)["process_graph"]
    nodes = list(graph.values())
    ids = [node["process_id"] for node in nodes]
    to_float = ids.index("local_ee_to_float")
    callback = next(index for index, node in enumerate(nodes)
                    if node["process_id"] == "reduce_dimension"
                    and node["arguments"]["dimension"] == "bands")
    to_double = ids.index("local_ee_to_double")
    transform = ids.index("local_ee_fast_distance_transform")
    assert to_float < callback < to_double < transform


def test_fast_distance_keeps_full_source_bounds_before_export_roi(ee):
    result = compile_sdk(
        ee,
        source(ee).select("nir").fastDistanceTransform(neighborhood=4),
        options={"region": EXPORT_REGION, "scale": 40},
    )
    nodes = list(result["process_graph"].values())
    load = next(node for node in nodes if node["process_id"] == "load_collection")
    transform = next(node for node in nodes
                     if node["process_id"] == "local_ee_fast_distance_transform")
    assert load["arguments"]["spatial_extent"] == {
        "west": 100, "south": 30, "east": 101, "north": 31,
    }
    process_ids = [node["process_id"] for node in nodes]
    assert process_ids.index("load_collection") < process_ids.index(
        "local_ee_fast_distance_transform",
    ) < process_ids.index("resample_spatial") < process_ids.index("mask_polygon")
    assert transform["arguments"]["spec"]


def test_mapped_fast_distance_preserves_collection_time_and_keys(ee):
    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    collection = ee.ImageCollection("sentinel-2-l2a").map(
        lambda image: image.select("nir").fastDistanceTransform(
            neighborhood=5, metric="manhattan",
        ),
    )
    result = compile_expression(encode(ee, collection), [metadata], items)
    assert result["kind"] == "collection"
    assert result["has_time_dimension"] is True
    assert result["bands"] == ["nir"]
    assert result["source_item_ids"] == ["scene-a", "scene-b", "scene-c"]
    assert len(transform_nodes(result)) == 1
    assert transform_specs(result) == [{
        "metric": "manhattan", "neighborhood": 5, "v": 1,
    }]


def test_first_clip_mask_input_is_widened_before_fast_transform(ee):
    image = (source(ee).select("nir")
             .clip(ee.Geometry.Rectangle([100.1, 30.1, 100.9, 30.9]))
             .updateMask(ee.Image.constant(1))
             .fastDistanceTransform(neighborhood=2))
    with pytest.raises(UnsupportedEEError, match="Image.clip spherical geometry edges"):
        compile_sdk(ee, image)
    image = (source(ee).select("nir")
             .clip(ee.Geometry.Rectangle([100.1, 30.1, 100.9, 30.9], geodesic=False))
             .updateMask(ee.Image.constant(1))
             .fastDistanceTransform(neighborhood=2))
    result = compile_sdk(ee, image)
    graph = result["process_graph"]
    nodes = list(graph.values())
    clip = next(node for node in nodes if node["process_id"] == "mask_polygon")
    mask = next(node for node in nodes if node["process_id"] == "mask")
    transform = next(node for node in nodes
                     if node["process_id"] == "local_ee_fast_distance_transform")
    assert _has_ancestor(graph, clip, "local_ee_to_double")
    assert _has_ancestor(graph, mask, "local_ee_to_double")
    assert _has_ancestor(graph, transform, "local_ee_to_double")
    node_ids = list(graph)
    mask_index = node_ids.index(next(key for key, node in graph.items()
                                     if node is mask))
    transform_index = node_ids.index(next(key for key, node in graph.items()
                                          if node is transform))
    assert mask_index < transform_index
    assert not any(node["process_id"] == "mask"
                   for node in list(graph.values())[transform_index + 1:])

    # Int32 distance output is exact through 2^24 and is intentionally not
    # classified as a Float64 result by the generic callback guard.
    translator = Translator([], {}, None)
    from gee.compat.earthengine.graph import Graph as PixelGraph

    compiler = PixelGraph(translator)
    pixel = Pixel(
        "fast_distance",
        (Pixel("to_double", (Pixel("constant", (1.0,)),)),
         prepare_fast_distance_spec(neighborhood=2)),
    )
    assert compiler.has_double_precision(pixel) is False


def test_constants_arrays_and_grid_mismatch_are_rejected(ee):
    with pytest.raises(UnsupportedEEError, match="finite bound raster source"):
        compile_sdk(
            ee, ee.Image.constant(1).fastDistanceTransform(neighborhood=3),
        )
    with pytest.raises(UnsupportedEEError, match="scalar Image"):
        compile_sdk(
            ee, source(ee).select("nir").toArray().fastDistanceTransform(),
        )

    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"]["proj:code"] = "EPSG:32610"
        item["properties"]["proj:transform"] = [10, 0, 500000, 0, -10, 3500000]
    changed = {key: [dict(item, properties=dict(item["properties"]))
                     for item in rows] for key, rows in items.items()}
    changed["sentinel-2-l2a"][1]["properties"]["proj:transform"][2] += 5
    first = (ee.ImageCollection("sentinel-2-l2a")
             .filter(ee.Filter.eq(name="system:index", value="scene-a"))
             .first().select("nir"))
    second = (ee.ImageCollection("sentinel-2-l2a")
              .filter(ee.Filter.eq(name="system:index", value="scene-b"))
              .first().select("nir"))
    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        compile_expression(
            encode(ee, first.add(image2=second).fastDistanceTransform()),
            [metadata], changed,
        )
