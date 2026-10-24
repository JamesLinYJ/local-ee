"""Effective spherical defaults and safe geometry-value topology routing."""
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_constructors import construct_geometry_value
from gee.compat.earthengine.geometry_structure import invoke_geometry_structure
from gee.compat.earthengine.geometry_values import (
    decode_geometry_bounded,
    effective_geometry_geodesic,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError
from scripts.ee_python_api.offline import OfflineGuard


def translator(steps=0):
    value = Translator([], {}, {})
    value.steps = steps
    return value


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


def _rectangle(*, geodesic=None, even_odd=None):
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]],
    }
    if geodesic is not None:
        geometry["geodesic"] = geodesic
    if even_odd is not None:
        geometry["evenOdd"] = even_odd
    return geometry


def test_pinned_sdk_numeric_geometry_defaults_are_omitted_except_even_odd(sdk):
    polygon = sdk.Geometry.Polygon([[[0, 0], [2, 0], [2, 2], [0, 2]]])
    rectangle = sdk.Geometry.Rectangle([0, 0, 2, 2])
    point = sdk.Geometry.Point([1, 1])
    line = sdk.Geometry.LineString([[0, 0], [2, 2]])

    assert sdk.serializer.encode(polygon, for_cloud_api=False) == {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]],
        "evenOdd": True,
    }
    assert sdk.serializer.encode(rectangle, for_cloud_api=False)["evenOdd"] is True
    for geometry in (point, line):
        wire = sdk.serializer.encode(geometry, for_cloud_api=False)
        assert "geodesic" not in wire
        assert "crs" not in wire


def test_default_spherical_values_keep_wire_omissions_and_bypass_geos(monkeypatch):
    from gee.compat.earthengine import spherical_native
    import shapely.geometry

    native_calls = []
    geos_calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: native_calls.append(value))
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: geos_calls.append(value))

    raw = _rectangle()
    result = decode_geometry_bounded(translator(), raw)
    assert result.geometry_metadata == {
        "crs": "EPSG:4326", "geodesic": True, "evenOdd": True,
    }
    assert "geodesic" not in result
    assert "evenOdd" not in result
    assert result["coordinates"][0][0] == result["coordinates"][0][-1]
    assert native_calls == [result]
    assert geos_calls == []
    assert raw["coordinates"][0][0] != raw["coordinates"][0][-1]


def test_explicit_planar_flags_survive_public_mapping_and_use_only_geos(monkeypatch):
    from gee.compat.earthengine import spherical_native
    import shapely.geometry

    native_calls = []
    geos_calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: native_calls.append(value))

    class PlanarShape:
        is_valid = True

    monkeypatch.setattr(shapely.geometry, "shape", lambda value: geos_calls.append(value) or PlanarShape())

    result = decode_geometry_bounded(translator(), _rectangle(geodesic=False, even_odd=True))
    assert result["geodesic"] is False
    assert result["evenOdd"] is True
    assert result.geometry_metadata == {
        "crs": "EPSG:4326", "geodesic": False, "evenOdd": True,
    }
    assert native_calls == []
    assert geos_calls == [result]


def test_even_odd_left_inside_routes_to_s2_and_planar_left_inside_fails_closed(monkeypatch):
    from gee.compat.earthengine import spherical_native
    import shapely.geometry

    native_calls = []
    geos_calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: native_calls.append(value))
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: geos_calls.append(value))

    spherical = decode_geometry_bounded(
        translator(), _rectangle(geodesic=True, even_odd=False),
    )
    assert spherical["evenOdd"] is False
    assert spherical.geometry_metadata["evenOdd"] is False
    assert native_calls == [spherical]
    assert geos_calls == []

    with pytest.raises(UnsupportedEEError, match="Planar Geometry evenOdd=false"):
        decode_geometry_bounded(
            translator(), _rectangle(geodesic=False, even_odd=False),
        )
    assert geos_calls == []


def test_mixed_geometry_collection_validates_each_model_without_sending_sphere_to_geos(monkeypatch):
    from gee.compat.earthengine import spherical_native
    import shapely.geometry

    native_calls = []
    geos_calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: native_calls.append(value))

    class PlanarShape:
        is_valid = True

    monkeypatch.setattr(shapely.geometry, "shape", lambda value: geos_calls.append(value) or PlanarShape())

    collection = decode_geometry_bounded(translator(), {
        "type": "GeometryCollection",
        "geometries": [
            _rectangle(),
            _rectangle(geodesic=False),
        ],
    })
    assert native_calls == [collection["geometries"][0]]
    assert geos_calls == [collection["geometries"][1]]
    with pytest.raises(UnsupportedEEError, match="mixed geodesic"):
        effective_geometry_geodesic(collection)


@pytest.mark.parametrize("parent_flag,child_flags,planar_indices,spherical_indices,whole_collection", [
    (False, [None, True], [0], [1], False),
    (True, [None, False], [1], [0], False),
    (False, [True, True], [], [0, 1], False),
    (True, [None, None], [], [], True),
])
def test_collection_flag_is_inherited_but_explicit_child_flag_wins(
        monkeypatch, parent_flag, child_flags, planar_indices, spherical_indices,
        whole_collection):
    from gee.compat.earthengine import spherical_native
    import shapely.geometry

    native_calls = []
    geos_calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: native_calls.append(value))

    class PlanarShape:
        is_valid = True

    monkeypatch.setattr(shapely.geometry, "shape",
                        lambda value: geos_calls.append(value) or PlanarShape())

    children = []
    for flag in child_flags:
        child = _rectangle()
        if flag is not None:
            child["geodesic"] = flag
        children.append(child)
    collection = decode_geometry_bounded(translator(), {
        "type": "GeometryCollection",
        "geodesic": parent_flag,
        "geometries": children,
    })

    if planar_indices or spherical_indices:
        with pytest.raises(UnsupportedEEError, match="mixed geodesic"):
            effective_geometry_geodesic(collection)
    else:
        assert effective_geometry_geodesic(collection) is parent_flag
    assert geos_calls == [collection["geometries"][index] for index in planar_indices]
    if whole_collection:
        assert native_calls == [collection]
    else:
        assert native_calls == [collection["geometries"][index] for index in spherical_indices]


def test_mixed_collection_inherited_left_inside_rejects_planar_child(monkeypatch):
    from gee.compat.earthengine import spherical_native
    import shapely.geometry

    native_calls = []
    geos_calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: native_calls.append(value))
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: geos_calls.append(value))
    with pytest.raises(UnsupportedEEError, match="Planar Geometry evenOdd=false left-inside"):
        decode_geometry_bounded(translator(), {
            "type": "GeometryCollection",
            "evenOdd": False,
            "geometries": [
                {"type": "Polygon", "geodesic": False,
                 "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]]},
                {"type": "Polygon", "geodesic": True, "evenOdd": True,
                 "coordinates": [[[3, 0], [5, 0], [5, 2], [3, 2]]]},
            ],
        })
    assert geos_calls == []
    assert native_calls == []


def test_mixed_collection_passes_inherited_evenodd_to_spherical_validation(monkeypatch):
    from gee.compat.earthengine import spherical_native
    from gee.compat.earthengine.spherical_wire import encode_geometry
    import shapely.geometry

    native_calls = []
    geos_calls = []

    class PlanarShape:
        is_valid = True

    monkeypatch.setattr(spherical_native, "validate", lambda value: native_calls.append(value))
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: geos_calls.append(value) or PlanarShape())

    collection = decode_geometry_bounded(translator(), {
        "type": "GeometryCollection",
        "evenOdd": False,
        "geometries": [
            {"type": "Polygon", "geodesic": False, "evenOdd": True,
             "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]]},
            {"type": "Polygon", "geodesic": True,
             "coordinates": [[[3, 0], [5, 0], [5, 2], [3, 2]]]},
        ],
    })
    assert geos_calls == [collection["geometries"][0]]
    assert len(native_calls) == 1
    spherical_view = native_calls[0]
    assert spherical_view is not collection["geometries"][1]
    assert "evenOdd" not in spherical_view
    assert spherical_view.geometry_metadata["evenOdd"] is False
    assert collection["geometries"][1].geometry_metadata["evenOdd"] is True
    assert encode_geometry(spherical_view)[3] == 0


def test_constructor_defaults_and_bbox_planar_exception_are_effective_sidecars(monkeypatch):
    from gee.compat.earthengine import spherical_native

    native_calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: native_calls.append(value))

    polygon = construct_geometry_value(translator(), "Polygon", {
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]],
    })
    assert polygon.geometry_metadata == {
        "crs": "EPSG:4326", "geodesic": True, "evenOdd": True,
    }
    assert "geodesic" not in polygon
    assert "evenOdd" not in polygon

    bbox = construct_geometry_value(translator(), "BBox", {
        "west": 0, "south": 0, "east": 2, "north": 2,
    })
    assert bbox.geometry_metadata == {
        "crs": "EPSG:4326", "geodesic": False, "evenOdd": True,
    }
    assert bbox["geodesic"] is False
    assert native_calls == [polygon]


def test_linearring_constructor_closes_a_position_sequence(monkeypatch):
    from gee.compat.earthengine import spherical_native

    calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: calls.append(value))
    ring = construct_geometry_value(translator(), "LinearRing", {
        "coordinates": [[0, 0], [3, 0], [0, 3]],
    })
    assert ring["coordinates"][0] == ring["coordinates"][-1]
    assert len(ring["coordinates"]) == 4
    assert ring.geometry_metadata["geodesic"] is True
    assert calls == [ring]


def test_structure_accessor_reports_effective_spherical_flag(monkeypatch):
    from gee.compat.earthengine import spherical_native

    calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: calls.append(value))
    point = {"type": "Point", "coordinates": [1, 2]}
    assert invoke_geometry_structure(
        translator(), "Geometry.geodesic", {"geometry": point},
    ) is True
    assert invoke_geometry_structure(
        translator(), "Geometry.edgesAreGeodesics", {"geometry": point},
    ) is True
    assert len(calls) == 2


def test_spherical_validation_reserves_local_budget_before_native_call(monkeypatch):
    from gee.compat.earthengine import spherical_native
    from gee.compat.earthengine.geometry_preflight import measure_geometry
    from gee.compat.earthengine.spherical_preflight import native_work

    calls = []
    monkeypatch.setattr(spherical_native, "validate", lambda value: calls.append(value))
    raw = _rectangle()
    cost = measure_geometry(raw)
    ordinary_charge = cost.nodes + cost.positions + 3 * cost.ring_closures
    closed_positions = cost.positions + cost.ring_closures
    t = translator()
    value = decode_geometry_bounded(t, raw)
    expected = (ordinary_charge + 1 + cost.nodes + 4 * closed_positions
                + native_work(value))
    assert t.steps == expected
    assert calls == [value]

    calls.clear()
    t = translator(49_990)
    with pytest.raises(UnsupportedEEError, match="Spherical geometry validation.*50000-step"):
        decode_geometry_bounded(t, {"type": "Point", "coordinates": [0, 0]})
    assert t.steps == 49_997  # base structural reservation only
    assert calls == []
