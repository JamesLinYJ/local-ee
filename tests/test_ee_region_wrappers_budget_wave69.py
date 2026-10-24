"""Feature wrapper policy and precharged EE region mapping."""
from __future__ import annotations

import copy

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_preflight import MAX_GEOMETRY_WORK
from gee.compat.earthengine.geometry_regions import own_ee_region
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.services import ee as ee_service
from ee_region_support import (
    _polygon, _service_export_probe, sdk, synthetic_inputs,
    _without_native_s2_validation,
)


@pytest.mark.parametrize(
    "wrapper_fields",
    [
        {"geodesic": True},
        {"geodesic": False},
        {"evenOdd": False},
        {"crs": {"type": "name", "properties": {"name": "EPSG:3857"}}},
    ],
)
def test_sdk_feature_wrapper_model_fields_reject_before_geos(
    sdk, monkeypatch, wrapper_fields,
):
    _without_native_s2_validation(monkeypatch)
    import shapely.geometry

    shape_calls = []
    monkeypatch.setattr(
        shapely.geometry, "shape", lambda value: shape_calls.append(value),
    )
    feature = {
        "type": "Feature", "geometry": _polygon(False),
        "properties": {}, **wrapper_fields,
    }
    wrapped = sdk.Feature(sdk.Dictionary({"roi": feature}).get("roi"))
    wire = sdk.serializer.encode(
        sdk.Image.constant(1).clip(wrapped), for_cloud_api=False,
    )

    with pytest.raises(UnsupportedEEError, match="Feature wrappers"):
        compile_expression(wire, [], {})
    assert shape_calls == []
    assert feature["geometry"]["geodesic"] is False


def test_sdk_feature_child_model_remains_authoritative(sdk, monkeypatch):
    _without_native_s2_validation(monkeypatch)
    metadata, items, _ = synthetic_inputs()
    child_planar = {
        "type": "Feature", "geometry": _polygon(False), "properties": {},
    }
    wrapped_planar = sdk.Feature(
        sdk.Dictionary({"roi": child_planar}).get("roi"),
    )
    planar = compile_expression(
        sdk.serializer.encode(
            sdk.ImageCollection("sentinel-2-l2a").first().select("nir").clip(
                wrapped_planar,
            ),
            for_cloud_api=False,
        ),
        [metadata], items,
    )
    assert planar["kind"] == "image"

    # A wrapper-level false model is not allowed to planarize the child's EE
    # default. It is rejected by the local unsupported-wrapper policy.
    wrapper_false = {
        "type": "Feature", "geometry": _polygon(), "properties": {},
        "geodesic": False,
    }
    wrapped_spherical = sdk.Feature(
        sdk.Dictionary({"roi": wrapper_false}).get("roi"),
    )
    with pytest.raises(UnsupportedEEError, match="Feature wrappers"):
        compile_expression(
            sdk.serializer.encode(
                sdk.ImageCollection("sentinel-2-l2a").first().select("nir").clip(
                    wrapped_spherical,
                ),
                for_cloud_api=False,
            ),
            [metadata], items,
        )


@pytest.mark.parametrize("field", ["geodesic", "evenOdd", "crs"])
def test_service_feature_wrapper_model_fields_reject_before_geos(monkeypatch, field):
    _without_native_s2_validation(monkeypatch)
    import shapely.geometry

    shape_calls = []
    monkeypatch.setattr(
        shapely.geometry, "shape", lambda value: shape_calls.append(value),
    )
    feature = {
        "type": "Feature", "geometry": _polygon(False), "properties": {},
        field: False if field != "crs" else {
            "type": "name", "properties": {"name": "EPSG:3857"},
        },
    }
    with pytest.raises(UnsupportedEEError, match="Feature wrappers"):
        ee_service.geometry(feature, [], {})
    assert shape_calls == []


def test_service_direct_feature_default_model_and_properties_are_checked(monkeypatch):
    _without_native_s2_validation(monkeypatch)
    import shapely.geometry

    shape_calls = []
    monkeypatch.setattr(
        shapely.geometry, "shape", lambda value: shape_calls.append(value),
    )
    feature = {
        "type": "Feature", "geometry": _polygon(),
        "properties": {"tag": "preserved", "values": [1, 2]},
    }
    before = copy.deepcopy(feature)
    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        ee_service.geometry(feature, [], {})
    assert shape_calls == []
    assert feature == before


def test_service_export_rejects_feature_wrapper_flags_before_budget_or_job(
    sdk, monkeypatch,
):
    _without_native_s2_validation(monkeypatch)
    import shapely.geometry

    shape_calls = []
    monkeypatch.setattr(
        shapely.geometry, "shape", lambda value: shape_calls.append(value),
    )
    state, expression, account = _service_export_probe(monkeypatch, sdk)
    feature = {
        "type": "Feature", "geometry": _polygon(False), "properties": {},
        "geodesic": True,
    }
    before = copy.deepcopy(feature)

    with pytest.raises(UnsupportedEEError, match="Feature wrappers"):
        ee_service.dispatch(None, account, {
            "action": "export_image", "expression": expression,
            "options": {"region": feature, "scale": 10},
        })

    assert shape_calls == []
    assert state["pixel"] == []
    assert state["jobs"] == []
    assert feature == before


def test_service_export_accepts_feature_child_explicit_planar_model(sdk, monkeypatch):
    _without_native_s2_validation(monkeypatch)
    state, expression, account = _service_export_probe(monkeypatch, sdk)
    feature = {
        "type": "Feature", "geometry": _polygon(False),
        "properties": {"tag": "metadata-is-not-mutated"},
    }
    before = copy.deepcopy(feature)

    result = ee_service.dispatch(None, account, {
        "action": "export_image", "expression": expression,
        "options": {"region": feature, "scale": 10},
    })

    assert result["job_id"] == "synthetic"
    assert state["pixel"] and state["jobs"]
    region_option = state["pixel"][0][1]["region"]
    assert region_option["type"] == "Polygon"
    assert region_option["geodesic"] is False
    assert feature == before


def test_region_mapping_is_precharged_and_exactly_budgeted(monkeypatch):
    _without_native_s2_validation(monkeypatch)
    import gee.compat.earthengine.geometry_regions as region_helpers

    source = _polygon(False)
    original_mapping = region_helpers.public_geometry_mapping
    observed_steps = []

    def record_mapping(value, **kwargs):
        observed_steps.append(active["translator"].steps)
        return original_mapping(value, **kwargs)

    current = Translator([], {}, {})
    active = {"translator": current}
    monkeypatch.setattr(region_helpers, "public_geometry_mapping", record_mapping)
    own_ee_region(current, copy.deepcopy(source), "budget probe",
                  strip_inferred_even_odd=True)
    reserved_work = current.steps
    assert observed_steps == [reserved_work]

    observed_steps.clear()
    underfunded = Translator([], {}, {})
    underfunded.steps = MAX_GEOMETRY_WORK - reserved_work + 1
    active["translator"] = underfunded
    with pytest.raises(UnsupportedEEError, match="50000-step.*budget"):
        own_ee_region(underfunded, copy.deepcopy(source), "budget probe",
                      strip_inferred_even_odd=True)
    assert observed_steps == []

    exact = Translator([], {}, {})
    exact.steps = MAX_GEOMETRY_WORK - reserved_work
    active["translator"] = exact
    own_ee_region(exact, copy.deepcopy(source), "budget probe",
                  strip_inferred_even_odd=True)
    assert exact.steps == MAX_GEOMETRY_WORK
    assert observed_steps == [MAX_GEOMETRY_WORK]


def test_ee_region_mixed_collection_keeps_typed_child_model(monkeypatch):
    _without_native_s2_validation(monkeypatch)
    typed_spherical = GeometryValue(_polygon(), {"geodesic": True}, validated=True)
    source = {
        "type": "GeometryCollection",
        "geometries": [_polygon(False), typed_spherical],
    }
    before = copy.deepcopy(source)

    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        own_ee_region(Translator([], {}, {}), source, "EE region")

    assert source == before
    assert typed_spherical.geometry_metadata == {"geodesic": True}
