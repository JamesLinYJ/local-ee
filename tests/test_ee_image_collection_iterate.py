"""Finite, ordered ImageCollection.iterate semantics."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Function, Image, ImageSequence, Pixel, const
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


@pytest.fixture
def context():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path="vendor/earthengine-js/algorithms.json",
        )
        metadata, items, _ = synthetic_inputs()
        yield ee, [metadata], items
    assert guard.evidence()["attempt_count"] == 0


def _evaluate(context, value):
    ee, catalog, items = context
    wire = ee.serializer.encode(value, for_cloud_api=False)
    return Translator(catalog, items, {}).evaluate(wire), wire


def _pixel_sources(value):
    found = []

    def visit(pixel):
        if not isinstance(pixel, Pixel):
            return
        if pixel.op == "band":
            found.append(pixel.args[0])
        for child in pixel.args:
            if isinstance(child, Pixel):
                visit(child)
            elif isinstance(child, (tuple, list)):
                for nested in child:
                    visit(nested)

    for _, pixel in value.bands:
        visit(pixel)
    return found


def test_catalog_iterate_preserves_sorted_current_and_accumulator_order(context):
    ee, _, _ = context
    collection = ee.ImageCollection("sentinel-2-l2a").sort(
        "system:index", ascending=False,
    )
    value = collection.iterate(
        lambda current, accumulator: ee.List(accumulator).add(
            ee.Image(current).getString("system:index"),
        ),
        [],
    )

    result, _ = _evaluate(context, value)
    assert result == ["scene-c", "scene-b", "scene-a"]


def test_catalog_iterate_exposes_per_item_metadata_without_aliasing_source(context):
    ee, _, items = context
    items["sentinel-2-l2a"][0]["properties"]["nested"] = {
        "labels": ["original"],
    }
    value = ee.ImageCollection("sentinel-2-l2a").limit(
        1, "system:index", ascending=True,
    ).iterate(
        lambda current, accumulator: ee.Image(current).get("nested"),
        None,
    )

    result, _ = _evaluate(context, value)
    assert result == {"labels": ["original"]}
    result["labels"].append("caller mutation")
    assert items["sentinel-2-l2a"][0]["properties"]["nested"] == {
        "labels": ["original"],
    }


def test_sequence_iterate_adds_actual_frames_in_explicit_order(context):
    ee, catalog, items = context
    first = ee.ImageCollection("sentinel-2-l2a").sort(
        "system:index", ascending=False,
    ).first().select("red").rename("late")
    second = ee.ImageCollection("sentinel-2-l2a").sort(
        "system:index", ascending=True,
    ).first().select("green").rename("early")
    collection = ee.ImageCollection.fromImages([first, second])
    value = collection.iterate(
        lambda current, accumulator: ee.Image(accumulator).addBands(current),
        ee.Image().select([]),
    )

    result, wire = _evaluate(context, value)
    assert [name for name, _ in result.bands] == ["late", "early"]
    assert [source.ids for source in _pixel_sources(result)] == [
        ("scene-c",), ("scene-a",),
    ]
    compiled = compile_expression(wire, catalog, items)
    assert compiled["bands"] == ["late", "early"]
    assert compiled["source_item_ids"] == ["scene-c", "scene-a"]


def test_empty_catalog_iterate_returns_owned_seed_and_preflights_callback(context):
    ee, _, _ = context
    empty = ee.ImageCollection("sentinel-2-l2a").filterDate(
        "2030-01-01", "2031-01-01",
    )
    seed = {"nested": {"values": [1]}}
    result, _ = _evaluate(
        context, empty.iterate(lambda current, accumulator: accumulator, seed),
    )
    assert result == seed
    assert result is not seed and result["nested"] is not seed["nested"]

    invalid = empty.iterate(
        lambda current, accumulator: ee.Image(current).paint(
            ee.FeatureCollection([]),
        ),
        0,
    )
    with pytest.raises(UnsupportedEEError, match="Unsupported Earth Engine algorithm"):
        _evaluate(context, invalid)

    valid = empty.iterate(
        lambda current, accumulator: ee.Image(current).select([]),
        123,
    )
    assert _evaluate(context, valid)[0] == 123


def test_sequence_null_seed_can_be_unused_and_callback_can_return_null(context):
    ee, _, _ = context
    images = ee.ImageCollection.fromImages([
        ee.Image.constant(1), ee.Image.constant(2),
    ])
    unused = images.iterate(
        lambda current, accumulator: ee.Image(current).get("system:index"),
        None,
    )
    assert _evaluate(context, unused)[0] == "1"

    null_result = images.iterate(
        lambda current, accumulator: ee.Algorithms.If(
            condition=False, trueCase=1, falseCase=None,
        ),
        7,
    )
    assert _evaluate(context, null_result)[0] is None


def _pixel_chain(pixel, count):
    for _ in range(count):
        pixel = Pixel("wrapper", (pixel,))
    return pixel


def _shared_depth_collection(context, wrapper_count):
    _, catalog, items = context
    translator = Translator(catalog, items, {})
    collection = translator.load("sentinel-2-l2a")
    shared = _pixel_chain(const(1), 30)
    deep = _pixel_chain(shared, wrapper_count)
    collection.image.bands = [("shallow", shared), ("deep", deep)]
    callback = Function(
        ["current", "accumulator"],
        {"type": "ArgumentRef", "value": "accumulator"},
        {},
    )
    return translator, collection, callback


def _iterate_direct(translator, collection, callback):
    return translator.invoke("Collection.iterate", {
        "collection": collection, "function": callback, "first": 9,
    })


def test_shared_pixel_subtree_is_allowed_at_exact_depth_96(context):
    translator, collection, callback = _shared_depth_collection(context, 64)
    assert _iterate_direct(translator, collection, callback) == 9


def test_shared_pixel_subtree_is_rejected_at_depth_97_after_shallow_visit(context):
    translator, collection, callback = _shared_depth_collection(context, 65)
    with pytest.raises(UnsupportedEEError, match="band expression exceeds depth 96"):
        _iterate_direct(translator, collection, callback)


def test_callback_environment_copy_work_is_precharged_before_evaluation():
    translator = Translator([], {}, {})
    translator.steps = 49_918
    called = []

    def evaluate(*args, **kwargs):
        called.append(True)
        return 1

    translator.evaluate = evaluate
    callback = Function(
        ["current", "accumulator"],
        {"type": "ArgumentRef", "value": "accumulator"},
        {"captured": {"value": 1}},
    )
    with pytest.raises(UnsupportedEEError, match="callback environment copies"):
        translator.invoke("Collection.iterate", {
            "collection": ImageSequence([Image([], {})]),
            "function": callback,
            "first": 0,
        })
    assert called == []


def test_catalog_frame_and_callback_copy_work_are_reserved_before_materialization(
    context, monkeypatch,
):
    import gee.compat.earthengine.image_collection_iterate as iterate_module

    _, catalog, items = context
    translator = Translator(catalog, items, {})
    collection = translator.load("sentinel-2-l2a")
    callback = Function(
        ["current", "accumulator"],
        {"type": "ArgumentRef", "value": "accumulator"},
        {"captured": 1},
    )
    translator.steps = 49_900
    built = []
    monkeypatch.setattr(iterate_module, "_catalog_item_map", lambda *_: {})
    monkeypatch.setattr(iterate_module, "_rebind_work", lambda *_: 0)
    monkeypatch.setattr(
        iterate_module, "_catalog_frame", lambda *args: built.append(args),
    )

    with pytest.raises(UnsupportedEEError, match="callback environment copies"):
        iterate_module._catalog_frames(translator, collection, callback)

    assert built == []
    frame_cost = len(collection.source.ids) * (2 * len(collection.image.bands) + 3)
    sizing_cost = sum(len(key) + 1 for key in callback.env)
    sizing_cost += sum(len(name) + 1 for name in callback.names)
    assert translator.steps == 49_900 + frame_cost + sizing_cost
