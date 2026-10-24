"""Pinned Python SDK workflows over bounded inline FeatureCollections."""
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Filter


@pytest.fixture
def ee_sdk():
    import ee

    configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2",
        "a" * 48,
        signatures_path="vendor/earthengine-js/algorithms.json",
    )
    return ee


def compile_sdk(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def _features(value):
    assert value["type"] == "FeatureCollection"
    return value["features"]


def test_feature_collection_size_first_list_and_aggregate_array(ee_sdk):
    ee = ee_sdk
    features = [
        ee.Feature(ee.Geometry.Point(1, 2), {"name": "first", "score": 4, "system:index": "a"}),
        ee.Feature(None, {"name": "second", "score": None}),
        ee.Feature(ee.Geometry.Point(3, 4), {"name": "third", "score": 0}),
    ]
    collection = ee.FeatureCollection(features)

    assert compile_sdk(ee, collection.size()) == 3
    assert compile_sdk(ee, collection.first()) == {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [1, 2]},
        "properties": {"name": "first", "score": 4, "system:index": "a"},
    }
    assert compile_sdk(ee, collection.toList(2, 1)) == [
        {"type": "Feature", "geometry": None, "properties": {"name": "second", "score": None}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3, 4]},
         "properties": {"name": "third", "score": 0}},
    ]
    assert compile_sdk(ee, collection.aggregate_array("score")) == [4, None, 0]
    assert compile_sdk(ee, collection.aggregate_array("missing")) == [None, None, None]
    assert compile_sdk(ee, features[0].get("missing")) is None
    assert compile_sdk(ee, features[0].get("system:index")) == "a"


def test_feature_map_sets_properties_and_respects_null_and_return_types(ee_sdk):
    ee = ee_sdk
    collection = ee.FeatureCollection([
        ee.Feature(ee.Geometry.Point(1, 2), {"name": "keep", "include": True}),
        ee.Feature(ee.Geometry.Point(3, 4), {"name": "drop", "include": False}),
    ])
    mapped = collection.map(
        lambda feature: feature.setMulti({
            "label": feature.get("name"),
            "missing": feature.get("not-present"),
        })
    )
    values = _features(compile_sdk(ee, mapped))
    assert values == [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
         "properties": {"name": "keep", "include": True, "label": "keep", "missing": None}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3, 4]},
         "properties": {"name": "drop", "include": False, "label": "drop", "missing": None}},
    ]

    nullable = collection.map(
        lambda feature: ee.Algorithms.If(feature.get("include"), feature, None),
        dropNulls=True,
    )
    assert _features(compile_sdk(ee, nullable)) == [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]},
         "properties": {"name": "keep", "include": True}}
    ]
    with pytest.raises(UnsupportedEEError, match="dropNulls=true"):
        compile_sdk(ee, collection.map(lambda feature: ee.Algorithms.If(
            feature.get("include"), feature, None
        )))
    with pytest.raises(UnsupportedEEError, match="must return a Feature"):
        compile_sdk(ee, collection.map(lambda feature: feature.get("name")))


def test_feature_collection_filters_nulls_then_orders_and_limits(ee_sdk):
    ee = ee_sdk
    collection = ee.FeatureCollection([
        ee.Feature(None, {"score": 3, "label": "c"}),
        ee.Feature(None, {"label": "missing"}),
        ee.Feature(None, {"score": None, "label": "null"}),
        ee.Feature(None, {"score": 1, "label": "a"}),
        ee.Feature(None, {"score": 2, "label": "b"}),
    ])
    selected = collection.filter(ee.Filter.notNull(["score"])).filter(ee.Filter.gt("score", 1))
    assert [feature["properties"]["label"] for feature in _features(compile_sdk(ee, selected))] == [
        "c", "b"
    ]
    ordered = collection.filter(ee.Filter.notNull(["score"])).sort("score").limit(2)
    assert [feature["properties"]["label"] for feature in _features(compile_sdk(ee, ordered))] == [
        "a", "b"
    ]
    descending = collection.filter(ee.Filter.notNull(["score"])).sort("score", False)
    assert [feature["properties"]["label"] for feature in _features(compile_sdk(ee, descending))] == [
        "c", "b", "a"
    ]


def test_feature_filter_ordered_comparisons_treat_absent_and_null_as_nonmatches(ee_sdk):
    ee = ee_sdk
    collection = ee.FeatureCollection([
        ee.Feature(None, {"label": "absent"}),
        ee.Feature(None, {"label": "null", "score": None}),
        ee.Feature(None, {"label": "one", "score": 1}),
        ee.Feature(None, {"label": "two", "score": 2}),
        ee.Feature(None, {"label": "three", "score": 3}),
    ])
    cases = [
        (ee.Filter.gt("score", 1), ["two", "three"]),
        (ee.Filter.gte("score", 2), ["two", "three"]),
        (ee.Filter.lt("score", 2), ["one"]),
        (ee.Filter.lte("score", 2), ["one", "two"]),
    ]
    for filt, expected in cases:
        result = collection.filter(filt)
        assert [f["properties"]["label"] for f in _features(compile_sdk(ee, result))] == expected


def test_feature_filter_and_or_not_recurse_with_unknown_null_logic(ee_sdk):
    ee = ee_sdk
    collection = ee.FeatureCollection([
        ee.Feature(None, {"label": "missing"}),
        ee.Feature(None, {"label": "null", "score": None, "other": None}),
        ee.Feature(None, {"label": "low", "score": 1, "other": 11}),
        ee.Feature(None, {"label": "high", "score": 3, "other": 11}),
        ee.Feature(None, {"label": "mid", "score": 2, "other": 0}),
        ee.Feature(None, {"label": "alternate", "other": 11}),
    ])
    score_gt_one = ee.Filter.gt("score", 1)
    other_gt_ten = ee.Filter.gt("other", 10)
    conjunction = ee.Filter.And(score_gt_one, other_gt_ten)
    disjunction = ee.Filter.Or(ee.Filter.gt("score", 2), other_gt_ten)
    negation = ee.Filter.Not(ee.Filter.gt("score", 2))

    def labels(value):
        return [f["properties"]["label"] for f in _features(compile_sdk(ee, value))]

    assert labels(collection.filter(conjunction)) == ["high"]
    assert labels(collection.filter(disjunction)) == ["low", "high", "alternate"]
    assert labels(collection.filter(negation)) == ["low", "mid"]


def test_feature_filter_null_equality_and_unknown_operations_fail_explicitly(ee_sdk):
    ee = ee_sdk
    collection = ee.FeatureCollection([ee.Feature(None, {"score": 1})])
    with pytest.raises(UnsupportedEEError, match="equality involving missing/null"):
        compile_sdk(ee, collection.filter(ee.Filter.eq("missing", 1)))
    with pytest.raises(UnsupportedEEError, match="equality involving missing/null"):
        compile_sdk(ee, collection.filter(ee.Filter.eq("score", None)))

    feature = {"type": "Feature", "geometry": None, "properties": {"score": 1}}
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        translator.invoke("Collection.filter", {
            "collection": {"type": "FeatureCollection", "features": [feature]},
            "filter": Filter("greaterThan", {
                "leftField": "score", "rightValue": 0, "ignored": True,
            }),
        })
    with pytest.raises(UnsupportedEEError, match="Unsupported inline Feature filter"):
        translator.invoke("Collection.filter", {
            "collection": {"type": "FeatureCollection", "features": [feature]},
            "filter": Filter("unknown", {}),
        })


def test_feature_filter_scalar_types_do_not_conflate_boolean_or_arrays(ee_sdk):
    ee = ee_sdk
    collection = ee.FeatureCollection([
        ee.Feature(None, {"label": "boolean", "value": True}),
        ee.Feature(None, {"label": "number", "value": 1}),
    ])
    selected = collection.filter(ee.Filter.eq("value", 1))
    assert [f["properties"]["label"] for f in _features(compile_sdk(ee, selected))] == ["number"]

    array_feature = ee.Feature(None, {"coefficients": ee.Array([1, 2])})
    array_filter = ee.Filter.eq("coefficients", ee.Array([1, 2]))
    with pytest.raises(UnsupportedEEError, match="scalar metadata operands only"):
        compile_sdk(ee, ee.FeatureCollection([array_feature]).filter(array_filter))


def test_feature_filter_predicate_and_feature_work_share_compilation_budget(ee_sdk):
    ee = ee_sdk
    collection = ee.FeatureCollection([
        ee.Feature(None, {"score": 1}) for _ in range(600)
    ])
    repeated_predicate = ee.Filter.Or(*[
        ee.Filter.gt("score", 0) for _ in range(100)
    ])
    with pytest.raises(UnsupportedEEError, match="graph exceeds compilation limits"):
        compile_sdk(ee, collection.filter(repeated_predicate))


def test_feature_string_filter_comparison_charges_character_work():
    translator = Translator([], {}, None)
    translator.steps = 49990
    feature = {"type": "Feature", "geometry": None,
               "properties": {"label": "abcdefghij"}}
    collection = {"type": "FeatureCollection", "features": [feature]}
    filt = Filter("equals", {"leftField": "label", "rightValue": "abcdefghij"})
    with pytest.raises(UnsupportedEEError, match="graph exceeds compilation limits"):
        translator.invoke("Collection.filter", {"collection": collection, "filter": filt})


def test_shared_long_feature_ids_and_sort_keys_cannot_amplify_work(ee_sdk):
    ee = ee_sdk
    # The SDK shares this long string in the DAG. A tiny size() result must
    # still pay for ID allocation or repeated string-key comparisons.
    shared = "x" * 30_000
    collection = ee.FeatureCollection([
        ee.Feature(None, {"system:index": shared, "sort_key": shared}),
        ee.Feature(None, {"system:index": shared, "sort_key": shared}),
    ])
    for value in (collection.merge(ee.FeatureCollection([])).size(),
                  collection.sort("sort_key").size()):
        with pytest.raises(UnsupportedEEError, match="graph exceeds compilation limits"):
            compile_sdk(ee, value)


def test_feature_collection_merge_iterate_and_copy_properties(ee_sdk):
    ee = ee_sdk
    first = ee.FeatureCollection([
        ee.Feature(None, {"score": 2, "system:index": "left-a", "keep": "copied"}),
        ee.Feature(None, {"score": 3, "system:index": "left-b"}),
    ])
    second = ee.FeatureCollection([ee.Feature(None, {"score": 5, "system:index": "right-a"})])
    merged = first.merge(second)
    merged_features = _features(compile_sdk(ee, merged))
    assert [f["properties"]["score"] for f in merged_features] == [2, 3, 5]
    assert [f["properties"]["system:index"] for f in merged_features] == [
        "1_left-a", "1_left-b", "2_right-a"
    ]
    repeated = merged.merge(ee.FeatureCollection([
        ee.Feature(None, {"score": 8, "system:index": "last"})
    ]))
    assert [f["properties"]["system:index"] for f in _features(compile_sdk(ee, repeated))] == [
        "1_1_left-a", "1_1_left-b", "1_2_right-a", "2_last"
    ]
    total = merged.iterate(
        lambda feature, previous: ee.Number(previous).add(ee.Number(feature.get("score"))), 0
    )
    assert compile_sdk(ee, total) == 10

    source = ee.Feature(None, {"keep": "copied", "omit": 7, "system:index": "source-id"})
    destination = ee.Feature(ee.Geometry.Point(8, 9), {"own": True})
    copied = compile_sdk(ee, destination.copyProperties(source))
    assert copied == {
        "type": "Feature", "geometry": {"type": "Point", "coordinates": [8, 9]},
        "properties": {"own": True, "keep": "copied", "omit": 7},
    }
    explicit = compile_sdk(ee, destination.copyProperties(source, properties=["system:index"]))
    assert explicit["properties"] == {"own": True, "system:index": "source-id"}
    excluded = compile_sdk(ee, destination.copyProperties(source, exclude=["omit"]))
    assert excluded["properties"] == {"own": True, "keep": "copied"}


def test_feature_collection_merge_requires_and_prefixes_sdk_feature_ids(ee_sdk):
    ee = ee_sdk
    geojson = ee.Feature({
        "type": "Feature", "id": "geojson-id",
        "geometry": {"type": "Point", "coordinates": [5, 6]},
        "properties": {"label": "source"},
    })
    other = ee.Feature(None, {"label": "other", "system:index": "other-id"})
    merged = ee.FeatureCollection([geojson]).merge(ee.FeatureCollection([other]))
    assert [feature["properties"]["system:index"] for feature in _features(compile_sdk(ee, merged))] == [
        "1_geojson-id", "2_other-id"
    ]

    no_id = ee.FeatureCollection([ee.Feature(None, {"label": "anonymous"})])
    with pytest.raises(UnsupportedEEError, match="explicit Feature id or system:index"):
        compile_sdk(ee, no_id.merge(ee.FeatureCollection([])))


def test_merge_preserves_and_reprefixes_existing_top_level_ids():
    first = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "left", "geometry": None, "properties": {"x": 1}}
    ]}
    second = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "right", "geometry": None, "properties": {"x": 2}}
    ]}
    translator = Translator([], {}, None)
    merged = translator.invoke("Collection.merge", {"collection1": first, "collection2": second})
    assert [feature["id"] for feature in merged["features"]] == ["1_left", "2_right"]
    repeated = translator.invoke("Collection.merge", {
        "collection1": merged,
        "collection2": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": "last", "geometry": None, "properties": {}}
        ]},
    })
    assert [feature["id"] for feature in repeated["features"]] == [
        "1_1_left", "1_2_right", "2_last"
    ]
    assert first["features"][0]["id"] == "left"


def test_feature_properties_preserve_typed_arrays_for_ee_array_calls(ee_sdk):
    ee = ee_sdk
    collection = ee.FeatureCollection([
        ee.Feature(None, {"x0": 1, "x1": 0, "y": 5}),
        ee.Feature(None, {"x0": 1, "x1": 1, "y": 7}),
        ee.Feature(None, {"x0": 1, "x1": 2, "y": 9}),
    ])
    fit = collection.reduceColumns(
        reducer=ee.Reducer.linearRegression(numX=2, numY=1),
        selectors=["x0", "x1", "y"],
    )
    wrapped = ee.Feature(None, {"coefficients": fit.get("coefficients")})
    assert compile_sdk(ee, ee.Array(wrapped.get("coefficients")).get([1, 0])) == pytest.approx(
        2, abs=1e-14
    )


def test_feature_element_updates_and_geometry_preserve_feature_fields(ee_sdk):
    ee = ee_sdk
    feature = ee.Feature(ee.Geometry.Point(10, 20), {"old": 1, "null": None})
    assert compile_sdk(ee, feature.geometry()) == {"type": "Point", "coordinates": [10, 20]}
    assert compile_sdk(ee, feature.geometry(proj=ee.Projection("EPSG:4326"), geodesics=False)) == {
        "type": "Point", "coordinates": [10, 20]
    }
    updated = compile_sdk(ee, feature.set("new", [1, None]).setMulti({"old": 2}))
    assert updated == {
        "type": "Feature", "geometry": {"type": "Point", "coordinates": [10, 20]},
        "properties": {"old": 2, "null": None, "new": [1, None]},
    }
    assert set(compile_sdk(ee, feature.propertyNames())) == {"old", "null"}
    assert compile_sdk(ee, ee.Feature(None, {}).geometry()) is None


@pytest.mark.parametrize("kwargs, message", [
    ({"proj": "EPSG:3857"}, "EPSG:4326"),
])
def test_feature_geometry_rejects_unimplemented_projection_options(ee_sdk, kwargs, message):
    ee = ee_sdk
    feature = ee.Feature(ee.Geometry.Point(0, 0))
    with pytest.raises(UnsupportedEEError, match=message):
        compile_sdk(ee, feature.geometry(**kwargs))


def test_feature_geometry_rejects_nonnull_max_error_value(ee_sdk):
    ee = ee_sdk
    feature = ee.Feature(ee.Geometry.Point(0, 0))
    expression = ee.serializer.encode(feature.geometry(maxError=ee.ErrorMargin(1)), for_cloud_api=False)
    # ErrorMargin itself is outside this inline compatibility slice. Replace
    # the wrapper value with a decoded scalar to exercise Feature.geometry's
    # explicit handling of a non-null reprojection tolerance.
    expression["scope"] = [
        (key, 1 if isinstance(value, dict) and value.get("functionName") == "ErrorMargin" else value)
        for key, value in expression["scope"]
    ]
    with pytest.raises(UnsupportedEEError, match="maxError reprojection"):
        compile_expression(expression, [], {})


def test_inline_feature_collection_caps_and_public_output_budget(ee_sdk):
    ee = ee_sdk
    too_many = ee.FeatureCollection([ee.Feature(None, {"id": i}) for i in range(1001)])
    with pytest.raises(UnsupportedEEError, match="at most 1000 features"):
        compile_sdk(ee, too_many.size())

    repeated = ee.Feature(None, {"payload": "x" * 1200})
    large_output = ee.FeatureCollection([repeated] * 1000).map(lambda feature: feature)
    with pytest.raises(UnsupportedEEError, match="Computed value exceeds 1 MB"):
        compile_sdk(ee, large_output)

