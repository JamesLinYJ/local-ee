"""Component geometry transport retains fresh ownership and strict consumers."""
from copy import deepcopy

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_structure import invoke_feature_structure
from gee.compat.earthengine.feature_values import invoke_feature_value
from gee.compat.earthengine.geometry_binary import invoke_geometry_binary
from gee.compat.earthengine.geometry_components import (
    decode_component_geometry_bounded,
    own_component_geometry_bounded,
)
from gee.compat.earthengine.geometry_constructors import construct_geometry_value
from gee.compat.earthengine.geometry_consumers import own_feature_collection_geometries
from gee.compat.earthengine.geometry_preflight import measure_geometry
from gee.compat.earthengine.geometry_regions import own_ee_region
from gee.compat.earthengine.geometry_structure import invoke_geometry_structure
from gee.compat.earthengine.geometry_values import (
    GeometryValue,
    decode_geometry_bounded,
    own_geometry_bounded,
)
from gee.compat.earthengine.nested_collections import (
    construct_nested_collection,
    flatten_collection,
)
from gee.compat.earthengine.static_dictionary_ops import invoke_dictionary_extra
from gee.compat.earthengine.static_list_ops import invoke_list_extra
from gee.ee_translate import UnsupportedEEError


def translator(steps=0):
    value = Translator([], {}, {})
    value.steps = steps
    return value


def overlapping_geometry():
    return {"type": "MultiPolygon", "geodesic": False, "coordinates": [
        [[[0, 0], [4, 0], [4, 2], [0, 2], [0, 0]]],
        [[[2, 0], [6, 0], [6, 2], [2, 2], [2, 0]]],
    ]}


def feature(geometry):
    return {"type": "Feature", "id": "actual-id", "geometry": geometry,
            "properties": {"nested": {"values": [1, 2]}}}


def transfer(route, geometry):
    t = translator()
    if route == "literal":
        return t.evaluate(geometry)
    if route == "constructor":
        return construct_geometry_value(t, "MultiPolygon", {
            "coordinates": geometry["coordinates"], "geodesic": False,
        })
    if route == "own":
        return own_component_geometry_bounded(t, geometry)
    if route == "Feature.geometry":
        return invoke_feature_value(t, route, {"feature": feature(geometry)})
    if route == "Feature.setGeometry":
        result = invoke_feature_structure(t, route, {
            "feature": feature(None), "geometry": geometry,
        })
        return result["geometry"]
    if route == "Geometry.geometries":
        return invoke_geometry_structure(t, route, {"geometry": geometry})[0]
    if route == "List.getGeometry":
        return invoke_list_extra(t, route, {"list": [geometry], "index": 0})
    if route == "Dictionary.getGeometry":
        return invoke_dictionary_extra(t, route, {
            "dictionary": {"geometry": geometry}, "key": "geometry",
        })
    raise AssertionError(route)


ROUTES = ("literal", "constructor", "own", "Feature.geometry",
          "Feature.setGeometry", "Geometry.geometries", "List.getGeometry",
          "Dictionary.getGeometry")


@pytest.mark.parametrize("route", ROUTES)
def test_component_transfers_preserve_parts_and_detach_both_directions(route):
    source = overlapping_geometry()
    original = deepcopy(source)
    output = transfer(route, source)
    assert type(output) is GeometryValue
    assert output == original
    assert output.geometry_metadata == {
        "crs": "EPSG:4326", "geodesic": False, "evenOdd": True,
    }
    source["coordinates"][0][0][1][0] = 3
    assert output == original
    output["coordinates"][1][0][1][0] = 5
    assert source["coordinates"][1] == original["coordinates"][1]


@pytest.mark.parametrize("route", ROUTES)
def test_stale_typed_component_marker_never_authorizes_mutated_polygon(route):
    source = decode_component_geometry_bounded(translator(), overlapping_geometry())
    assert source._geometry_validated is True
    source["coordinates"][0][0] = [[0, 0], [4, 2], [4, 0], [0, 2], [0, 0]]
    with pytest.raises(UnsupportedEEError, match="topology"):
        transfer(route, source)


def test_component_constructor_does_not_change_raw_strict_decoder_contract():
    raw = overlapping_geometry()
    typed = transfer("constructor", raw)
    for source in (raw, typed):
        for decode in (decode_geometry_bounded, own_geometry_bounded):
            with pytest.raises(UnsupportedEEError, match="topology"):
                decode(translator(), source)
    assert own_component_geometry_bounded(translator(), typed) == typed


@pytest.mark.parametrize("operation", ("Geometry.union", "Geometry.intersects"))
def test_aggregate_geos_consumers_freshly_reject_component_geometry(operation):
    value = transfer("literal", overlapping_geometry())
    point = {"type": "Point", "coordinates": [1, 1], "geodesic": False}
    with pytest.raises(UnsupportedEEError, match="topology"):
        invoke_geometry_binary(translator(), operation, {
            "left": value, "right": point, "proj": "EPSG:4326",
        })
    with pytest.raises(UnsupportedEEError, match="topology"):
        own_ee_region(translator(), value, "strict raster region")


@pytest.mark.parametrize("route", ("direct", "wrong_receiver"))
def test_catalog_feature_collection_union_requires_strict_topology(route, monkeypatch):
    import shapely.ops

    geometry = transfer("literal", overlapping_geometry())
    collection = {"type": "FeatureCollection", "features": [feature(geometry)]}
    monkeypatch.setattr(shapely.ops, "unary_union", lambda _: pytest.fail(
        "Aggregate union ran before strict topology validation",
    ))
    with pytest.raises(UnsupportedEEError, match="topology"):
        if route == "direct":
            translator().footprint(collection)
        else:
            translator().invoke("Image.geometry", {"feature": collection})


def test_catalog_feature_collection_union_retains_valid_disjoint_control():
    geometry = overlapping_geometry()
    for point in geometry["coordinates"][1][0]:
        point[0] += 4
    collection = {"type": "FeatureCollection", "features": [feature(geometry)]}
    original = deepcopy(collection)
    output = translator().footprint(collection)
    assert output["type"] == "MultiPolygon"
    assert len(output["coordinates"]) == 2
    assert output["geodesic"] is False
    assert collection == original


@pytest.mark.parametrize("rows", (None, {}, [None], [{"type": "Point"}],
                                 [{"type": "Feature"}] * 1001))
def test_footprint_collection_structure_is_bounded_before_geometry_work(rows):
    with pytest.raises(UnsupportedEEError, match="Feature rows"):
        own_feature_collection_geometries(translator(), {
            "type": "FeatureCollection", "features": rows,
        }, "footprint")


def test_footprint_geometry_only_scan_preserves_budget_and_ignores_unused_metadata():
    geometry = {"type": "Point", "coordinates": [1, 2], "geodesic": False}
    rows = [{"type": "Feature", "geometry": None} for _ in range(999)]
    rows.append({"type": "Feature", "geometry": geometry, "properties": object()})
    collection = {"type": "FeatureCollection", "features": rows}
    cost = measure_geometry(geometry)
    required = 1001 + cost.nodes + cost.positions + 3 * cost.ring_closures
    t = translator(50000 - required)
    result = own_feature_collection_geometries(t, collection, "footprint")
    assert t.steps == 50000 and result == [geometry]
    result[0]["coordinates"][0] = 9
    assert geometry["coordinates"] == [1, 2]
    with pytest.raises(UnsupportedEEError, match="50000"):
        own_feature_collection_geometries(
            translator(50001 - required), collection, "footprint",
        )


@pytest.mark.parametrize("hole", (
    [[5, 0.5], [5.5, 0.5], [5.5, 1.5], [5, 1.5], [5, 0.5]],
    [[3, 0.5], [5, 0.5], [5, 1.5], [3, 1.5], [3, 0.5]],
))
def test_component_validation_keeps_shell_and_holes_as_one_atomic_polygon(hole):
    value = overlapping_geometry()
    value["coordinates"][0].append(hole)
    with pytest.raises(UnsupportedEEError, match="topology"):
        decode_component_geometry_bounded(translator(), value)


@pytest.mark.parametrize("typed", (False, True))
def test_nested_collection_transport_retains_geometry_and_metadata(typed):
    geometry = overlapping_geometry()
    source = feature(transfer("literal", geometry) if typed else geometry)
    child = {"type": "FeatureCollection", "features": [source]}
    t = translator()
    nested = construct_nested_collection(t, [child], ({"origin": ["actual"]}, True))
    output = flatten_collection(t, nested)
    result = output["features"][0]
    assert result == source
    assert type(result["geometry"]) is (GeometryValue if typed else dict)
    assert output["properties"] == {"origin": ["actual"]}
    result["geometry"]["coordinates"][0][0][1][0] = 3
    result["properties"]["nested"]["values"].append(3)
    assert source["geometry"]["coordinates"][0][0][1][0] == 4
    if typed:
        result["geometry"].geometry_metadata["evenOdd"] = False
        assert source["geometry"].geometry_metadata["evenOdd"] is True
    assert source["properties"]["nested"]["values"] == [1, 2]


def test_component_decode_preserves_exact_shared_budget_boundary(monkeypatch):
    import gee.planar_geometry_validation as planar

    raw = overlapping_geometry()
    cost = measure_geometry(raw)
    required = cost.nodes + cost.positions + 3 * cost.ring_closures
    exact = translator(50000 - required)
    assert decode_component_geometry_bounded(exact, raw) == raw
    assert exact.steps == 50000
    monkeypatch.setattr(planar, "planar_component_bounds", lambda _: pytest.fail(
        "GEOS component validation ran before budget reservation",
    ))
    with pytest.raises(UnsupportedEEError, match="50000"):
        decode_component_geometry_bounded(translator(50001 - required), raw)


@pytest.mark.parametrize("problem", ("cycle", "depth", "children", "positions", "finite"))
def test_component_decoder_keeps_structural_limits(problem):
    value = overlapping_geometry()
    if problem == "cycle":
        value = {"type": "GeometryCollection", "geometries": []}
        value["geometries"].append(value)
    elif problem == "depth":
        for _ in range(17):
            value = {"type": "GeometryCollection", "geometries": [value]}
    elif problem == "children":
        value = {"type": "GeometryCollection", "geometries": [value] * 1001}
    elif problem == "positions":
        value = {"type": "LineString", "geodesic": False,
                 "coordinates": [[0, 0]] * 10001}
    else:
        value["coordinates"][0][0][1][0] = float("inf")
    with pytest.raises(UnsupportedEEError):
        decode_component_geometry_bounded(translator(), value)
