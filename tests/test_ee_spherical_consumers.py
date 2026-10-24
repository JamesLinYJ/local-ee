"""New spherical outputs must not silently enter the legacy planar masks."""
import json

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_consumers import reject_spherical_edges
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.image_ops import invoke_image
from gee.compat.earthengine.ir import (
    Image, Pixel, Reducer, Source, UnsupportedEEError, const,
)
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.compat.earthengine.spherical_wire import FULL_SPHERE


def geometry(geodesic=True):
    return {"type": "Polygon", "geodesic": geodesic,
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}


@pytest.mark.parametrize("operation", ["Image.clip", "Image.reduceRegion"])
def test_raster_consumer_rejects_spherical_edges_before_geos(operation, monkeypatch):
    import shapely.geometry

    calls = []
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: calls.append(value))
    if operation == "Image.reduceRegion":
        image = Image([("B1", const(1))], {})
        arguments = {"image": image, "geometry": geometry()}
        arguments["reducer"] = Reducer("mean")
        with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
            invoke_image(Translator([], {}, {}), operation, arguments)
    else:
        # Image.clip now lowers default-geodesic polygons into independent
        # coverage and raw science IR. Its ordinary image output remains
        # unsupported until a mask-aware consumer proves the real grid.
        image = Image([("B1", const(1))], {})
        clipped = invoke_image(Translator([], {}, {}), operation, {
            "input": image, "geometry": geometry(),
        })
        assert isinstance(clipped, Image)
        assert clipped.clip_footprint is not None
        assert len(clipped.bands) == 1
        assert clipped.bands[0][0] == "B1"
        carrier = clipped.bands[0][1]
        assert carrier.op == "with_mask"
        raw_science, coverage = carrier.args
        assert raw_science is image.bands[0][1]
        assert coverage.op == "clip_coverage"
        assert coverage.args[0] is raw_science
        assert json.loads(coverage.args[1])["model"] == "great-circle"

        with pytest.raises(UnsupportedEEError, match="Fractional image masks require a mask-aware consumer"):
            Graph(Translator([], {}, {})).expression(carrier)
        unbound_science = Pixel(
            "band", (Source("synthetic", (), ("B1",)), "B1"),
        )
        unbound = invoke_image(Translator([], {}, {}), operation, {
            "input": Image([("B1", unbound_science)], {}),
            "geometry": geometry(),
        }).bands[0][1].args[1]
        with pytest.raises(UnsupportedEEError, match="Image.clip coverage requires a finite actual raster source and grid"):
            Graph(Translator([], {}, {})).expression(unbound)
    assert calls == []


def test_full_sphere_clip_has_a_clear_error_instead_of_dict_attribute_error():
    with pytest.raises(UnsupportedEEError, match="full-sphere"):
        invoke_image(Translator([], {}, {}), "Image.clip", {
            "input": Image([("B1", const(1))], {}), "geometry": FULL_SPHERE,
        })


def test_legacy_planar_inputs_and_edgeless_points_keep_their_existing_route():
    translator = Translator([], {}, {})
    planar = geometry(False)
    point = {"type": "Point", "coordinates": [1, 2], "geodesic": True}
    reject_spherical_edges(translator, planar, "clip")
    reject_spherical_edges(translator, point, "clip")
    from gee.compat.earthengine.geometry_preflight import measure_geometry

    expected = sum(
        cost.nodes + cost.positions
        for cost in (measure_geometry(planar), measure_geometry(point))
    )
    assert translator.steps == expected


def test_nested_public_spherical_flags_cannot_bypass_the_consumer_guard():
    value = {"type": "GeometryCollection", "geodesic": True, "geometries": [
        {key: item for key, item in geometry().items() if key != "geodesic"},
    ]}
    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        reject_spherical_edges(Translator([], {}, {}), value, "filter")
    value["geometries"][0]["geodesic"] = False
    reject_spherical_edges(Translator([], {}, {}), value, "filter")


def test_consumer_flag_inspection_is_finite_and_charged():
    translator = Translator([], {}, {})
    translator.steps = 50_000
    with pytest.raises(UnsupportedEEError, match="50000"):
        reject_spherical_edges(translator, geometry(False), "clip")
    cyclic = {"type": "GeometryCollection", "geometries": []}
    cyclic["geometries"].append(cyclic)
    with pytest.raises(UnsupportedEEError, match="finite nesting"):
        reject_spherical_edges(Translator([], {}, {}), cyclic, "clip")


def test_typed_sidecar_models_are_resolved_but_points_and_empty_values_are_neutral():
    typed_spherical = GeometryValue(
        {key: value for key, value in geometry().items() if key != "geodesic"},
        {"geodesic": True}, validated=True,
    )
    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        reject_spherical_edges(Translator([], {}, {}), typed_spherical, "clip")

    point = GeometryValue(
        {"type": "Point", "coordinates": [1, 2]}, {"geodesic": True},
        validated=True,
    )
    empty_collection = GeometryValue(
        {"type": "GeometryCollection", "geometries": []},
        {"geodesic": True}, validated=True,
    )
    empty_multi = GeometryValue(
        {"type": "MultiPolygon", "coordinates": []}, {"geodesic": True},
        validated=True,
    )
    for value in (point, empty_collection, empty_multi):
        reject_spherical_edges(Translator([], {}, {}), value, "clip")


def test_untyped_unflagged_geojson_keeps_the_legacy_planar_default():
    raw = {key: value for key, value in geometry().items() if key != "geodesic"}
    reject_spherical_edges(Translator([], {}, {}), raw, "clip")


def test_feature_collection_geometry_route_imports_and_uses_shared_guard():
    translator = Translator([], {}, {})
    original = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": {
            key: value for key, value in geometry(False).items()
            if key != "geodesic"
        }}],
    }
    # This original predecoded EE value used to take the catalog's planar
    # default. It has no catalog provenance, so its default edges are spherical.
    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        translator.footprint(original)
    assert "geodesic" not in original["features"][0]["geometry"]


def test_feature_collection_explicit_planar_footprint_uses_shared_guard():
    translator = Translator([], {}, {})
    result = translator.footprint({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": geometry(False)}],
    })
    assert result["type"] == "Polygon"
    assert result["geodesic"] is False
