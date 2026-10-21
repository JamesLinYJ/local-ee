"""Bounded per-item metadata map contracts from the pinned official SDK."""
import json
from pathlib import Path

import numpy as np
import pytest

from gee.ee_metadata import (
    _contains_mapped_metadata_read,
    _flows_from_argument,
    evaluate_per_image_map,
    requires_item_metadata,
)
from gee.ee_translate import Filter, Function, ImageSequence, Translator, UnsupportedEEError, compile_expression
from test_ee_translate import evaluate_graph


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "ee-metadata-1.7.49.json").read_text())
SDK = FIXTURE["expressions"]


def test_collection_map_drop_nulls_does_not_coerce_arbitrary_values():
    with pytest.raises(UnsupportedEEError, match='dropNulls must be a boolean'):
        Translator([], {}, None).invoke('Collection.map', {'dropNulls': 'false'})


def rect(w=0, s=0, e=2, n=2):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


@pytest.fixture
def local():
    names = ["blue", "green", "red", "nir", "SCL"]
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": names}}}]
    # Items a and b are distinct observations on the same day. Item identity
    # and source order must survive even when their timestamps are adjacent.
    items = {"sentinel-2-l2a": [
        {"id": "a", "bbox": [0, 0, 2, 2], "geometry": rect(), "properties": {
            "system:time_start": 1000, "system:index": "a", "CLOUDY_PIXEL_PERCENTAGE": 20}},
        {"id": "b", "bbox": [0, 0, 2, 2], "geometry": rect(), "properties": {
            "system:time_start": 1001, "system:index": "b", "CLOUDY_PIXEL_PERCENTAGE": 5}},
        {"id": "c", "bbox": [0, 0, 2, 2], "geometry": rect(), "properties": {
            "system:time_start": 86402000, "system:index": "c", "CLOUDY_PIXEL_PERCENTAGE": 90}},
    ]}
    return catalog, items


def resolve(value, scope):
    seen = set()
    while isinstance(value, dict) and value.get("type") == "ValueRef":
        key = value.get("value")
        if key in seen or key not in scope:
            raise AssertionError(f"unresolved or cyclic ValueRef: {key}")
        seen.add(key)
        value = scope[key]
    return value


def walk(value):
    if isinstance(value, list):
        for item in value:
            yield from walk(item)
    elif isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)


def callback(name):
    expression = SDK[name]
    scope = dict(expression["scope"])
    maps = [node for node in scope.values() for node in walk(node)
            if isinstance(node, dict) and node.get("type") == "Invocation"
            and node.get("functionName") == "Collection.map"]
    assert len(maps) == 1
    function = resolve(maps[0]["arguments"]["baseAlgorithm"], scope)
    assert function["type"] == "Function"
    return Function(function["argumentNames"], function["body"], {}), scope


def translator(local, scope):
    t = Translator(*local, options=None)
    t.scope.update(scope)
    return t


@pytest.mark.parametrize("name", [
    "mappedIndex", "mappedDateMillis", "mappedDateYear",
    "mappedGeometry", "mappedPropertyNames", "mappedPixelAndProperties", "mappedDropNulls",
])
def test_official_sdk_serializes_item_metadata_access(name):
    function, scope = callback(name)
    assert requires_item_metadata(function, scope)


def test_captured_image_property_read_stays_static():
    function, scope = callback("capturedStaticMetadata")
    assert not requires_item_metadata(function, scope)


@pytest.mark.parametrize(("name", "property_name", "expected"), [
    ("mappedIndex", "mapped:index", ["a", "b", "c"]),
    ("mappedDateMillis", "mapped:time", [1000.0, 1001.0, 86402000.0]),
    ("mappedDateYear", "mapped:year", [1970, 1970, 1970]),
])
def test_dynamic_get_date_set_values_are_per_item(local, name, property_name, expected):
    function, scope = callback(name)
    t = translator(local, scope)
    result = evaluate_per_image_map(t, t.load("sentinel-2-l2a"), function)
    assert isinstance(result, ImageSequence)
    assert [image.props[property_name] for image in result.images] == expected
    assert [image.source.ids for image in result.images] == [("a",), ("b",), ("c",)]


def test_property_names_and_captured_values_keep_ee_item_scope(local):
    function, scope = callback("mappedPropertyNames")
    t = translator(local, scope)
    result = evaluate_per_image_map(t, t.load("sentinel-2-l2a"), function)
    expected = ["system:time_start", "system:index", "CLOUDY_PIXEL_PERCENTAGE"]
    assert [image.props["mapped:properties"] for image in result.images] == [expected] * 3

    captured, captured_scope = callback("capturedStaticMetadata")
    assert not requires_item_metadata(captured, captured_scope)
    t = translator(local, captured_scope)
    result = evaluate_per_image_map(t, t.load("sentinel-2-l2a"), captured)
    assert [image.props["captured"] for image in result.images] == ["a", "a", "a"]


def test_item_geometry_is_resolved_from_each_frame(local):
    from shapely.geometry import shape

    function, scope = callback("mappedGeometry")
    t = translator(local, scope)
    result = evaluate_per_image_map(t, t.load("sentinel-2-l2a"), function)
    assert all(shape(image.props["mapped:geometry"]).equals(shape(rect())) for image in result.images)


def test_normal_pixel_callback_keeps_each_same_day_observation(local):
    function, scope = callback("mappedPixelAndProperties")
    t = translator(local, scope)
    result = evaluate_per_image_map(t, t.load("sentinel-2-l2a"), function)
    assert [image.source.ids for image in result.images] == [("a",), ("b",), ("c",)]
    assert [image.props["system:index"] for image in result.images] == ["a", "b", "c"]
    assert [image.props["mapped:index"] for image in result.images] == ["a", "b", "c"]
    assert [image.props["system:time_start"] for image in result.images] == [1000, 1001, 86402000]
    assert all([name for name, _ in image.bands] == ["nd"] for image in result.images)
    # The native map adapter preserves the source Pixel DAG, not a scalar or a
    # fabricated constant raster, so downstream graph compilation remains
    # responsible for resolving the actual source bands and their masks.
    assert all(pixel.op == "if" for image in result.images for _, pixel in image.bands)


def test_drop_nulls_and_sort_preserve_item_identity(local):
    function, scope = callback("mappedDropNulls")
    t = translator(local, scope)
    result = evaluate_per_image_map(t, t.load("sentinel-2-l2a"), function, drop_nulls=True)
    assert [image.props["system:index"] for image in result.images] == ["c"]

    function, scope = callback("mappedIndex")
    t = translator(local, scope)
    result = evaluate_per_image_map(t, t.load("sentinel-2-l2a"), function)
    ordered = t.invoke("Collection.sort", {"collection": result, "key": "CLOUDY_PIXEL_PERCENTAGE", "ascending": True})
    assert [image.props["system:index"] for image in ordered.images] == ["b", "a", "c"]
    same_day = t.invoke("Collection.filter", {"collection": result, "filter": Filter(
        "dateRangeContains", {"rightField": "system:time_start", "leftValue": (1000, 1002)})})
    assert [image.props["system:index"] for image in same_day.images] == ["a", "b"]


def test_metadata_adapter_propagates_real_unsupported_semantics(local):
    argument = {"type": "ArgumentRef", "value": "image"}
    body = {"type": "Invocation", "functionName": "Image.unknownNeighborhood", "arguments": {
        "input": {"type": "Invocation", "functionName": "Element.get", "arguments": {
            "object": argument, "property": "system:index"}}}}
    function = Function(["image"], body, {})
    assert requires_item_metadata(function)
    t = translator(local, {})
    with pytest.raises(UnsupportedEEError, match="Unsupported Earth Engine algorithm"):
        evaluate_per_image_map(t, t.load("sentinel-2-l2a"), function)


def test_metadata_adapter_enforces_finite_frame_limit(local):
    catalog, items = local
    original = items["sentinel-2-l2a"][0]
    items["sentinel-2-l2a"] = [dict(original, id=f"i{index}") for index in range(1001)]
    t = Translator(catalog, items, options=None)
    image = {"type": "ArgumentRef", "value": "image"}
    function = Function(["image"], {"type": "Invocation", "functionName": "Element.get", "arguments": {
        "object": image, "property": "system:index"}}, {})
    with pytest.raises(UnsupportedEEError, match="1000 frames"):
        evaluate_per_image_map(t, t.load("sentinel-2-l2a"), function)


@pytest.mark.parametrize(("name", "expected"), [
    ("mappedIndex", ["a", "b", "c"]),
    ("mappedMissingProperty", [None, None, None]),
    ("mappedDateMillis", [1000.0, 1001.0, 86402000.0]),
    ("mappedDateYear", [1970, 1970, 1970]),
    ("mappedPropertyNames", [["system:time_start", "system:index", "CLOUDY_PIXEL_PERCENTAGE"]] * 3),
    ("mappedDropNulls", ["c"]),
    ("nestedListMapShadow", [["a"], ["a"], ["a"]]),
    ("capturedStaticMetadata", ["a", "a", "a"]),
])
def test_official_sdk_metadata_fixtures_compile_to_expected_values(local, name, expected):
    result = compile_expression(SDK[name], *local)
    assert result == {"kind": "value", "value": expected, "warnings": []}


def test_official_sdk_geometry_fixture_compiles_to_expected_values(local):
    from shapely.geometry import shape

    result = compile_expression(SDK["mappedGeometry"], *local)
    assert result["kind"] == "value"
    assert len(result["value"]) == 3
    assert all(shape(geometry).equals(shape(rect())) for geometry in result["value"])


def test_official_sdk_pixel_fixture_compiles_to_ordered_graph_and_values(local):
    result = compile_expression(SDK["mappedPixelAndProperties"], *local)
    assert result["kind"] == "image"
    assert result["bands"] == ["nd"]
    assert result["source_item_ids"] == ["a", "b", "c"]
    scene_loads = [node["arguments"] for node in result["process_graph"].values()
                   if node["process_id"] == "load_collection"]
    assert [node["_gee_item_ids"] for node in scene_loads] == [["a"], ["b"], ["c"]]

    arrays = {
        "a": {"red": np.array([1.0, 2.0]), "nir": np.array([4.0, 5.0])},
        "b": {"red": np.array([2.0, 2.0]), "nir": np.array([6.0, 8.0])},
        "c": {"red": np.array([4.0, 4.0]), "nir": np.array([8.0, 12.0])},
    }
    raster, labels, timed = evaluate_graph(result, arrays)
    assert labels == ["nd"] and not timed
    # Independent per-scene normalized-difference values averaged over a/b/c.
    np.testing.assert_allclose(raster, [[0.4777777778, 0.5095238095]], rtol=1e-8, atol=1e-8)


def invocation(name, **arguments):
    return {"type": "Invocation", "functionName": name, "arguments": arguments}


def argument(name):
    return {"type": "ArgumentRef", "value": name}


@pytest.mark.parametrize("cast", ["Image.toFloat", "Image.toDouble"])
@pytest.mark.parametrize(("read", "property_name", "expected"), [
    ("get", "mapped:index", ["a", "b", "c"]),
    ("date", "mapped:time", [1000.0, 1001.0, 86402000.0]),
])
def test_compile_map_metadata_read_through_numeric_cast(local, cast, read, property_name, expected):
    image = argument("image")
    cast_image = invocation(cast, value=image)
    if read == "get":
        value = invocation("Element.get", object=invocation(cast, value=argument("image")),
            property="system:index")
    else:
        value = invocation("Date.millis", date=invocation("Image.date",
            image=invocation(cast, value=argument("image"))))
    body = invocation("Element.set", object=cast_image, key=property_name, value=value)
    expression = invocation("AggregateFeatureCollection.array", collection=invocation("Collection.map",
        collection=invocation("ImageCollection.load", id="sentinel-2-l2a"),
        baseAlgorithm={"type": "Function", "argumentNames": ["image"], "body": body}),
        property=property_name)

    result = compile_expression(expression, *local)
    assert result == {"kind": "value", "value": expected, "warnings": []}


def test_same_value_ref_name_in_distinct_lexical_scopes_keeps_memo_identity():
    ref = {"type": "ValueRef", "value": "same"}
    def compound(binding):
        return {"type": "CompoundValue", "scope": [["same", binding]], "value": ref}

    flow_memo = {}
    assert _flows_from_argument(compound(invocation("Image.toDouble", value=argument("image"))),
        "image", {}, memo=flow_memo)
    assert not _flows_from_argument(compound(invocation("Image.toDouble", value=argument("captured"))),
        "image", {}, memo=flow_memo)
    flow_scopes = [scope for scope, _ in flow_memo.values()]
    assert len(flow_scopes) == 2 and flow_scopes[0] is not flow_scopes[1]
    assert all(scope["same"] for scope in flow_scopes)

    read_memo = {}
    assert _contains_mapped_metadata_read(compound(invocation("Element.get", object=argument("image"),
        property="system:index")), "image", {}, memo=read_memo)
    assert not _contains_mapped_metadata_read(compound(invocation("Element.get", object=argument("captured"),
        property="system:index")), "image", {}, memo=read_memo)
    read_scopes = [scope for scope, _ in read_memo.values()]
    assert len(read_scopes) == 2 and read_scopes[0] is not read_scopes[1]
    assert all(scope["same"] for scope in read_scopes)


def test_nested_list_map_argument_shadowing_and_outer_capture_compile(local):
    collection = invocation("ImageCollection.load", id="sentinel-2-l2a")
    first_image = invocation("Image", value=invocation("Collection.first", collection=collection))
    inner_shadow = {"type": "Function", "argumentNames": ["image"], "body": invocation(
        "Element.get", object=argument("image"), property="system:index")}
    shadowed_body = invocation("Element.set", object=argument("image"), key="nested:static",
        value=invocation("List.map", list=[first_image], baseAlgorithm=inner_shadow))
    shadowed = Function(["image"], shadowed_body, {})
    assert not requires_item_metadata(shadowed)

    shadowed_expr = invocation("AggregateFeatureCollection.array", collection=invocation("Collection.map",
        collection=collection, baseAlgorithm={"type": "Function", "argumentNames": ["image"],
        "body": shadowed_body}), property="nested:static")
    assert compile_expression(shadowed_expr, *local)["value"] == [["a"], ["a"], ["a"]]

    # A nested callback with a different parameter may close over the outer map
    # image. It must trigger frame evaluation, otherwise the generic mapped
    # placeholder cannot resolve system:index for a/b/c independently.
    inner_capture = {"type": "Function", "argumentNames": ["item"], "body": invocation(
        "Element.get", object=argument("image"), property="system:index")}
    capture_body = invocation("Element.set", object=argument("image"), key="nested:dynamic",
        value=invocation("List.map", list=["unused"], baseAlgorithm=inner_capture))
    capture = Function(["image"], capture_body, {})
    assert requires_item_metadata(capture)
    capture_expr = invocation("AggregateFeatureCollection.array", collection=invocation("Collection.map",
        collection=collection, baseAlgorithm={"type": "Function", "argumentNames": ["image"],
        "body": capture_body}), property="nested:dynamic")
    assert compile_expression(capture_expr, *local)["value"] == [["a"], ["b"], ["c"]]


def test_shared_value_ref_dag_analysis_is_bounded_and_compile_budgeted(local):
    scope = [["collection", invocation("ImageCollection.load", id="sentinel-2-l2a")], ["n0", 1]]
    for level in range(1, 42):
        previous = {"type": "ValueRef", "value": f"n{level - 1}"}
        scope.append([f"n{level}", invocation("Number.add", left=previous, right=previous)])
    body = invocation("Element.set", object=argument("image"), key="shared:value",
        value={"type": "ValueRef", "value": "n41"})
    function = {"type": "Function", "argumentNames": ["image"], "body": body}
    scope.append(["callback", function])
    expression = {"type": "CompoundValue", "scope": scope, "value": invocation("Collection.map",
        collection={"type": "ValueRef", "value": "collection"},
        baseAlgorithm={"type": "ValueRef", "value": "callback"})}

    assert not requires_item_metadata(Function(["image"], body, {}), dict(scope))
    # The detector walks the shared DAG once; normal evaluation still applies
    # its explicit graph-step budget instead of expanding the DAG unboundedly.
    with pytest.raises(UnsupportedEEError, match="Earth Engine graph exceeds compilation limits"):
        compile_expression(expression, *local)


def test_compile_does_not_fallback_after_unsupported_mapped_operation(local):
    image = argument("image")
    dynamic = invocation("Element.get", object=image, property="system:index")
    body = invocation("Image.unknownNeighborhood", input=dynamic)
    expression = invocation("Collection.map", collection=invocation("ImageCollection.load", id="sentinel-2-l2a"),
        baseAlgorithm={"type": "Function", "argumentNames": ["image"], "body": body})
    with pytest.raises(UnsupportedEEError, match="Unsupported Earth Engine algorithm: Image.unknownNeighborhood"):
        compile_expression(expression, *local)


def test_scalar_return_from_metadata_map_is_not_a_computable_collection(local):
    body = invocation("Element.get", object=argument("image"), property="system:index")
    expression = invocation("Collection.map", collection=invocation("ImageCollection.load", id="sentinel-2-l2a"),
        baseAlgorithm={"type": "Function", "argumentNames": ["image"], "body": body})
    with pytest.raises(UnsupportedEEError, match="ImageCollection.map must return an Image"):
        compile_expression(expression, *local)
