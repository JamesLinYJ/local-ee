"""Bounded inline Feature predicates and planar overlay contracts."""
import pytest
from shapely.geometry import shape

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_geometry_binary import (
    FEATURE_GEOMETRY_BINARY_FUNCTIONS,
    invoke_feature_geometry_binary,
)
from gee.compat.earthengine.ir import UnsupportedEEError


_METHODS = {
    "Feature.contains", "Feature.containedIn", "Feature.disjoint",
    "Feature.intersects", "Feature.intersection", "Feature.union",
    "Feature.difference", "Feature.symmetricDifference",
}
_LEFT = {"type": "Polygon", "geodesic": False, "coordinates": [[
    [0, 0], [3, 0], [3, 2], [0, 2], [0, 0],
]]}
_RIGHT = {"type": "Polygon", "geodesic": False, "coordinates": [[
    [2, 1], [4, 1], [4, 3], [2, 3], [2, 1],
]]}


def _translator(steps=0):
    result = Translator([], {}, {})
    result.steps = steps
    return result


def _feature(geometry, properties=None, feature_id=None):
    result = {
        "type": "Feature", "geometry": geometry,
        "properties": {} if properties is None else properties,
    }
    if feature_id is not None:
        result["id"] = feature_id
    return result


def _invoke(name, left, right, *, translator=None, **options):
    return invoke_feature_geometry_binary(
        _translator() if translator is None else translator,
        name, {"left": left, "right": right, **options},
    )


def _geojson_area(geometry):
    """Compute polygonal area directly from output rings, independent of GEOS."""
    kind = geometry["type"]
    polygons = [geometry["coordinates"]] if kind == "Polygon" else geometry["coordinates"]
    area = 0.0
    for polygon in polygons:
        rings = []
        for ring in polygon:
            twice_area = sum(
                ring[index][0] * ring[index + 1][1]
                - ring[index + 1][0] * ring[index][1]
                for index in range(len(ring) - 1)
            )
            rings.append(abs(twice_area) / 2)
        area += rings[0] - sum(rings[1:])
    return area


def test_exported_feature_methods_match_the_eight_geometry_operations():
    assert FEATURE_GEOMETRY_BINARY_FUNCTIONS == frozenset(_METHODS)


def test_predicates_use_actual_left_and_right_feature_geometries():
    left_polygon = _feature(_LEFT)
    right_polygon = _feature(_RIGHT)
    center = _feature({"type": "Point", "coordinates": [1, 1]})
    far = _feature({"type": "Point", "coordinates": [8, 8]})

    assert _invoke("Feature.contains", left_polygon, center,
                   proj="EPSG:4326") is True
    assert _invoke("Feature.containedIn", center, left_polygon,
                   proj="EPSG:4326") is True
    assert _invoke("Feature.disjoint", left_polygon, far,
                   proj="EPSG:4326") is True
    assert _invoke("Feature.intersects", left_polygon, right_polygon,
                   proj="EPSG:4326") is True
    # Shapely's contains excludes the boundary. The local rule is explicit;
    # it is not evidence of Google spherical or boundary-policy parity.
    edge = _feature({"type": "Point", "coordinates": [3, 1]})
    assert _invoke("Feature.contains", left_polygon, edge,
                   proj="EPSG:4326") is False


def test_overlays_match_literal_geometries_and_keep_owned_left_properties():
    left = _feature(
        _LEFT, {"system:index": "left-row", "label": "owner",
                "nested": {"values": [1, 2]}}, "left-row",
    )
    right = _feature(
        _RIGHT, {"system:index": "right-row", "label": "ignored"},
        "right-row",
    )
    left_snapshot = {
        "geometry": {"type": "Polygon", "geodesic": False, "coordinates": [[
            [0, 0], [3, 0], [3, 2], [0, 2], [0, 0],
        ]]},
        "properties": {"system:index": "left-row", "label": "owner",
                       "nested": {"values": [1, 2]}},
    }
    expected = {
        "Feature.intersection": shape({
            "type": "Polygon", "coordinates": [[
                [2, 1], [3, 1], [3, 2], [2, 2], [2, 1],
            ]],
        }),
        "Feature.union": shape({
            "type": "Polygon", "coordinates": [[
                [0, 0], [3, 0], [3, 1], [4, 1], [4, 3], [2, 3],
                [2, 2], [0, 2], [0, 0],
            ]],
        }),
        "Feature.difference": shape({
            "type": "Polygon", "coordinates": [[
                [0, 0], [3, 0], [3, 1], [2, 1], [2, 2], [0, 2], [0, 0],
            ]],
        }),
        "Feature.symmetricDifference": shape({
            "type": "MultiPolygon", "coordinates": [
                [[[0, 0], [3, 0], [3, 1], [2, 1], [2, 2], [0, 2], [0, 0]]],
                [[[3, 1], [4, 1], [4, 3], [2, 3], [2, 2], [3, 2], [3, 1]]],
            ],
        }),
    }
    expected_areas = {
        "Feature.intersection": 1.0,
        "Feature.union": 9.0,
        "Feature.difference": 5.0,
        "Feature.symmetricDifference": 8.0,
    }

    for name, reference in expected.items():
        result = _invoke(name, left, right, proj="EPSG:4326")
        assert result["type"] == "Feature"
        assert shape(result["geometry"]).equals(reference)
        assert _geojson_area(result["geometry"]) == expected_areas[name]
        assert result["properties"] == left_snapshot["properties"]
        assert result["properties"] is not left["properties"]
        assert result["id"] == "left-row"
        assert "right-row" not in repr(result)
        result["properties"]["nested"]["values"].append(99)
        assert left["properties"]["nested"]["values"] == [1, 2]

    intersection = _invoke(
        "Feature.intersection", left, right, proj="EPSG:4326",
    )
    intersection["geometry"]["coordinates"][0][0][0] = 99
    assert left["geometry"]["coordinates"][0][0] == [0, 0]
    assert right["geometry"]["coordinates"][0][0] == [2, 1]

    index_only = _feature(_LEFT, {"system:index": "indexed-left"})
    indexed_result = _invoke(
        "Feature.union", index_only, right, proj="EPSG:4326",
    )
    assert "id" not in indexed_result
    assert indexed_result["properties"]["system:index"] == "indexed-left"

    # A disjoint polygon intersection is a valid empty geometry result.
    empty = _invoke(
        "Feature.intersection", left,
        _feature({"type": "Polygon", "geodesic": False, "coordinates": [[
            [5, 5], [6, 5], [6, 6], [5, 6], [5, 5],
        ]]}),
        proj="EPSG:4326",
    )
    assert shape(empty["geometry"]).is_empty
    assert empty["geometry"]["type"] == "GeometryCollection"


@pytest.mark.parametrize("name", sorted(_METHODS))
def test_methods_reject_non_features_null_or_malformed_geometries(name):
    left = _feature(_LEFT)
    with pytest.raises(UnsupportedEEError):
        _invoke(name, {"type": "Image"}, left, proj="EPSG:4326")
    with pytest.raises(UnsupportedEEError):
        _invoke(name, _feature(None), left, proj="EPSG:4326")
    malformed = _feature({"type": "Point", "coordinates": [0, 0], "extra": 1})
    with pytest.raises(UnsupportedEEError):
        _invoke(name, malformed, left, proj="EPSG:4326")
    for flags in ({"geodesic": True}, {"evenOdd": False}):
        with pytest.raises(UnsupportedEEError):
            _invoke(
                name,
                _feature({"type": "Polygon", "coordinates": _LEFT["coordinates"],
                          **flags}),
                left, proj="EPSG:4326",
            )


@pytest.mark.parametrize("options", [
    {}, {"proj": None}, {"proj": "EPSG:3857"},
    {"proj": "EPSG:4326", "maxError": 1},
])
def test_projection_and_error_margin_do_not_silently_select_google_defaults(options):
    with pytest.raises(UnsupportedEEError):
        _invoke("Feature.intersection", _feature(_LEFT), _feature(_RIGHT), **options)


def test_rejects_conflicting_identity_extra_arguments_and_missing_operands():
    conflict = _feature(_LEFT, {"system:index": "other"}, "left-row")
    with pytest.raises(UnsupportedEEError, match="different elements"):
        _invoke("Feature.union", conflict, _feature(_RIGHT), proj="EPSG:4326")
    with pytest.raises(UnsupportedEEError):
        invoke_feature_geometry_binary(
            _translator(), "Feature.intersects",
            {"left": _feature(_LEFT), "right": _feature(_RIGHT),
             "proj": "EPSG:4326", "ignored": False},
        )
    for arguments in ({"right": _feature(_RIGHT)}, {"left": _feature(_LEFT)}):
        with pytest.raises(UnsupportedEEError):
            invoke_feature_geometry_binary(
                _translator(), "Feature.intersects",
                {**arguments, "proj": "EPSG:4326"},
            )


def test_property_output_copy_budget_is_reserved_before_geometry_work(monkeypatch):
    from gee.compat.earthengine import feature_geometry_binary

    called = False

    def forbidden_geometry_work(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("GEOS path must not run after output-copy preflight fails")

    monkeypatch.setattr(
        feature_geometry_binary, "invoke_geometry_binary", forbidden_geometry_work,
    )
    # Each input scan fits; the additional owned left-property copy exceeds
    # the inherited budget before a geometry operation may begin.
    bulk = list(range(2_500))
    left = _feature(_LEFT, {"bulk": bulk}, "left-row")
    right = _feature(_RIGHT, {"small": 1}, "right-row")
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        _invoke(
            "Feature.union", left, right, translator=_translator(24_000),
            proj="EPSG:4326",
        )
    assert not called
