"""Focused controls for bounded inline FeatureCollection CSV values."""

from __future__ import annotations

import copy
import csv
import json

import pytest

from gee import table_values
from gee.table_values import (
    MAX_CELLS,
    MAX_COLUMNS,
    MAX_DEPTH,
    MAX_JSON_BYTES,
    MAX_ROWS,
    TableValueError,
    columns,
    render_csv,
)


def feature(properties=None, *, geometry=None, feature_id=None):
    item = {"type": "Feature", "geometry": geometry, "properties": properties}
    if feature_id is not None:
        item["id"] = feature_id
    return item


def collection(features):
    return {"type": "FeatureCollection", "features": features}


def input_bytes(data):
    return len(json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def test_default_columns_and_csv_preserve_order_values_and_csv_special_characters():
    data = collection([
        feature(
            {
                "first": '雪, "quoted"\nline',
                "flag": True,
                "nothing": None,
                "nested": {"z": [1, None], "a": "保留"},
            },
            geometry={"type": "Point", "coordinates": [120.5, 30]},
            feature_id="row-1",
        ),
        feature({"second": False, "first": None}, geometry=None, feature_id=7),
    ])
    original = copy.deepcopy(data)

    assert columns(data) == [
        "system:index", "first", "flag", "nothing", "nested", "second", ".geo",
    ]
    rendered = render_csv(data)
    assert rendered.startswith("system:index,first,flag,nothing,nested,second,.geo\r\n")
    assert '雪, "quoted"\nline' not in rendered  # CSV quotes and escapes the field.
    rows = list(csv.reader(rendered.splitlines(keepends=True)))
    assert rows[1] == [
        "row-1", '雪, "quoted"\nline', "true", "", '{"z":[1,null],"a":"保留"}', "",
        '{"type":"Point","coordinates":[120.5,30]}',
    ]
    assert rows[2] == ["7", "", "", "", "", "false", ""]
    assert data == original


def test_property_system_index_takes_precedence_and_missing_values_are_empty():
    data = collection([
        feature({"system:index": "from-property"}, feature_id="from-id"),
        feature({"system:index": None}, feature_id="must-not-fallback"),
        feature({}, feature_id=None),
    ])
    assert list(csv.reader(render_csv(data).splitlines())) == [
        ["system:index", ".geo"],
        ["from-property", ""],
        ["", ""],
        ["", ""],
    ]


def test_empty_collection_keeps_both_reserved_columns():
    data = collection([])
    assert columns(data) == ["system:index", ".geo"]
    assert render_csv(data) == "system:index,.geo\r\n"


def test_selectors_keep_user_order_and_allow_both_reserved_columns():
    data = collection([feature({"x": 3, "y": "comma,value"}, feature_id=12)])
    assert render_csv(data, [".geo", "y", "system:index", "x"]) == (
        '.geo,y,system:index,x\r\n,"comma,value",12,3\r\n'
    )


@pytest.mark.parametrize("selectors", [[], (), ["x", "x"], ["unknown"], ["x", 1]])
def test_selectors_must_be_a_nonempty_unique_list_of_known_string_columns(selectors):
    with pytest.raises(TableValueError, match="selector|Unknown"):
        render_csv(collection([feature({"x": 1})]), selectors)


def test_bad_unselected_property_is_rejected_and_data_like_keys_are_not_executed():
    with pytest.raises(TableValueError, match="finite"):
        render_csv(collection([feature({"chosen": 1, "bad": float("nan")})]), ["chosen"])

    data = collection([feature({
        "process_id": "do-not-run-this",
        "from_node": {"process_id": "arbitrary data", "value": "__import__('os')"},
    })])
    assert columns(data) == ["system:index", "process_id", "from_node", ".geo"]
    assert "__import__('os')" in render_csv(data)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_json_numbers_are_rejected_even_when_nested(bad):
    data = collection([feature({"nested": {"list": [1, bad]}})])
    with pytest.raises(TableValueError, match="finite"):
        columns(data)


@pytest.mark.parametrize("value", [(1, 2), object(), {1: "not JSON"}])
def test_non_json_python_values_are_rejected(value):
    with pytest.raises(TableValueError, match="JSON"):
        columns(collection([feature({"x": value})]))


def test_metadata_depth_limit_accepts_boundary_and_rejects_one_level_beyond():
    allowed_nesting = MAX_DEPTH - 4  # root, features, feature, properties containers.
    value = "leaf"
    for _ in range(allowed_nesting):
        value = [value]
    columns(collection([feature({"deep": value})]))

    too_deep = [value]
    with pytest.raises(TableValueError, match="depth"):
        columns(collection([feature({"deep": too_deep})]))


def test_attribute_name_length_and_nul_boundary():
    columns(collection([feature({"a" * 256: 1})]))
    with pytest.raises(TableValueError, match="Attribute names"):
        columns(collection([feature({"a" * 257: 1})]))
    with pytest.raises(TableValueError, match="Attribute names"):
        columns(collection([feature({"bad\x00name": 1})]))


def test_reserved_geo_property_is_rejected_instead_of_overwritten():
    with pytest.raises(TableValueError, match="conflicts"):
        render_csv(collection([feature({".geo": "property data"}, geometry=None)]))


@pytest.mark.parametrize("geometry", [
    {"type": "Point", "coordinates": [1, 2]},
    {"type": "MultiPoint", "coordinates": [[1, 2], [3, 4]]},
    {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
    {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]]},
    {"type": "MultiPolygon", "coordinates": [[[[0, 0], [2, 0], [2, 2], [0, 0]]]]},
    {"type": "GeometryCollection", "geometries": []},
    {"type": "GeometryCollection", "geometries": [
        {"type": "Point", "coordinates": [1, 2]},
    ]},
])
def test_valid_two_dimensional_wgs84_geojson_geometries_are_accepted(geometry):
    assert render_csv(collection([feature({}, geometry=geometry)])).count("\r\n") == 2


@pytest.mark.parametrize("geometry", [
    {"type": "Circle", "coordinates": [1, 2]},
    {"type": "Point", "coordinates": [1, 2, 3]},
    {"type": "Point", "coordinates": [181, 0]},
    {"type": "Point", "coordinates": [0, -91]},
    {"type": "Point", "coordinates": [float("nan"), 0]},
    {"type": "LineString", "coordinates": [[0, 0]]},
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]]},
    {"type": "Polygon", "coordinates": [[
        [0, 0], [2, 2], [0, 2], [2, 0], [0, 0],
    ]]},
])
def test_invalid_geometry_shape_dimension_range_ring_and_topology_are_rejected(geometry):
    with pytest.raises(TableValueError):
        columns(collection([feature({}, geometry=geometry)]))


def test_feature_collection_and_feature_structure_are_required():
    for data in ([], {"type": "FeatureCollection", "features": ()},
                 {"type": "FeatureCollection", "features": [None]},
                 collection([{"type": "Feature", "geometry": None}])):
        with pytest.raises(TableValueError):
            columns(data)


def test_row_limit_accepts_exactly_one_thousand_and_rejects_the_next_row():
    columns(collection([feature({}) for _ in range(MAX_ROWS)]))
    with pytest.raises(TableValueError, match="1000"):
        columns(collection([feature({}) for _ in range(MAX_ROWS + 1)]))


def test_column_limit_counts_reserved_columns():
    columns(collection([feature({f"f{i}": i for i in range(MAX_COLUMNS - 2)})]))
    with pytest.raises(TableValueError, match="256 columns"):
        columns(collection([feature({f"f{i}": i for i in range(MAX_COLUMNS - 1)})]))


def test_cell_limit_uses_default_column_count_even_when_selecting_one_column():
    props = {f"f{i}": i for i in range(48)}
    exact = collection([feature(props) for _ in range(MAX_ROWS)])
    assert len(columns(exact)) * MAX_ROWS == MAX_CELLS
    over = collection([feature({**props, "extra": 1}) for _ in range(MAX_ROWS)])
    with pytest.raises(TableValueError, match="50000"):
        render_csv(over, ["f0"])


def test_json_input_byte_cap_counts_utf8_and_accepts_the_exact_boundary():
    data = collection([feature({"blob": ""})])
    base = input_bytes(data)
    data["features"][0]["properties"]["blob"] = "雪" * ((MAX_JSON_BYTES - base + 2) // 3)
    # Adjust by Unicode code point until the serialized byte count is exact.
    blob = data["features"][0]["properties"]["blob"]
    while input_bytes(data) > MAX_JSON_BYTES:
        blob = blob[:-1]
        data["features"][0]["properties"]["blob"] = blob
    while input_bytes(data) < MAX_JSON_BYTES:
        blob += "x"
        data["features"][0]["properties"]["blob"] = blob
    assert input_bytes(data) == MAX_JSON_BYTES
    columns(data)

    data["features"][0]["properties"]["blob"] += "x"
    with pytest.raises(TableValueError, match="JSON input exceeds"):
        columns(data)


def test_csv_output_byte_cap_uses_utf8_byte_count(monkeypatch):
    data = collection([feature({"x": "中文"})])
    actual_bytes = len(render_csv(data).encode("utf-8"))
    monkeypatch.setattr(table_values, "MAX_CSV_BYTES", actual_bytes)
    assert len(render_csv(data).encode("utf-8")) == actual_bytes
    monkeypatch.setattr(table_values, "MAX_CSV_BYTES", actual_bytes - 1)
    with pytest.raises(TableValueError, match="CSV output exceeds"):
        render_csv(data)


def test_named_epsg_4326_crs_and_planar_geometry_flags_are_preserved():
    crs = {"type": "name", "properties": {"name": "EPSG:4326"}}
    geometry = {
        "type": "Point", "coordinates": [100, 30], "crs": crs,
        "geodesic": False, "evenOdd": True,
    }
    data = collection([feature({}, geometry=geometry)])
    data["crs"] = crs
    data["features"][0]["crs"] = crs
    original = copy.deepcopy(data)

    row = list(csv.reader(render_csv(data).splitlines()))[1]
    assert row == [
        "",
        json.dumps(geometry, ensure_ascii=False, separators=(",", ":")),
    ]
    assert data == original


def test_null_crs_is_accepted_at_all_geojson_levels():
    geometry = {"type": "Point", "coordinates": [1, 2], "crs": None}
    item = feature({}, geometry=geometry)
    item["crs"] = None
    data = collection([item])
    data["crs"] = None
    columns(data)


@pytest.mark.parametrize("layer", ["collection", "feature", "geometry", "nested geometry"])
def test_non_wgs84_crs_is_rejected_at_each_geojson_layer(layer):
    data = collection([feature({}, geometry={"type": "Point", "coordinates": [100, 30]})])
    projected = {"type": "name", "properties": {"name": "EPSG:3857"}}
    if layer == "collection":
        data["crs"] = projected
    elif layer == "feature":
        data["features"][0]["crs"] = projected
    elif layer == "geometry":
        data["features"][0]["geometry"]["crs"] = projected
    else:
        data["features"][0]["geometry"] = {
            "type": "GeometryCollection",
            "geometries": [{
                "type": "Point", "coordinates": [100, 30], "crs": projected,
            }],
        }
    with pytest.raises(TableValueError, match="EPSG:4326|crs"):
        columns(data)


@pytest.mark.parametrize("bad_crs", [
    "EPSG:4326",
    {},
    {"type": "link", "properties": {"href": "local-file.geojson"}},
    {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3857"}},
])
def test_malformed_or_non_epsg4326_crs_is_rejected(bad_crs):
    data = collection([feature({}, geometry={"type": "Point", "coordinates": [1, 2]})])
    data["crs"] = bad_crs
    with pytest.raises(TableValueError, match="crs|EPSG:4326"):
        render_csv(data)


@pytest.mark.parametrize("geometry", [
    {"type": "Point", "coordinates": [1, 2], "geodesic": True},
    {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]],
     "evenOdd": False},
    {"type": "Point", "coordinates": [1, 2], "geodesic": "true"},
    {"type": "GeometryCollection", "geometries": [
        {"type": "Point", "coordinates": [1, 2], "evenOdd": False},
    ]},
])
def test_unsupported_ee_geometry_semantics_are_rejected(geometry):
    with pytest.raises(TableValueError, match="geodesic|evenOdd"):
        columns(collection([feature({}, geometry=geometry)]))


def test_crs_and_geometry_flag_keys_inside_properties_remain_ordinary_data():
    properties = {
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        "geodesic": True,
        "evenOdd": False,
    }
    data = collection([feature(properties, geometry={"type": "Point", "coordinates": [1, 2]})])
    assert columns(data) == ["system:index", "crs", "geodesic", "evenOdd", ".geo"]
    assert list(csv.reader(render_csv(data).splitlines()))[1][1:4] == [
        '{"type":"name","properties":{"name":"EPSG:3857"}}', "true", "false",
    ]


def test_geometry_feature_and_collection_bboxes_accept_exact_bounds_and_preserve_json():
    geometry = {
        "type": "Point", "coordinates": [100, 30], "bbox": [100, 30, 100, 30],
    }
    data = collection([feature({}, geometry=geometry)])
    data["features"][0]["bbox"] = [100, 30, 100, 30]
    data["bbox"] = [100, 30, 100, 30]
    rendered = render_csv(data)
    assert list(csv.reader(rendered.splitlines()))[1][1] == json.dumps(
        geometry, ensure_ascii=False, separators=(",", ":"),
    )
    assert data["bbox"] == [100, 30, 100, 30]


@pytest.mark.parametrize("layer", ["geometry", "feature", "collection"])
def test_bbox_must_enclose_nonempty_geometry_at_its_own_geojson_layer(layer):
    data = collection([feature({}, geometry={"type": "Point", "coordinates": [100, 30]})])
    if layer == "geometry":
        data["features"][0]["geometry"]["bbox"] = [99, 31, 100, 31]
    elif layer == "feature":
        data["features"][0]["bbox"] = [99, 31, 100, 31]
    else:
        data["bbox"] = [100, 31, 100, 31]
    with pytest.raises(TableValueError, match="enclose"):
        columns(data)


def test_collection_bbox_must_cover_every_nonempty_feature_geometry():
    data = collection([
        feature({}, geometry={"type": "Point", "coordinates": [100, 30]}),
        feature({}, geometry={"type": "Point", "coordinates": [120, 10]}),
    ])
    data["bbox"] = [100, 10, 120, 30]
    columns(data)
    data["bbox"] = [100, 10, 119, 30]
    with pytest.raises(TableValueError, match="enclose"):
        render_csv(data)


def test_bbox_rejects_antimeridian_crossing_and_empty_collections_allow_bbox():
    crossing = collection([])
    crossing["bbox"] = [170, -10, -170, 10]
    with pytest.raises(TableValueError, match="ordered"):
        columns(crossing)

    empty = collection([])
    empty["bbox"] = [-180, -90, 180, 90]
    assert columns(empty) == ["system:index", ".geo"]
    assert render_csv(empty) == "system:index,.geo\r\n"

    empty_geometry = {"type": "GeometryCollection", "geometries": [], "bbox": [0, 0, 1, 1]}
    assert columns(collection([feature({}, geometry=empty_geometry)]))[-1] == ".geo"

    huge = collection([])
    huge["bbox"] = [0, 0, 10**400, 1]
    with pytest.raises(TableValueError, match="WGS84"):
        columns(huge)
