"""Spherical defaults and catalog provenance at EE region boundaries."""
from __future__ import annotations

import copy

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_consumers import reject_spherical_edges
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.probe_cases import synthetic_inputs
from ee_region_support import _polygon, sdk, _without_native_s2_validation


def test_consumer_default_is_contextual_and_typed_children_keep_their_model():
    raw = _polygon()
    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        reject_spherical_edges(
            Translator([], {}, {}), raw, "EE region", default_geodesic=True,
        )

    # Historical internal raw values remain planar when their caller has
    # established catalog provenance, while an explicit false flag is valid.
    reject_spherical_edges(Translator([], {}, {}), raw, "catalog region")
    reject_spherical_edges(
        Translator([], {}, {}), _polygon(False), "EE region",
        default_geodesic=True,
    )

    typed_child = GeometryValue(_polygon(), {"geodesic": True}, validated=True)
    container = {"type": "GeometryCollection", "geometries": [typed_child]}
    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        reject_spherical_edges(Translator([], {}, {}), container, "catalog region")

    planar_child = GeometryValue(_polygon(), {"geodesic": False}, validated=True)
    reject_spherical_edges(
        Translator([], {}, {}),
        {"type": "GeometryCollection", "geometries": [planar_child]},
        "EE region", default_geodesic=True,
    )
    for edge_less in (
        {"type": "Point", "coordinates": [100, 30], "geodesic": True},
        {"type": "MultiPolygon", "coordinates": [], "geodesic": True},
        {"type": "GeometryCollection", "geometries": [], "geodesic": True},
    ):
        reject_spherical_edges(
            Translator([], {}, {}), edge_less, "EE region",
            default_geodesic=True,
        )


def test_catalog_default_is_applied_to_raw_edge_leaves_not_typed_children(monkeypatch):
    _without_native_s2_validation(monkeypatch)
    from gee.compat.earthengine.spatial_filters import _own_catalog_geometry

    typed = GeometryValue(_polygon(), {"geodesic": True}, validated=True)
    source = {
        "type": "GeometryCollection",
        "geometries": [_polygon(), typed],
    }
    before = copy.deepcopy(source)
    owned = _own_catalog_geometry(Translator([], {}, {}), source)

    assert owned["geometries"][0]["geodesic"] is False
    assert "geodesic" not in owned
    assert owned["geometries"][1].geometry_metadata["geodesic"] is True
    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        reject_spherical_edges(Translator([], {}, {}), owned, "catalog region")
    assert source == before
    assert typed.geometry_metadata == {"geodesic": True}


def test_collection_footprint_keeps_raw_stac_leaf_default_planar():
    metadata, items, _ = synthetic_inputs()
    translator = Translator([metadata], items, {})
    collection = translator.load("sentinel-2-l2a")

    footprint = translator.footprint(collection)

    assert footprint["type"] == "Polygon"
    assert footprint["geodesic"] is False


def test_sdk_dictionary_get_and_set_cannot_hide_default_spherical_region(sdk, monkeypatch):
    _without_native_s2_validation(monkeypatch)
    import shapely.geometry

    shape_calls = []
    monkeypatch.setattr(
        shapely.geometry, "shape",
        lambda value: shape_calls.append(value),
    )
    ring = [[100, 30], [101, 30], [101, 31], [100, 30]]
    ring_before = copy.deepcopy(ring)
    typed_child = sdk.Geometry.Polygon([ring])
    raw_child = _polygon()
    collection = {
        "type": "GeometryCollection",
        "geometries": [typed_child],
    }
    regions = [
        sdk.Geometry(sdk.Dictionary({"roi": raw_child}).get("roi")),
        sdk.Geometry(sdk.Dictionary({"roi": collection}).get("roi")),
        sdk.Geometry(sdk.Dictionary({}).set("roi", typed_child).get("roi")),
    ]

    for index, region in enumerate(regions):
        image = sdk.Image.constant(1)
        if index == 0:
            expression = image.clip(region)
        else:
            expression = image.reduceRegion(sdk.Reducer.mean(), region, 100)
        wire = sdk.serializer.encode(expression, for_cloud_api=False)
        with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
            compile_expression(wire, [], {})

    assert shape_calls == []
    assert ring == ring_before


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
@pytest.mark.parametrize("operation", ["clip", "reduceRegion"])
def test_dictionary_get_regions_are_freshly_revalidated_before_raster_use(
    sdk, monkeypatch, region_value, message, operation,
):
    import shapely.geometry

    shape_calls = []
    monkeypatch.setattr(
        shapely.geometry, "shape",
        lambda value: shape_calls.append(value),
    )
    image = sdk.Image.constant(1)
    region = sdk.Geometry(sdk.Dictionary({"roi": region_value}).get("roi"))
    expression = (
        image.clip(region)
        if operation == "clip"
        else image.reduceRegion(sdk.Reducer.mean(), region, 100)
    )
    wire = sdk.serializer.encode(expression, for_cloud_api=False)

    with pytest.raises(UnsupportedEEError, match=message):
        compile_expression(wire, [], {})

    assert shape_calls == []
