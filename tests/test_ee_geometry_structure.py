"""Pinned SDK shape and bounded local geometry-structure contracts."""
import copy

import pytest
from shapely.geometry import shape

from gee.ee_python_client import configure_local_ee
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_constructors import (
    GEOMETRY_CONSTRUCTOR_ARGUMENTS,
    construct_geometry_value,
)
from gee.compat.earthengine.geometry_structure import (
    GEOMETRY_STRUCTURE_ARGUMENTS,
    invoke_geometry_structure,
)
from gee.compat.earthengine.geometry_values import (
    GeometryValue,
    decode_geometry_bounded,
    own_geometry_bounded,
)
from gee.ee_translate import UnsupportedEEError
from scripts.ee_python_api.offline import OfflineGuard


@pytest.fixture
def sdk():
    import ee

    with OfflineGuard() as guard:
        configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path="vendor/earthengine-js/algorithms.json",
        )
        yield ee
        assert guard.evidence()["attempt_count"] == 0


def translator(steps=0):
    result = Translator([], {}, {})
    result.steps = steps
    return result


def invocation_names(value):
    names = []
    if isinstance(value, dict):
        if value.get("type") == "Invocation":
            names.append(value.get("functionName"))
        for child in value.values():
            names.extend(invocation_names(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            names.extend(invocation_names(child))
    return names


def test_pinned_sdk_serializes_geometry_structure_invocations_and_ring_constructor(sdk):
    point = sdk.Geometry.Point([3, 4])
    methods = {
        "coordinates": "Geometry.coordinates",
        "geometries": "Geometry.geometries",
        "isUnbounded": "Geometry.isUnbounded",
        "edgesAreGeodesics": "Geometry.edgesAreGeodesics",
        "geodesic": "Geometry.geodesic",
        "type": "Geometry.type",
    }
    for method, expected in methods.items():
        serialized = sdk.serializer.encode(getattr(point, method)(), for_cloud_api=False)
        assert expected in invocation_names(serialized)

    ring = sdk.Geometry.LinearRing(
        [[0, 0], [2, 0], [2, 2]], proj="EPSG:4326", geodesic=False,
    )
    serialized_ring = sdk.serializer.encode(ring, for_cloud_api=False)
    assert "GeometryConstructors.LinearRing" in invocation_names(serialized_ring)
    literal_ring = sdk.Geometry.LinearRing([[0, 0], [2, 0], [2, 2]])
    assert sdk.serializer.encode(literal_ring, for_cloud_api=False) == {
        "type": "LinearRing", "coordinates": [[0, 0], [2, 0], [2, 2]],
    }

    bbox = sdk.Geometry.BBox(0, 0, 2, 2).toGeoJSON()
    assert bbox == {
        "type": "Polygon", "geodesic": False,
        "coordinates": [[[0, 2], [0, 0], [2, 0], [2, 2]]],
    }


def test_structure_accessors_return_real_shape_flags_and_owned_values():
    t = translator()
    source = {
        "type": "GeometryCollection",
        "geometries": [
            {"type": "LinearRing", "coordinates": [[0, 0], [2, 0], [2, 2]]},
            {"type": "Point", "coordinates": [1, 1], "geodesic": False},
        ],
    }
    original = copy.deepcopy(source)
    geometry = decode_geometry_bounded(t, source)
    assert geometry["type"] == "GeometryCollection"
    assert geometry["geometries"][0]["type"] == "LinearRing"
    assert geometry["geometries"][1].geometry_metadata["geodesic"] is False
    assert invoke_geometry_structure(t, "Geometry.type", {"geometry": geometry}) == "GeometryCollection"
    assert invoke_geometry_structure(t, "Geometry.geodesic", {"geometry": geometry}) is False
    assert invoke_geometry_structure(t, "Geometry.edgesAreGeodesics", {"geometry": geometry}) is False
    assert invoke_geometry_structure(t, "Geometry.isUnbounded", {"geometry": geometry}) is False
    children = invoke_geometry_structure(t, "Geometry.geometries", {"geometry": geometry})
    assert [child["type"] for child in children] == ["LinearRing", "Point"]
    assert children[1].geometry_metadata["geodesic"] is False
    assert invoke_geometry_structure(t, "Geometry.geodesic", {"geometry": children[1]}) is False
    children[0]["coordinates"][0][0] = 99
    assert geometry["geometries"][0]["coordinates"][0] == [0, 0]
    assert source == original

    point = decode_geometry_bounded(t, {"type": "Point", "coordinates": [5, 6]})
    singleton = invoke_geometry_structure(t, "Geometry.geometries", {"geometry": point})
    assert len(singleton) == 1 and singleton[0] == point
    singleton[0]["coordinates"][0] = 50
    assert point["coordinates"] == [5, 6]
    coordinates = invoke_geometry_structure(t, "Geometry.coordinates", {"geometry": point})
    coordinates[0] = 50
    assert point["coordinates"] == [5, 6]

    with pytest.raises(UnsupportedEEError, match="no GeoJSON coordinates"):
        invoke_geometry_structure(t, "Geometry.coordinates", {"geometry": geometry})


def test_geometry_metadata_options_are_retained_and_planar_flags_are_exact():
    t = translator()
    geometry = decode_geometry_bounded(t, {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]],
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "geodesic": False,
        "evenOdd": True,
    })
    assert geometry.geometry_metadata == {
        "crs": "EPSG:4326", "geodesic": False, "evenOdd": True,
    }
    assert geometry["coordinates"][0][0] == geometry["coordinates"][0][-1]
    assert invoke_geometry_structure(t, "Geometry.geodesic", {"geometry": geometry}) is False
    assert invoke_geometry_structure(t, "Geometry.edgesAreGeodesics", {"geometry": geometry}) is False


def test_geometry_constructors_bbox_multigeometry_and_linearring_keep_types():
    t = translator()
    bbox = construct_geometry_value(t, "BBox", {
        "west": -2, "south": -100, "east": 3, "north": 100,
    })
    assert bbox["type"] == "Polygon"
    assert bbox["coordinates"] == [[[-2, 90], [-2, -90], [3, -90], [3, 90], [-2, 90]]]
    assert bbox.geometry_metadata["geodesic"] is False
    assert shape(bbox).area == 900

    ring = construct_geometry_value(t, "LinearRing", {
        "coordinates": [[0, 0], [2, 0], [2, 2]], "geodesic": False,
    })
    assert ring["type"] == "LinearRing"
    assert ring["coordinates"] == [[0, 0], [2, 0], [2, 2], [0, 0]]
    assert shape(ring).geom_type == "LinearRing"

    collection = construct_geometry_value(t, "MultiGeometry", {
        "geometries": [ring, {"type": "Point", "coordinates": [1, 1]}],
        "geodesic": False,
    })
    assert collection["type"] == "GeometryCollection"
    assert [child["type"] for child in collection["geometries"]] == ["LinearRing", "Point"]
    assert collection.geometry_metadata["geodesic"] is False


def test_constructor_signatures_reject_unknown_and_missing_args_before_empty_cases():
    t = translator()
    assert GEOMETRY_CONSTRUCTOR_ARGUMENTS["GeometryConstructors.BBox"] == (
        frozenset({"west", "south", "east", "north"}), frozenset())
    assert GEOMETRY_CONSTRUCTOR_ARGUMENTS["GeometryConstructors.MultiGeometry"][0] == frozenset({"geometries"})
    assert GEOMETRY_CONSTRUCTOR_ARGUMENTS["GeometryConstructors.LinearRing"][0] == frozenset({"coordinates"})
    assert GEOMETRY_STRUCTURE_ARGUMENTS["Geometry.geometries"] == (
        frozenset({"geometry"}), frozenset())

    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        construct_geometry_value(t, "MultiGeometry", {"geometries": [], "typo": True})
    with pytest.raises(UnsupportedEEError, match="requires arguments"):
        construct_geometry_value(t, "BBox", {"west": 0, "south": 0, "east": 1})
    with pytest.raises(UnsupportedEEError, match="maxError"):
        construct_geometry_value(t, "MultiGeometry", {"geometries": [], "maxError": 1})
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_geometry_structure(t, "Geometry.geometries", {"geometry": {"type": "GeometryCollection", "geometries": []}, "extra": 1})


def test_structure_accessors_validate_untrusted_direct_geometry_ir():
    with pytest.raises(UnsupportedEEError, match="spherical"):
        invoke_geometry_structure(
            translator(), "Geometry.type",
            {"geometry": {"type": "Point", "coordinates": [0, 0], "geodesic": True}},
        )
    with pytest.raises(UnsupportedEEError, match="finite"):
        invoke_geometry_structure(
            translator(), "Geometry.isUnbounded",
            {"geometry": {"type": "Point", "coordinates": [0, float("inf")]}},
        )
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_geometry_structure(
            translator(49994), "Geometry.coordinates",
            {"geometry": {"type": "Point", "coordinates": [0, 0]}},
        )


def test_mutated_geometry_values_are_revalidated_and_owned_copies_keep_metadata():
    t = translator()
    point = decode_geometry_bounded(t, {"type": "Point", "coordinates": [1, 2]})
    point["coordinates"][0] = 181
    with pytest.raises(UnsupportedEEError, match="longitude/latitude bounds"):
        invoke_geometry_structure(t, "Geometry.type", {"geometry": point})
    with pytest.raises(UnsupportedEEError, match="longitude/latitude bounds"):
        own_geometry_bounded(t, point)

    flagged = decode_geometry_bounded(t, {"type": "Point", "coordinates": [1, 2]})
    flagged.geometry_metadata["geodesic"] = True
    with pytest.raises(UnsupportedEEError, match="spherical"):
        invoke_geometry_structure(t, "Geometry.geodesic", {"geometry": flagged})

    flagged = decode_geometry_bounded(t, {"type": "Point", "coordinates": [1, 2]})
    flagged["geodesic"] = True
    with pytest.raises(UnsupportedEEError, match="spherical"):
        own_geometry_bounded(t, flagged)

    collection = decode_geometry_bounded(t, {
        "type": "GeometryCollection",
        "geometries": [{"type": "Point", "coordinates": [1, 2]}],
    })
    collection["geometries"][0]["coordinates"][1] = 91
    with pytest.raises(UnsupportedEEError, match="longitude/latitude bounds"):
        invoke_geometry_structure(t, "Geometry.geometries", {"geometry": collection})

    source = decode_geometry_bounded(t, {
        "type": "Point", "coordinates": [1, 2], "geodesic": False,
    })
    owned = own_geometry_bounded(t, source)
    assert owned is not source
    assert owned.geometry_metadata == {"geodesic": False}


@pytest.mark.parametrize("arguments, message", [
    ({"west": 170, "south": -1, "east": -170, "north": 1}, "dateline wrapping"),
    ({"west": 0, "south": 95, "east": 1, "north": 100}, "beyond a pole"),
    ({"west": 0, "south": 2, "east": 1, "north": 1}, "north must be greater than or equal to south"),
    ({"west": 10**1000, "south": 0, "east": 1, "north": 1}, "finite number"),
])
def test_bbox_rejects_unrepresentable_or_out_of_range_boxes(arguments, message):
    with pytest.raises(UnsupportedEEError, match=message):
        construct_geometry_value(translator(), "BBox", arguments)


def test_bbox_canonicalizes_longitudes_and_bounds_huge_point_numbers():
    bbox = construct_geometry_value(translator(), "BBox", {
        "west": 181, "south": 0, "east": 182, "north": 1,
    })
    assert bbox["coordinates"] == [[[-179, 1], [-179, 0], [-178, 0], [-178, 1], [-179, 1]]]
    assert bbox.geometry_metadata["geodesic"] is False

    with pytest.raises(UnsupportedEEError, match="finite two-dimensional positions"):
        decode_geometry_bounded(translator(), {"type": "Point", "coordinates": [10**1000, 0]})


def test_bounded_decode_cycle_depth_and_budget_guards_precede_geos(monkeypatch):
    coordinates = []
    coordinates.append(coordinates)
    cycle = {"type": "GeometryCollection", "geometries": []}
    cycle["geometries"].append(cycle)
    with pytest.raises(UnsupportedEEError, match="cycle"):
        decode_geometry_bounded(translator(), {"type": "LineString", "coordinates": coordinates})
    with pytest.raises(UnsupportedEEError, match="cycle"):
        decode_geometry_bounded(translator(), cycle)

    nested = {"type": "Point", "coordinates": [0, 0]}
    for _ in range(17):
        nested = {"type": "GeometryCollection", "geometries": [nested]}
    with pytest.raises(UnsupportedEEError, match="nesting exceeds 16"):
        decode_geometry_bounded(translator(), nested)

    import shapely.geometry

    called = []
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: called.append(value))
    t = translator(49994)
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        decode_geometry_bounded(t, {"type": "Point", "coordinates": [1, 2]})
    assert t.steps == 49994
    assert not called
