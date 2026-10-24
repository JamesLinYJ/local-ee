"""New spherical outputs must not silently enter the legacy planar masks."""
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_consumers import reject_spherical_edges
from gee.compat.earthengine.image_ops import invoke_image
from gee.compat.earthengine.ir import Image, Reducer, UnsupportedEEError, const
from gee.compat.earthengine.spherical_wire import FULL_SPHERE


def geometry(geodesic=True):
    return {"type": "Polygon", "geodesic": geodesic,
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}


@pytest.mark.parametrize("operation", ["Image.clip", "Image.reduceRegion"])
def test_raster_consumer_rejects_spherical_edges_before_geos(operation, monkeypatch):
    import shapely.geometry

    calls = []
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: calls.append(value))
    image = Image([("B1", const(1))], {})
    arguments = {"input" if operation == "Image.clip" else "image": image,
                 "geometry": geometry()}
    if operation == "Image.reduceRegion":
        arguments["reducer"] = Reducer("mean")
    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        invoke_image(Translator([], {}, {}), operation, arguments)
    assert calls == []


def test_full_sphere_clip_has_a_clear_error_instead_of_dict_attribute_error():
    with pytest.raises(UnsupportedEEError, match="full-sphere"):
        invoke_image(Translator([], {}, {}), "Image.clip", {
            "input": Image([("B1", const(1))], {}), "geometry": FULL_SPHERE,
        })


def test_legacy_planar_inputs_and_edgeless_points_keep_their_existing_route():
    translator = Translator([], {}, {})
    reject_spherical_edges(translator, geometry(False), "clip")
    reject_spherical_edges(translator, {"type": "Point", "coordinates": [1, 2],
                                        "geodesic": True}, "clip")
    assert translator.steps == 2


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
