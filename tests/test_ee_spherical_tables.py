"""Spherical semantics at the trusted literal Feature CSV boundary."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from gee import table_spherical_geometry
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.compat.earthengine.spherical_preflight import native_work
from gee.compat.earthengine.spherical_wire import FULL_SPHERE
from gee.table_values import TableValueError, columns, render_csv


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ee_sdk():
    from gee.ee_python_client import configure_local_ee

    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2",
        "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def _feature(geometry):
    return {"type": "Feature", "geometry": geometry, "properties": {}}


def _collection(*geometries):
    return {"type": "FeatureCollection", "features": [_feature(item) for item in geometries]}


def test_raw_unflagged_geojson_keeps_planar_policy_but_explicit_sphere_uses_s2(monkeypatch):
    calls = []
    monkeypatch.setattr(table_spherical_geometry.spherical_native, "validate", calls.append)
    plain = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    columns(_collection(plain))
    assert calls == []

    spherical = {**plain, "geodesic": True}
    rendered = render_csv(_collection(spherical))
    assert calls == [{
        "type": "LineString", "coordinates": [[0, 0], [1, 1]],
        "geodesic": True, "evenOdd": True,
    }]
    assert json.loads(list(csv.reader(rendered.splitlines()))[1][1]) == spherical


def test_typed_default_sphere_and_evenodd_sidecar_are_preserved_without_geos(monkeypatch):
    geometry = GeometryValue(
        {"type": "Polygon", "coordinates": [[
            [0, 0], [1, 0], [1, 1], [0, 0],
        ]]},
        {"geodesic": True, "evenOdd": False},
    )
    s2_calls = []
    monkeypatch.setattr(table_spherical_geometry.spherical_native, "validate", s2_calls.append)

    import shapely.geometry

    def geos_is_forbidden(_geometry):
        raise AssertionError("spherical coordinates reached GEOS")

    monkeypatch.setattr(shapely.geometry, "shape", geos_is_forbidden)
    rendered = render_csv(_collection(geometry))
    public = json.loads(list(csv.reader(rendered.splitlines()))[1][1])
    assert public["geodesic"] is True
    assert public["evenOdd"] is False
    assert s2_calls == [{
        "type": "Polygon", "coordinates": geometry["coordinates"],
        "geodesic": True, "evenOdd": False,
    }]


def test_typed_geometry_defaults_to_sphere_even_when_flags_are_absent(monkeypatch):
    geometry = GeometryValue({"type": "Point", "coordinates": [12, 34]})
    calls = []
    monkeypatch.setattr(table_spherical_geometry.spherical_native, "validate", calls.append)
    rendered = render_csv(_collection(geometry))
    assert calls == [{
        "type": "Point", "coordinates": [12, 34], "geodesic": True, "evenOdd": True,
    }]
    public = json.loads(list(csv.reader(rendered.splitlines()))[1][1])
    assert public == {"type": "Point", "coordinates": [12, 34]}


def test_native_point_line_and_polygon_geojson_roundtrip_through_pinned_sdk(ee_sdk):
    empty = {"type": "GeometryCollection", "geometries": []}
    inputs = [
        {"type": "Point", "coordinates": [12, 34]},
        {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
    ]
    expected_flags = {
        "Point": set(),
        "LineString": {"geodesic"},
        "Polygon": {"geodesic", "evenOdd"},
    }

    for source in inputs:
        native = table_spherical_geometry.spherical_native.run(
            "union", source, empty, output_positions=100, output_children=100,
        )
        rendered = render_csv(_collection(native))
        public = json.loads(list(csv.reader(rendered.splitlines()))[1][1])
        kind = source["type"]
        assert public["type"] == kind
        assert set(public) - {"type", "coordinates"} == expected_flags[kind]

        # Constructing and cloud-encoding the parsed CSV geometry exercises
        # the actual SDK constructor signature, not a hand-written allowlist.
        geometry = ee_sdk.Geometry(json.loads(json.dumps(public)))
        assert geometry.toGeoJSON() == public
        encoded = ee_sdk.serializer.encode(geometry, for_cloud_api=True)
        invocation = encoded["values"][encoded["result"]]["functionInvocationValue"]
        assert invocation["functionName"] == f"GeometryConstructors.{kind}"
        assert set(invocation["arguments"]) == {"coordinates", *expected_flags[kind]}


def test_collection_evenodd_is_carried_by_polygon_children_for_sdk_roundtrip(ee_sdk):
    polygon = GeometryValue(
        {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        {"geodesic": True, "evenOdd": True},
    )
    collection = GeometryValue(
        {"type": "GeometryCollection", "geometries": [polygon]},
        {"geodesic": True, "evenOdd": False},
    )
    rendered = render_csv(_collection(collection))
    public = json.loads(list(csv.reader(rendered.splitlines()))[1][1])
    assert public["geodesic"] is True
    assert "evenOdd" not in public
    assert public["geometries"][0]["evenOdd"] is False
    assert "geodesic" not in public["geometries"][0]

    geometry = ee_sdk.Geometry(json.loads(json.dumps(public)))
    encoded = ee_sdk.serializer.encode(geometry, for_cloud_api=True)
    invocation = encoded["values"][encoded["result"]]["functionInvocationValue"]
    assert invocation["functionName"] == "GeometryConstructors.MultiGeometry"
    assert set(invocation["arguments"]) == {"geometries", "geodesic"}
    child = invocation["arguments"]["geometries"]["arrayValue"]["values"][0]
    child_invocation = child["functionInvocationValue"]
    assert child_invocation["functionName"] == "GeometryConstructors.Polygon"
    assert set(child_invocation["arguments"]) == {"coordinates", "evenOdd"}


def test_mixed_collection_validates_each_component_without_geos_spherical_input(monkeypatch):
    spherical = {"type": "LineString", "coordinates": [[0, 0], [1, 1]], "geodesic": True}
    planar = {"type": "LineString", "coordinates": [[2, 2], [3, 3]], "geodesic": False}
    native_calls = []
    geos_calls = []
    monkeypatch.setattr(table_spherical_geometry.spherical_native, "validate", native_calls.append)

    import shapely.geometry

    def geos_shape(geometry):
        geos_calls.append(geometry)
        return shapely.geometry.LineString(geometry["coordinates"])

    monkeypatch.setattr(shapely.geometry, "shape", geos_shape)
    columns(_collection({"type": "GeometryCollection", "geometries": [spherical, planar]}))
    assert native_calls == [{
        "type": "LineString", "coordinates": spherical["coordinates"],
        "geodesic": True, "evenOdd": True,
    }]
    assert geos_calls == [planar]


def test_spherical_curve_bbox_uses_conservative_world_extent(monkeypatch):
    monkeypatch.setattr(table_spherical_geometry.spherical_native, "validate", lambda _geometry: None)
    curve = {
        "type": "LineString", "coordinates": [[0, 0], [1, 1]], "geodesic": True,
    }
    curve["bbox"] = [-180, -90, 180, 90]
    columns(_collection(curve))
    curve["bbox"] = [0, 0, 1, 1]
    with pytest.raises(TableValueError, match="enclose"):
        columns(_collection(curve))


def test_table_spherical_work_uses_native_cost_and_is_aggregated_before_native(monkeypatch):
    geometries = [
        GeometryValue({
            "type": "Polygon",
            "coordinates": [[
                [0, 0], [3, 0], [3, 2], [0, 0],
            ]],
        }),
        GeometryValue({
            "type": "Polygon",
            "coordinates": [[
                [4, 4], [6, 4], [6, 5], [5, 6], [4, 4],
            ]],
        }),
    ]
    costs = [native_work(geometry) for geometry in geometries]
    assert all(cost > native_work(GeometryValue({"type": "Point", "coordinates": [1, 1]}))
               for cost in costs)
    monkeypatch.setattr(
        table_spherical_geometry, "MAX_SPHERICAL_TABLE_WORK", sum(costs) - 1,
    )
    calls = []
    monkeypatch.setattr(table_spherical_geometry.spherical_native, "validate", calls.append)
    with pytest.raises(TableValueError, match="shared 50000-step table work budget"):
        columns(_collection(*geometries))
    assert calls == []


def test_malformed_later_sibling_is_rejected_before_earlier_s2_component(monkeypatch):
    calls = []
    monkeypatch.setattr(table_spherical_geometry.spherical_native, "validate", calls.append)
    good = {"type": "Point", "coordinates": [1, 2], "geodesic": True}
    malformed = {
        "type": "Polygon", "geodesic": True,
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1]]],
    }
    collection = {
        "type": "GeometryCollection",
        "geometries": [good, malformed],
    }
    with pytest.raises(TableValueError, match="rings must be closed"):
        columns(_collection(collection))
    assert calls == []


def test_full_sphere_has_no_public_csv_geojson_encoding():
    with pytest.raises(TableValueError, match="FullSphere.*public GeoJSON CSV"):
        render_csv(_collection(FULL_SPHERE))


def test_explicit_spherical_geojson_without_adapter_fails_closed(monkeypatch):
    def missing_adapter(_geometry):
        raise table_spherical_geometry.UnsupportedEEError("S2 adapter is unavailable")

    monkeypatch.setattr(table_spherical_geometry.spherical_native, "validate", missing_adapter)
    geometry = {"type": "Point", "coordinates": [1, 2], "geodesic": True}
    with pytest.raises(TableValueError, match="S2 adapter is unavailable"):
        columns(_collection(geometry))
