"""Service export, query and Feature routes for EE regions."""
from __future__ import annotations

import copy

import pytest

from gee.ee_translate import UnsupportedEEError
from gee.services import ee as ee_service
from scripts.ee_python_api.probe_cases import synthetic_inputs
from ee_region_support import (
    _polygon, _service_export_probe, sdk, _without_native_s2_validation,
)


@pytest.mark.parametrize("model", ["default", "explicit_spherical"])
def test_export_image_rejects_spherical_region_before_shape_budget_or_job(
    sdk, monkeypatch, model,
):
    _without_native_s2_validation(monkeypatch)
    import shapely.geometry

    shape_calls = []
    monkeypatch.setattr(
        shapely.geometry, "shape",
        lambda value: shape_calls.append(value),
    )
    state, expression, account = _service_export_probe(monkeypatch, sdk)
    coordinates = [[100, 30], [101, 30], [101, 31], [100, 30]]
    region = (
        sdk.Geometry.Polygon([coordinates])
        if model == "default"
        else sdk.Geometry.Polygon([coordinates], geodesic=True)
    )
    wire = sdk.serializer.encode(region, for_cloud_api=False)
    before = copy.deepcopy(wire)

    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        ee_service.dispatch(None, account, {
            "action": "export_image", "expression": expression,
            "options": {"region": wire, "scale": 10},
        })

    assert wire == before
    assert shape_calls == []
    assert state["pixel"] == []
    assert state["jobs"] == []


def test_explicit_planar_export_region_keeps_model_and_reaches_mock_job(sdk, monkeypatch):
    _without_native_s2_validation(monkeypatch)
    state, expression, account = _service_export_probe(monkeypatch, sdk)
    coordinates = [[100, 30], [101, 30], [101, 31], [100, 30]]
    region = sdk.Geometry.Polygon([coordinates], geodesic=False, evenOdd=True)
    wire = sdk.serializer.encode(region, for_cloud_api=False)
    before = copy.deepcopy(wire)
    coordinates_before = copy.deepcopy(coordinates)

    result = ee_service.dispatch(None, account, {
        "action": "export_image", "expression": expression,
        "options": {"region": wire, "scale": 10},
    })

    assert result["job_id"] == "synthetic"
    assert len(state["pixel"]) == len(state["jobs"]) == 1
    region_option = state["pixel"][0][1]["region"]
    assert region_option["type"] == "Polygon"
    assert region_option["geodesic"] is False
    assert region_option["evenOdd"] is True
    assert [
        [list(point) for point in polygon]
        for polygon in region_option["coordinates"]
    ] == [coordinates_before]
    assert coordinates == coordinates_before
    assert wire == before


@pytest.mark.parametrize(
    ("region_value", "message"),
    [
        ({**_polygon(False), "evenOdd": False}, "evenOdd=false"),
        (
            {
                **_polygon(False),
                "crs": {
                    "type": "name",
                    "properties": {"name": "EPSG:3857"},
                },
            },
            "Only EPSG:4326",
        ),
    ],
)
def test_export_image_freshly_revalidates_dictionary_region_before_work(
    sdk, monkeypatch, region_value, message,
):
    import shapely.geometry

    shape_calls = []
    monkeypatch.setattr(
        shapely.geometry, "shape",
        lambda value: shape_calls.append(value),
    )
    state, expression, account = _service_export_probe(monkeypatch, sdk)
    region = sdk.Dictionary({"roi": region_value}).get("roi")
    wire = sdk.serializer.encode(region, for_cloud_api=False)

    with pytest.raises(UnsupportedEEError, match=message):
        ee_service.dispatch(None, account, {
            "action": "export_image", "expression": expression,
            "options": {"region": wire, "scale": 10},
        })

    assert shape_calls == []
    assert state["pixel"] == []
    assert state["jobs"] == []


def test_map_view_region_uses_same_spherical_query_boundary(sdk, monkeypatch):
    _without_native_s2_validation(monkeypatch)
    metadata, items, _ = synthetic_inputs()
    monkeypatch.setattr(
        ee_service, "catalog_snapshot", lambda: ([metadata], items),
    )
    events = []
    monkeypatch.setattr(ee_service, "record_event", lambda _account, event: events.append(event))
    region = sdk.Geometry.Polygon([[[100, 30], [101, 30], [101, 31], [100, 30]]])
    wire = sdk.serializer.encode(region, for_cloud_api=False)

    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        ee_service.dispatch(None, {"user_id": "synthetic-user", "scope": "user"}, {
            "action": "map_view", "options": {"geometry": wire},
        })
    assert events == []


def test_feature_region_unwrap_is_non_mutating_and_keeps_planar_metadata(monkeypatch):
    _without_native_s2_validation(monkeypatch)
    feature = {
        "type": "Feature",
        "geometry": _polygon(False),
        "properties": {"tag": "immutable", "values": [1, 2]},
    }
    before = copy.deepcopy(feature)

    result = ee_service.geometry(feature, [], {})

    assert result["geodesic"] is False
    assert feature == before
