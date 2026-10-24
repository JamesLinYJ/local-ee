"""Derived empty footprints remain actual empty sets and leave sources intact."""
import copy

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.filter_metadata import matches_filter
from gee.compat.earthengine.ir import Collection, Filter, Image, Source, UnsupportedEEError


def _square(west, east):
    return {"type": "Polygon", "coordinates": [
        [[west, 0], [east, 0], [east, 1], [west, 1], [west, 0]],
    ]}


@pytest.mark.parametrize("west,east,empty", [(0, 1, False), (3, 4, True)])
def test_clip_derived_catalog_footprint_uses_canonical_empty_geometry(west, east, empty):
    item = {"id": "a", "geometry": _square(west, east), "properties": {"actual": 1}}
    snapshot = copy.deepcopy(item)
    source = Source("local", ("a",), ())
    image = Image([], {}, source, footprint={**_square(0, 1), "geodesic": False})
    translator = Translator([], {"local": [item]}, {})
    rows = translator.collection_items(Collection(source, image))
    assert item == snapshot
    assert len(rows) == 1 and rows[0]["properties"] == item["properties"]
    if empty:
        assert rows[0]["geometry"]["type"] == "GeometryCollection"
        assert rows[0]["geometry"]["geometries"] == []
    predicate = Filter("intersects", {
        "leftField": ".all", "rightValue": {**_square(0, 1), "geodesic": False},
    })
    assert matches_filter(translator, predicate, rows[0]) is not empty
    if empty:
        # An empty set has no curve model; it does not create a mixed-model
        # transform or turn a default-spherical ROI into a successful match.
        spherical = Filter("intersects", {"leftField": ".all", "rightValue": _square(0, 1)})
        assert matches_filter(translator, spherical, rows[0]) is False


@pytest.mark.parametrize("clipped", [False, True])
@pytest.mark.parametrize("geometry", [
    {"type": "Polygon", "coordinates": []},
    {"type": "LineString", "coordinates": []},
    {"type": "Point", "coordinates": [3, 100]},
    {"type": "Point", "coordinates": [3, float("nan")]},
    {"type": "Point", "coordinates": [3, float("inf")]},
    {"type": "Point", "coordinates": [True, 0]},
    {**_square(3, 4), "crs": {"type": "name", "properties": {"name": "EPSG:3857"}}},
    {"type": "Polygon", "coordinates": [[[3, 0], [4, 1], [3, 1], [4, 0], [3, 0]]]},
])
def test_invalid_original_source_cannot_be_hidden_by_empty_clip(geometry, clipped):
    item = {"id": "a", "geometry": geometry, "properties": {}}
    source = Source("local", ("a",), ())
    footprint = {**_square(0, 1), "geodesic": False} if clipped else None
    translator = Translator([], {"local": [item]}, {})
    collection = Collection(source, Image([], {}, source, footprint=footprint))
    with pytest.raises(UnsupportedEEError):
        rows = translator.collection_items(collection)
        matches_filter(translator, Filter("intersects", {
            "leftField": ".all", "rightValue": {**_square(0, 1), "geodesic": False},
        }), rows[0])


@pytest.mark.parametrize("empty_catalog", [False, True])
def test_known_spherical_clip_model_rejects_before_any_catalog_rows(empty_catalog):
    from gee.compat.earthengine.geometry_values import decode_geometry_bounded

    item = {"id": "a", "geometry": _square(0, 1), "properties": {}}
    translator = Translator([], {"local": [item]}, {})
    source = Source("local", () if empty_catalog else ("a",), ())
    clip = decode_geometry_bounded(translator, _square(0, 1))
    with pytest.raises(UnsupportedEEError, match="spherical geometry edges"):
        translator.collection_items(Collection(source, Image([], {}, source, footprint=clip)))


@pytest.mark.parametrize("clip", [
    {"type": "Point", "coordinates": [0, 0]},
    {"type": "GeometryCollection", "geometries": []},
])
def test_no_edge_clip_does_not_invent_a_curve_model_on_empty_catalog(clip):
    from gee.compat.earthengine.geometry_values import decode_geometry_bounded

    translator = Translator([], {"local": []}, {})
    source = Source("local", (), ())
    owned = decode_geometry_bounded(translator, clip)
    assert translator.collection_items(Collection(source, Image([], {}, source, footprint=owned))) == []
