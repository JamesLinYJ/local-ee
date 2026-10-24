"""Feature.bounds ownership and official-client routing contracts."""
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_bounds import (
    GEOMETRY_BOUNDS_ARGUMENTS,
    invoke_geometry_bounds,
)
from gee.ee_translate import UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]


def translator():
    return Translator([], {}, {})


def planar_polygon():
    return {
        "type": "Polygon",
        "coordinates": [[[-5, 40], [5, 40], [5, 50], [-5, 50], [-5, 40]]],
        "geodesic": False,
    }


def test_feature_bounds_signature_and_left_identity_properties_are_owned():
    assert GEOMETRY_BOUNDS_ARGUMENTS["Feature.bounds"] == (
        frozenset({"feature"}), frozenset({"maxError", "proj"}),
    )
    feature = {
        "type": "Feature", "id": "left-1", "geometry": planar_polygon(),
        "properties": {"system:index": "left-1", "nested": {"values": [1]}},
    }
    result = invoke_geometry_bounds(translator(), "Feature.bounds", {
        "feature": feature, "maxError": 1, "proj": "EPSG:4326",
    })
    assert result["type"] == "Feature"
    assert result["id"] == "left-1"
    assert result["properties"] == feature["properties"]
    assert result["properties"] is not feature["properties"]
    assert result["properties"]["nested"] is not feature["properties"]["nested"]
    result["properties"]["nested"]["values"][0] = 9
    assert feature["properties"]["nested"]["values"] == [1]
    assert result["geometry"]["geodesic"] is False


def test_feature_bounds_retains_property_identity_without_inventing_top_level_id():
    feature = {
        "type": "Feature", "geometry": planar_polygon(),
        "properties": {"system:index": "property-id", "label": "source"},
    }
    result = invoke_geometry_bounds(
        translator(), "Feature.bounds", {"feature": feature},
    )
    assert result["properties"]["system:index"] == "property-id"
    assert "id" not in result


@pytest.mark.parametrize("feature, message", [
    ({"type": "Feature", "geometry": None, "properties": {}}, "non-null geometry"),
    ({"type": "Feature", "geometry": planar_polygon(), "properties": {"system:index": 1}},
     "system:index must be a string"),
])
def test_feature_bounds_rejects_null_geometry_and_invalid_identity(feature, message):
    with pytest.raises(UnsupportedEEError, match=message):
        invoke_geometry_bounds(
            translator(), "Feature.bounds", {"feature": feature},
        )


def test_feature_bounds_revalidates_mutated_properties_and_cycles():
    cyclic = {}
    cyclic["self"] = cyclic
    feature = {
        "type": "Feature", "geometry": planar_polygon(),
        "properties": {"nested": cyclic},
    }
    with pytest.raises(UnsupportedEEError, match="cycles"):
        invoke_geometry_bounds(translator(), "Feature.bounds", {"feature": feature})


def test_feature_bounds_preserves_the_shared_96_level_metadata_depth_limit():
    value = None
    for _ in range(94):
        value = {"child": value}
    accepted = {
        "type": "Feature", "geometry": planar_polygon(),
        "properties": {"nested": value},
    }
    result = invoke_geometry_bounds(
        translator(), "Feature.bounds", {"feature": accepted},
    )
    assert result["properties"]["nested"] == value

    value = {"child": value}
    rejected = {
        "type": "Feature", "geometry": planar_polygon(),
        "properties": {"nested": value},
    }
    with pytest.raises(UnsupportedEEError, match="depth limit"):
        invoke_geometry_bounds(
            translator(), "Feature.bounds", {"feature": rejected},
        )


def test_feature_bounds_is_in_the_empty_map_signature_preflight():
    from gee.ee_python_client import configure_local_ee
    from scripts.ee_python_api.offline import OfflineGuard

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        mapped = ee.FeatureCollection([]).map(lambda feature: feature.bounds())
        wire = ee.serializer.encode(mapped, for_cloud_api=False)
        result = compile_expression(wire, [], {})
        assert result["value"]["features"] == []
        assert guard.evidence()["attempt_count"] == 0


def test_official_feature_bounds_wire_compiles_to_owned_planar_feature():
    from gee.ee_python_client import configure_local_ee
    from scripts.ee_python_api.offline import OfflineGuard

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        source = ee.Feature(
            ee.Geometry.Polygon(
                [[[-5, 40], [5, 40], [5, 50], [-5, 50], [-5, 40]]],
                proj=ee.Projection("EPSG:4326"), geodesic=False,
            ),
            {"source": "feature-bounds"},
        )
        wire = ee.serializer.encode(
            source.bounds(maxError=1, proj=ee.Projection("EPSG:4326")),
            for_cloud_api=False,
        )
        result = compile_expression(wire, [], {})["value"]
        assert guard.evidence()["attempt_count"] == 0

    assert result["type"] == "Feature"
    assert result["properties"] == {"source": "feature-bounds"}
    assert result["geometry"]["geodesic"] is False
    assert result["geometry"]["coordinates"] == [[
        [-5, 40], [5, 40], [5, 50], [-5, 50], [-5, 40],
    ]]
