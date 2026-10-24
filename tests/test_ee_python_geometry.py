"""Pinned Python geometry serialization and bounded spherical/planar contracts."""
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
    planar = {**raw, "geodesic": False}
    assert compile_sdk(sdk, constructed)["value"] == result["value"] == planar
    assert shape(result["value"]).area == 1
    assert raw == before


def test_python_default_and_explicit_spherical_geometry_preserve_sdk_wire_flags(sdk):
    raw = {"type": "Polygon", "coordinates": rectangle()["coordinates"]}
    omitted = sdk.Geometry(raw)
    numeric = sdk.Geometry.Polygon([[[0, 0], [2, 0], [2, 2], [0, 2]]])
    explicit = sdk.Geometry(raw, proj="EPSG:4326", geodesic=True)

    omitted_wire = sdk.serializer.encode(omitted, for_cloud_api=False)
    numeric_wire = sdk.serializer.encode(numeric, for_cloud_api=False)
    explicit_wire = sdk.serializer.encode(explicit, for_cloud_api=False)
    assert "geodesic" not in omitted_wire and "evenOdd" not in omitted_wire
    assert "geodesic" not in numeric_wire and numeric_wire["evenOdd"] is True
    assert explicit_wire["geodesic"] is True
    assert explicit_wire["crs"]["properties"]["name"] == "EPSG:4326"

    omitted_value = compile_sdk(sdk, omitted)["value"]
    numeric_value = compile_sdk(sdk, numeric)["value"]
    explicit_value = compile_sdk(sdk, explicit)["value"]
    assert "geodesic" not in omitted_value and "evenOdd" not in omitted_value
    assert "geodesic" not in numeric_value and numeric_value["evenOdd"] is True
    assert explicit_value["geodesic"] is True


def test_python_geojson_preserves_filter_clip_reduction_and_table_geometry(sdk, catalogue):
    roi = sdk.Geometry(rectangle(.5, .5, 1.5, 1.5), proj="EPSG:4326", geodesic=False)
    planar_roi = {**rectangle(.5, .5, 1.5, 1.5), "geodesic": False}
    collection = sdk.ImageCollection("sentinel-2-l2a")
    filtered = compile_sdk(sdk, collection.filterBounds(roi), catalogue)
    assert filtered["source_item_ids"] == ["near"]
    clipped = compile_sdk(sdk, collection.first().clip(roi), catalogue)
    assert clipped["kind"] == "image" and clipped["bands"] == ["red"]
    geometry_arguments = [node["arguments"] for node in clipped["process_graph"].values()
                          if node["process_id"] == "mask_polygon"]
    assert geometry_arguments and geometry_arguments[0]["mask"] == planar_roi
    reduced = compile_sdk(sdk, collection.first().reduceRegion(sdk.Reducer.mean(), roi), catalogue)
    assert reduced["kind"] == "region"
    assert reduced["geometry"] == planar_roi
    table = compile_sdk(sdk, sdk.FeatureCollection([sdk.Feature(roi, {"mean": 3})]), catalogue)
    assert table["value"]["features"] == [
        {"type": "Feature", "geometry": planar_roi, "properties": {"mean": 3}}
    ]


@pytest.mark.parametrize("options, message", [
    ({"proj": "EPSG:3857", "geodesic": False}, "EPSG:4326"),
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
    ({"type": "LineString", "coordinates": [[0, 0]]}, "non-empty line requires at least two positions"),
    ({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1]]]}, "crosses edge"),
    ({"type": "Polygon", "geodesic": False,
      "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1]]]}, "topology"),
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
    spherical = compile_expression(
        {"type": "GeometryCollection", "geometries": [{**child, "geodesic": True}]}, [], {},
    )
    assert spherical["value"]["geometries"][0]["geodesic"] is True
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
