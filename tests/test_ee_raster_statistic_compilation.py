"""Closed numeric reducer plans and raster lowering contracts."""
import pytest

from gee.compat.earthengine.composed_reducers import invoke_composed_reducer
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.finite_reducer_leaves import invoke_finite_reducer
from gee.compat.earthengine.image_numeric_reducers import invoke_raster_numeric_reducer
from gee.compat.earthengine.ir import (
    Collection,
    Image,
    ImageSequence,
    Pixel,
    Reducer,
    Source,
    UnsupportedEEError,
)
from gee.compat.earthengine.numeric_reducer_plan import numeric_outputs
from gee.compat.earthengine.numeric_reducer_grid import require_common_grid


GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]],
}
GRID_TRANSFORM = [1, 0, 0, 0, -1, 1]


def _assets(transform=GRID_TRANSFORM, code="EPSG:4326"):
    return {
        name: {"proj:code": code, "proj:transform": list(transform)}
        for name in ("x", "y")
    }


def translator(collections=("local",), ids=("a", "b")):
    catalog = [{
        "id": cid,
        "cube:dimensions": {"bands": {"values": ["x", "y"]}},
    } for cid in collections]
    items = {cid: [
        {"id": item_id, "bbox": [0, 0, 2, 1], "geometry": GEOMETRY,
         "properties": {"system:index": item_id, "system:time_start": 1_000},
         "assets": _assets()}
        for item_id in ids
    ] for cid in collections}
    return Translator(catalog, items, {})


def image(source, bands=("x", "y"), **metadata):
    return Image(
        [(name, Pixel("band", (source, name))) for name in bands],
        metadata.get("props", {"tag": "kept"}), source,
        footprint=metadata.get("footprint"),
    )


@pytest.mark.parametrize(("name", "expected"), [
    ("sum", (("sum", "sum"),)),
    ("mean", (("mean", "mean"),)),
    ("min", (("min", "min"),)),
    ("max", (("max", "max"),)),
    ("count", (("count", "count"),)),
    ("first", (("first", "first"),)),
    ("last", (("last", "last"),)),
    ("median", (("median", "median"),)),
    ("sd", (("stdDev", "sd"),)),
    ("product", (("product", "product"),)),
    ("stdDev", (("stdDev", "stdDev"),)),
    ("variance", (("variance", "variance"),)),
    ("sampleVariance", (("variance", "sampleVariance"),)),
    ("minMax", (("min", "min"), ("max", "max"))),
])
def test_legacy_numeric_reducers_have_closed_output_and_operation_pairs(name, expected):
    assert numeric_outputs(Translator([], {}, {}), Reducer(name)) == expected


def test_shared_combine_and_set_outputs_keep_operations_when_names_are_removed():
    t = Translator([], {}, {})
    combined = invoke_composed_reducer(t, "Reducer.combine", {
        "reducer1": Reducer("sum"),
        "reducer2": invoke_finite_reducer(t, "Reducer.sampleVariance", {}),
        "sharedInputs": True,
        "outputPrefix": "spread_",
    })
    selected = invoke_composed_reducer(t, "Reducer.setOutputs", {
        "reducer": combined,
        "outputs": ["total", None],
    })
    assert numeric_outputs(t, selected) == (("total", "sum"),)


def test_min_max_can_be_renamed_and_a_removed_output_is_not_emitted():
    t = Translator([], {}, {})
    spec = invoke_finite_reducer(t, "Reducer.minMax", {})
    selected = invoke_composed_reducer(t, "Reducer.setOutputs", {
        "reducer": spec,
        "outputs": ["low", None],
    })
    assert numeric_outputs(t, selected) == (("low", "min"),)


@pytest.mark.parametrize("build", [
    lambda t: invoke_composed_reducer(t, "Reducer.combine", {
        "reducer1": Reducer("sum"), "reducer2": Reducer("mean"),
        "sharedInputs": False,
    }),
    lambda t: invoke_composed_reducer(t, "Reducer.group", {
        "reducer": Reducer("sum"), "groupField": 0,
    }),
    lambda t: invoke_composed_reducer(t, "Reducer.repeat", {
        "reducer": Reducer("sum"), "count": 1,
    }),
    lambda t: invoke_composed_reducer(t, "Reducer.forEach", {
        "reducer": Reducer("sum"), "outputNames": ["left"],
    }),
])
def test_nonshared_grouped_and_expanded_descriptors_reject(build):
    t = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError):
        numeric_outputs(t, build(t))


def test_non_numeric_zero_input_multi_input_duplicate_and_empty_outputs_reject():
    t = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError, match="Non-numeric"):
        numeric_outputs(t, invoke_finite_reducer(t, "Reducer.frequencyHistogram", {}))
    with pytest.raises(UnsupportedEEError, match="exactly one input"):
        numeric_outputs(t, invoke_finite_reducer(t, "Reducer.countEvery", {}))
    with pytest.raises(UnsupportedEEError, match="Reducer"):
        numeric_outputs(t, Reducer("pearsonsCorrelation"))
    with pytest.raises(UnsupportedEEError, match="at least one"):
        numeric_outputs(t, invoke_composed_reducer(t, "Reducer.setOutputs", {
            "reducer": Reducer("sum"), "outputs": [None],
        }))
    duplicate = invoke_composed_reducer(t, "Reducer.combine", {
        "reducer1": Reducer("sum"), "reducer2": Reducer("sum"),
        "sharedInputs": True,
    })
    with pytest.raises(UnsupportedEEError, match="unique"):
        numeric_outputs(t, duplicate)


def test_numeric_plan_reserves_work_before_returning_output_pairs():
    t = Translator([], {}, {})
    t.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        numeric_outputs(t, Reducer("sum"))
    assert t.steps == 49_999


def test_image_reduce_preserves_metadata_and_uses_double_native_band_operations():
    t = translator(ids=("a",))
    source = Source("local", ("a",), ("x", "y"))
    source_image = image(source)
    reducer = invoke_finite_reducer(t, "Reducer.minMax", {})
    result = invoke_raster_numeric_reducer(t, "Image.reduce", {
        "image": source_image, "reducer": reducer,
    })

    assert [name for name, _ in result.bands] == ["min", "max"]
    assert result.props == source_image.props
    assert result.source == source_image.source
    assert [pixel.args[1] for _, pixel in result.bands] == ["min", "max"]
    assert all(pixel.args[0][0].op == "to_double" for _, pixel in result.bands)


def test_image_reduce_shared_combine_uses_final_set_outputs_names():
    t = translator(ids=("a",))
    source = Source("local", ("a",), ("x", "y"))
    reducer = invoke_composed_reducer(t, "Reducer.setOutputs", {
        "reducer": invoke_composed_reducer(t, "Reducer.combine", {
            "reducer1": Reducer("sum"), "reducer2": Reducer("mean"),
            "sharedInputs": True,
        }),
        "outputs": [None, "average"],
    })
    result = invoke_raster_numeric_reducer(t, "Image.reduce", {
        "image": image(source), "reducer": reducer,
    })
    assert [name for name, _ in result.bands] == ["average"]
    assert result.bands[0][1].args[1] == "mean"


def test_image_reduce_rejects_distinct_source_lineages_before_constructing_merge():
    t = translator(ids=("a", "b"))
    image_value = Image([
        ("x", Pixel("band", (Source("local", ("a",), ("x", "y")), "x"))),
        ("y", Pixel("band", (Source("local", ("b",), ("x", "y")), "y"))),
    ], {})
    with pytest.raises(UnsupportedEEError, match="distinct source lineages"):
        invoke_raster_numeric_reducer(t, "Image.reduce", {
            "image": image_value, "reducer": Reducer("sum"),
        })


def test_collection_reduce_keeps_band_prefixes_and_rejects_unsupported_parallel_scale():
    t = translator(ids=("a", "b"))
    source = Source("local", ("a", "b"), ("x", "y"))
    collection = Collection(source, image(source))
    result = invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
        "collection": collection, "reducer": Reducer("mean"), "parallelScale": 1,
    })
    assert [name for name, _ in result.bands] == ["x_mean", "y_mean"]
    assert all(pixel.op == "reduce_t" for _, pixel in result.bands)
    assert all(pixel.args[0].op == "to_double" for _, pixel in result.bands)
    with pytest.raises(UnsupportedEEError, match="default parallelScale"):
        invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
            "collection": collection, "reducer": Reducer("mean"), "parallelScale": 2,
        })
    for invalid in (True, 0, float("nan"), float("inf"), "1"):
        with pytest.raises(UnsupportedEEError, match="parallelScale"):
            invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
                "collection": collection, "reducer": Reducer("mean"),
                "parallelScale": invalid,
            })
    with pytest.raises(UnsupportedEEError, match="default parallelScale"):
        invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
            "collection": collection, "reducer": Reducer("mean"),
            "parallelScale": 10**1000,
        })


def test_collection_reduce_requires_proven_grid_for_multiple_items():
    t = translator(ids=("a", "b"))
    t.items["local"][1].pop("assets")
    source = Source("local", ("a", "b"), ("x", "y"))
    with pytest.raises(UnsupportedEEError, match="complete proj:code/epsg"):
        invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
            "collection": Collection(source, image(source)), "reducer": Reducer("mean"),
        })


@pytest.mark.parametrize(("transform", "code", "message"), [
    ([2, 0, 0, 0, -1, 1], "EPSG:4326", "common pixel grid"),
    ([1, 0, 0.5, 0, -1, 1], "EPSG:4326", "common pixel grid"),
    ([1, 0, 0, 0, -1, 1], "EPSG:3857", "common pixel grid"),
])
def test_collection_reduce_rejects_incompatible_asset_grid(transform, code, message):
    t = translator(ids=("a", "b"))
    t.items["local"][1]["assets"] = _assets(transform, code)
    source = Source("local", ("a", "b"), ("x", "y"))
    with pytest.raises(UnsupportedEEError, match=message):
        invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
            "collection": Collection(source, image(source)), "reducer": Reducer("mean"),
        })


def test_collection_reduce_accepts_integer_pixel_origin_offsets():
    t = translator(ids=("a", "b"))
    t.items["local"][1]["assets"] = _assets([1, 0, 2, 0, -1, 1])
    source = Source("local", ("a", "b"), ("x", "y"))
    result = invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
        "collection": Collection(source, image(source)), "reducer": Reducer("mean"),
    })
    assert [name for name, _ in result.bands] == ["x_mean", "y_mean"]


def test_collection_reduce_compares_tiny_affine_bases_exactly():
    tiny = 2.0**-50
    t = translator(ids=("a", "b"))
    t.items["local"][0]["assets"] = _assets([tiny, 0, 0, 0, -tiny, 1])
    t.items["local"][1]["assets"] = _assets([
        tiny + 2.0**-100, 0, 0, 0, -tiny, 1,
    ])
    source = Source("local", ("a", "b"), ("x", "y"))
    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
            "collection": Collection(source, image(source)), "reducer": Reducer("mean"),
        })


def test_collection_reduce_rejects_nearly_singular_and_large_origin_fractional_offsets():
    t = translator(ids=("a", "b"))
    near_singular = [1, 1, 0, 1, 1 + 2.0**-40, 0]
    t.items["local"][0]["assets"] = _assets(near_singular)
    t.items["local"][1]["assets"] = _assets(near_singular)
    source = Source("local", ("a", "b"), ("x", "y"))
    with pytest.raises(UnsupportedEEError, match="singular affine"):
        invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
            "collection": Collection(source, image(source)), "reducer": Reducer("mean"),
        })

    t = translator(ids=("a", "b"))
    t.items["local"][0]["assets"] = _assets([1000, 0, 1e12, 0, -1000, 1e12])
    t.items["local"][1]["assets"] = _assets([1000, 0, 1e12 + 500, 0, -1000, 1e12])
    source = Source("local", ("a", "b"), ("x", "y"))
    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
            "collection": Collection(source, image(source)), "reducer": Reducer("mean"),
        })


def test_grid_lookup_rejects_duplicate_item_ids():
    t = translator(ids=("a", "b"))
    t.items["local"][1]["id"] = "a"
    source = Source("local", ("a", "b"), ("x", "y"))
    with pytest.raises(UnsupportedEEError, match="duplicate item IDs"):
        invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
            "collection": Collection(source, image(source)), "reducer": Reducer("mean"),
        })


def test_item_properties_projection_is_a_supported_grid_fallback():
    t = translator(ids=("a", "b"))
    for item in t.items["local"]:
        item.pop("assets")
        item["properties"].update({
            "proj:epsg": 4326,
            "proj:transform": GRID_TRANSFORM,
        })
    source = Source("local", ("a", "b"), ("x", "y"))
    result = invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
        "collection": Collection(source, image(source)), "reducer": Reducer("sum"),
    })
    assert [name for name, _ in result.bands] == ["x_sum", "y_sum"]


def test_one_item_does_not_require_projection_metadata_and_merge_rejects_free_values():
    t = translator(ids=("a",))
    t.items["local"][0].pop("assets")
    source = Source("local", ("a",), ("x", "y"))
    result = invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
        "collection": Collection(source, image(source)), "reducer": Reducer("sum"),
    })
    assert [name for name, _ in result.bands] == ["x_sum", "y_sum"]

    with pytest.raises(UnsupportedEEError, match="source-free"):
        require_common_grid(t, (Pixel("band", (source, "x")), Pixel("const", (1,))))


def test_image_sequence_reduction_preserves_distinct_same_day_frames():
    t = translator(ids=("a", "b"))
    frames = []
    for item_id in ("a", "b"):
        source = Source("local", (item_id,), ("x", "y"))
        frames.append(image(source, props={
            "system:index": item_id, "system:time_start": 1_000,
        }))
    result = invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
        "collection": ImageSequence(frames), "reducer": Reducer("sum"),
    })
    assert [name for name, _ in result.bands] == ["x_sum", "y_sum"]
    stack = result.bands[0][1].args[0]
    assert len(stack) == 2
    assert [pixel.args[0].args[0].ids for pixel in stack] == [("a",), ("b",)]
    assert result.footprint_is_absolute is True


def test_image_sequence_rejects_distinct_collection_lineages_before_merging():
    t = translator(collections=("local", "other"), ids=("a",))
    frames = [
        image(Source("local", ("a",), ("x", "y")), bands=("x",)),
        image(Source("other", ("a",), ("x", "y")), bands=("x",)),
    ]
    with pytest.raises(UnsupportedEEError, match="distinct collection lineages"):
        invoke_raster_numeric_reducer(t, "ImageCollection.reduce", {
            "collection": ImageSequence(frames), "reducer": Reducer("sum"),
        })
