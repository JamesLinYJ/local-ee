"""Hand-checkable contracts for bounded planar Geometry binary operations."""
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_binary import (
    GEOMETRY_BINARY_ARGUMENTS,
    GEOMETRY_BINARY_FUNCTIONS,
    invoke_geometry_binary,
)
from gee.compat.earthengine.geometry_values import decode_geometry_bounded
from gee.compat.earthengine.public_values import public_value
from gee.ee_translate import UnsupportedEEError


def translator(steps=0):
    result = Translator([], {}, {})
    result.steps = steps
    return result


def rectangle(x1, y1, x2, y2):
    return {
        "type": "Polygon",
        "coordinates": [[[x1, y1], [x2, y1], [x2, y2],
                         [x1, y2], [x1, y1]]],
        "geodesic": False,
    }


def point(x, y):
    return {"type": "Point", "coordinates": [x, y]}


def line(*coordinates):
    return {"type": "LineString", "coordinates": [list(item) for item in coordinates],
            "geodesic": False}


def call(name, left, right, *, translator_value=None, **options):
    arguments = {"left": left, "right": right, "proj": "EPSG:4326", **options}
    return invoke_geometry_binary(translator_value or translator(), name, arguments)


def ring_area(ring):
    return abs(sum(
        ring[index][0] * ring[index + 1][1]
        - ring[index + 1][0] * ring[index][1]
        for index in range(len(ring) - 1)
    )) / 2


def polygon_area(geometry):
    if geometry["type"] == "GeometryCollection":
        return sum(polygon_area(child) for child in geometry["geometries"])
    if geometry["type"] == "MultiPolygon":
        return sum(polygon_area({"type": "Polygon", "coordinates": polygon})
                   for polygon in geometry["coordinates"])
    if geometry["type"] != "Polygon":
        return 0
    rings = geometry["coordinates"]
    return ring_area(rings[0]) - sum(map(ring_area, rings[1:]))


def test_pinned_signatures_have_only_the_official_binary_arguments():
    assert GEOMETRY_BINARY_FUNCTIONS == frozenset({
        "Geometry.contains", "Geometry.containedIn", "Geometry.intersects",
        "Geometry.disjoint", "Geometry.intersection", "Geometry.union",
        "Geometry.difference", "Geometry.symmetricDifference",
    })
    for name, (required, optional) in GEOMETRY_BINARY_ARGUMENTS.items():
        assert required == frozenset({"left", "right"})
        assert optional == frozenset({"maxError", "proj"})
        assert call(name, point(0, 0), point(0, 0)) is not None
        assert call(name, point(0, 0), point(0, 0), maxError=None) is not None


def test_predicates_distinguish_contains_from_boundary_intersection():
    polygon = rectangle(0, 0, 2, 2)
    assert call("Geometry.contains", polygon, point(1, 1)) is True
    assert call("Geometry.contains", polygon, point(0, 1)) is False
    assert call("Geometry.intersects", polygon, point(0, 1)) is True
    assert call("Geometry.containedIn", point(1, 1), polygon) is True
    assert call("Geometry.containedIn", point(3, 1), polygon) is False
    assert call("Geometry.disjoint", polygon, point(3, 1)) is True
    assert call("Geometry.disjoint", polygon, point(0, 1)) is False


def test_polygon_overlays_match_hand_calculated_area_and_keep_metadata():
    left, right = rectangle(0, 0, 2, 2), rectangle(1, 1, 3, 3)
    intersection = call("Geometry.intersection", left, right)
    union = call("Geometry.union", left, right)
    difference = call("Geometry.difference", left, right)
    symmetric = call("Geometry.symmetricDifference", left, right)

    assert intersection["type"] == "Polygon"
    assert polygon_area(intersection) == 1
    assert polygon_area(union) == 7
    assert polygon_area(difference) == 3
    assert polygon_area(symmetric) == 6
    for result in (intersection, union, difference, symmetric):
        assert result.geometry_metadata == {"crs": "EPSG:4326", "geodesic": False}
        assert result["geodesic"] is False and "crs" not in result


def test_lower_dimensional_mixed_and_empty_outputs_are_owned_and_revalidatable():
    polygon = rectangle(0, 0, 2, 2)
    crossing = line((-1, 1), (3, 1))
    intersection = call("Geometry.intersection", polygon, crossing)
    assert intersection["type"] == "LineString"
    assert {tuple(position) for position in intersection["coordinates"]} == {(0, 1), (2, 1)}

    mixed = call("Geometry.union", polygon, line((4, 0), (5, 0)))
    assert mixed["type"] == "GeometryCollection"
    assert [child["type"] for child in mixed["geometries"]] == ["Polygon", "LineString"]
    assert all(child.geometry_metadata.get("geodesic") is False
               for child in mixed["geometries"])
    assert call("Geometry.intersects", mixed, point(4.5, 0)) is True
    public_mixed = public_value(mixed)
    assert public_mixed["geodesic"] is False
    assert "crs" not in public_mixed
    assert all(child["geodesic"] is False for child in public_mixed["geometries"])
    assert call("Geometry.intersects", public_mixed, point(4.5, 0)) is True

    empty = call("Geometry.intersection", polygon, rectangle(4, 4, 5, 5))
    assert empty["type"] == "GeometryCollection" and empty["geometries"] == []
    assert empty.geometry_metadata == {"crs": "EPSG:4326", "geodesic": False}
    assert public_value(empty) == {
        "type": "GeometryCollection", "geometries": [], "geodesic": False,
    }
    assert decode_geometry_bounded(translator(), empty).geometry_metadata == empty.geometry_metadata


def test_public_binary_geometry_roundtrips_through_pinned_python_sdk_offline():
    import ee

    from gee.ee_python_client import configure_local_ee
    from scripts.ee_python_api.offline import OfflineGuard

    with OfflineGuard() as guard:
        configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path="vendor/earthengine-js/algorithms.json",
        )
        result = call("Geometry.intersection", rectangle(0, 0, 2, 2),
                      rectangle(1, 1, 3, 3))
        sdk_geometry = ee.Geometry(public_value(result))
        wire = ee.serializer.encode(sdk_geometry, for_cloud_api=False)
        assert wire["geodesic"] is False and "crs" not in wire
        assert call("Geometry.intersects", wire, point(1.5, 1.5)) is True
        assert guard.evidence()["attempt_count"] == 0


@pytest.mark.parametrize("options, message", [
    ({}, "spherical"),
    ({"proj": None}, "spherical"),
    ({"proj": 4326}, "spherical"),
    ({"proj": True}, "spherical"),
    ({"maxError": 0}, "maxError"),
    ({"maxError": 1}, "maxError"),
])
def test_binary_projection_and_error_margin_are_strict(options, message):
    arguments = {"left": point(0, 0), "right": point(1, 1), **options}
    with pytest.raises(UnsupportedEEError, match=message):
        invoke_geometry_binary(translator(), "Geometry.intersects", arguments)


def test_exact_arguments_and_input_geometry_metadata_are_required():
    base = {"left": point(0, 0), "right": point(1, 1), "proj": "EPSG:4326"}
    with pytest.raises(UnsupportedEEError, match="requires arguments"):
        invoke_geometry_binary(translator(), "Geometry.union", {"left": point(0, 0), "proj": "EPSG:4326"})
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_geometry_binary(translator(), "Geometry.union", {**base, "leftover": 1})
    with pytest.raises(UnsupportedEEError, match="geodesic=false"):
        invoke_geometry_binary(translator(), "Geometry.intersects", {
            **base, "left": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        })
    with pytest.raises(UnsupportedEEError, match="spherical"):
        invoke_geometry_binary(translator(), "Geometry.intersects", {
            **base, "left": {**rectangle(0, 0, 1, 1), "geodesic": True},
        })
    with pytest.raises(UnsupportedEEError, match="EPSG:4326"):
        invoke_geometry_binary(translator(), "Geometry.intersects", {
            **base, "left": {**rectangle(0, 0, 1, 1), "crs": "EPSG:3857"},
        })
    with pytest.raises(UnsupportedEEError, match="evenOdd=false"):
        invoke_geometry_binary(translator(), "Geometry.intersects", {
            **base, "left": {**rectangle(0, 0, 1, 1), "evenOdd": False},
        })


def test_planar_flag_is_checked_per_collection_component_without_inheritance():
    collection = {
        "type": "GeometryCollection", "geodesic": False,
        "geometries": [{"type": "LineString", "coordinates": [[0, 0], [1, 1]]}],
    }
    with pytest.raises(UnsupportedEEError, match="geodesic=false"):
        call("Geometry.intersects", collection, point(0, 0))
    collection["geometries"][0]["geodesic"] = False
    assert call("Geometry.intersects", collection, point(0, 0)) is True
    assert call("Geometry.intersects", {"type": "MultiLineString", "coordinates": []}, point(0, 0)) is False


def test_intersection_precharges_possible_mixed_dimension_collection_children():
    polygon = rectangle(0, 0, 2, 2)
    collection = {
        "type": "GeometryCollection",
        "geometries": [line((-1, 1), (3, 1)), point(1, 1.5)],
    }
    result = call("Geometry.intersection", polygon, collection)
    assert result["type"] == "GeometryCollection"
    assert {child["type"] for child in result["geometries"]} == {"LineString", "Point"}
    assert all(child["geodesic"] is False for child in result["geometries"])


def test_open_polygon_and_linear_ring_closures_are_counted_and_normalized():
    open_ring = {"type": "LinearRing", "coordinates": [[0, 0], [2, 0],
                                                            [2, 2], [0, 2]],
                 "geodesic": False}
    open_polygon = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0],
                                                            [2, 2], [0, 2]]],
                    "geodesic": False}
    assert call("Geometry.intersects", open_ring, point(0, 1)) is True
    assert call("Geometry.intersects", open_polygon, point(0, 1)) is True


def test_mutated_ring_leaves_are_not_compared_before_fresh_decode():
    class EqualityTrap:
        def __eq__(self, other):
            raise AssertionError("mutable coordinate leaves must not be compared in preflight")

    geometry = {
        "type": "Polygon",
        "coordinates": [[[EqualityTrap(), 0], [1, 0], [1, 1], [0, 0]]],
        "geodesic": False,
    }
    with pytest.raises(UnsupportedEEError, match="finite two-dimensional"):
        call("Geometry.intersects", geometry, point(0, 0))


def test_mutated_geometry_value_is_revalidated_before_binary_operation():
    value = decode_geometry_bounded(translator(), point(1, 1))
    value["coordinates"][0] = 181
    with pytest.raises(UnsupportedEEError, match="longitude/latitude bounds"):
        call("Geometry.intersects", value, point(0, 0))

    value = decode_geometry_bounded(translator(), rectangle(0, 0, 1, 1))
    value.geometry_metadata["geodesic"] = True
    with pytest.raises(UnsupportedEEError, match="spherical"):
        call("Geometry.intersects", value, point(0, 0))
def test_output_objects_do_not_alias_mutable_operands():
    left, right = rectangle(0, 0, 2, 2), rectangle(1, 1, 3, 3)
    output = call("Geometry.intersection", left, right)
    output["coordinates"][0][0][0] = 99
    assert left["coordinates"][0][0] == [0, 0]
    assert right["coordinates"][0][0] == [1, 1]
