"""Pinned Python geometry serialization and bounded planar decode contracts."""
import copy

import pytest
from shapely.geometry import shape

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


def rectangle(west=0, south=0, east=2, north=2):
    return {"type": "Polygon", "coordinates": [
        [[west, south], [east, south], [east, north], [west, north], [west, south]]
    ]}


@pytest.fixture
def sdk():
    import ee
    configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                       signatures_path="vendor/earthengine-js/algorithms.json")
    return ee


@pytest.fixture
def catalogue():
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["red"]}}}]
    items = {"sentinel-2-l2a": [
        {"id": name, "bbox": [west, 0, west + 2, 2], "geometry": rectangle(west, 0, west + 2, 2),
         "properties": {"system:index": name, "system:time_start": time}}
        for name, west, time in [("near", 0, 1000), ("far", 10, 2000)]
    ]}
    return catalog, items


def compile_sdk(ee, obj, catalogue=([], {})):
    expression = ee.serializer.encode(obj, for_cloud_api=False)
    return compile_expression(expression, *catalogue)


def test_python_named_geojson_crs_and_projection_constructor_are_equivalent(sdk):
    raw = rectangle(.5, .5, 1.5, 1.5)
    before = copy.deepcopy(raw)
    literal = sdk.Geometry(raw, proj="EPSG:4326", geodesic=False)
    encoded = sdk.serializer.encode(literal, for_cloud_api=False)
    assert encoded["crs"] == {"type": "name", "properties": {"name": "EPSG:4326"}}
    result = compile_sdk(sdk, literal)
    constructed = sdk.Geometry.Rectangle([.5, .5, 1.5, 1.5],
                                        proj=sdk.Projection("EPSG:4326"), geodesic=False)
    assert compile_sdk(sdk, constructed)["value"] == result["value"] == raw
    assert shape(result["value"]).area == 1
    assert raw == before


def test_python_geojson_preserves_filter_clip_reduction_and_table_geometry(sdk, catalogue):
    roi = sdk.Geometry(rectangle(.5, .5, 1.5, 1.5), proj="EPSG:4326", geodesic=False)
    collection = sdk.ImageCollection("sentinel-2-l2a")
    filtered = compile_sdk(sdk, collection.filterBounds(roi), catalogue)
    assert filtered["source_item_ids"] == ["near"]
    clipped = compile_sdk(sdk, collection.first().clip(roi), catalogue)
    assert clipped["kind"] == "image" and clipped["bands"] == ["red"]
    geometry_arguments = [node["arguments"] for node in clipped["process_graph"].values()
                          if node["process_id"] == "mask_polygon"]
    assert geometry_arguments and geometry_arguments[0]["mask"] == rectangle(.5, .5, 1.5, 1.5)
    reduced = compile_sdk(sdk, collection.first().reduceRegion(sdk.Reducer.mean(), roi), catalogue)
    assert reduced["kind"] == "region"
    assert reduced["geometry"] == rectangle(.5, .5, 1.5, 1.5)
    table = compile_sdk(sdk, sdk.FeatureCollection([sdk.Feature(roi, {"mean": 3})]), catalogue)
    assert table["value"]["features"] == [
        {"type": "Feature", "geometry": rectangle(.5, .5, 1.5, 1.5), "properties": {"mean": 3}}
    ]


@pytest.mark.parametrize("options, message", [
    ({"proj": "EPSG:3857", "geodesic": False}, "EPSG:4326"),
    ({"proj": "EPSG:4326", "geodesic": True}, "spherical"),
    ({"proj": "EPSG:4326", "geodesic": False, "evenOdd": False}, "left-inside"),
])
def test_python_literal_geometry_rejects_unsupported_options(sdk, options, message):
    with pytest.raises(UnsupportedEEError, match=message):
        compile_sdk(sdk, sdk.Geometry(rectangle(), **options))


@pytest.mark.parametrize("crs", [
    {"type": "link", "properties": {"href": "https://example.org/crs"}},
    {"type": "name", "properties": {"name": "EPSG:4326", "transform": [1, 0, 0, 0, 1, 0]}},
    {"type": "name", "properties": {"name": "EPSG:3857"}},
    {"type": "name", "properties": {"name": None}},
    {"type": "name", "properties": {}},
    [],
])
def test_malformed_or_unsupported_named_crs_is_explicitly_rejected(crs):
    with pytest.raises(UnsupportedEEError, match="CRS|EPSG:4326"):
        compile_expression({**rectangle(), "crs": crs}, [], {})


@pytest.mark.parametrize("geometry, message", [
    ({"type": "Point", "coordinates": [0, float("inf")]}, "finite"),
    ({"type": "Point", "coordinates": [True, 0]}, "finite"),
    ({"type": "Point", "coordinates": [0, 0, 1]}, "two-dimensional"),
    ({"type": "Point", "coordinates": [0, 91]}, "bounds"),
    ({"type": "LineString", "coordinates": [[0, 0]]}, "Invalid planar"),
    ({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1]]]}, "topology"),
    ({**rectangle(), "geodesic": "false"}, "boolean"),
    ({**rectangle(), "evenOdd": "true"}, "boolean"),
    ({**rectangle(), "transform": [1, 0, 0, 0, 1, 0]}, "Unsupported GeoJSON"),
])
def test_geometry_rejects_invalid_coordinates_and_options(geometry, message):
    with pytest.raises(UnsupportedEEError, match=message):
        compile_expression(geometry, [], {})


def test_geometry_collection_recursively_checks_children_and_budget():
    child = {"type": "Point", "coordinates": [1, 2],
             "crs": {"type": "name", "properties": {"name": "EPSG:4326"}}}
    result = compile_expression({"type": "GeometryCollection", "geometries": [child]}, [], {})
    assert result["value"] == {"type": "GeometryCollection", "geometries": [
        {"type": "Point", "coordinates": [1, 2]}]}
    with pytest.raises(UnsupportedEEError, match="spherical"):
        compile_expression({"type": "GeometryCollection", "geometries": [{**child, "geodesic": True}]}, [], {})
    with pytest.raises(UnsupportedEEError, match="10000"):
        compile_expression({"type": "MultiPoint", "coordinates": [[0, 0]] * 10001}, [], {})


def test_constructor_does_not_ignore_interior_or_reprojection_options(sdk):
    constructor = {"type": "Invocation", "functionName": "GeometryConstructors.Polygon",
                   "arguments": {"coordinates": rectangle()["coordinates"], "geodesic": False}}
    for extra, message in [({"evenOdd": False}, "left-inside"), ({"maxError": 1}, "maxError")]:
        with pytest.raises(UnsupportedEEError, match=message):
            compile_expression({**constructor, "arguments": {**constructor["arguments"], **extra}}, [], {})
    raw = rectangle()
    raw["coordinates"][0].pop()
    assert compile_expression(raw, [], {})["value"] == rectangle()
    assert len(raw["coordinates"][0]) == 4
