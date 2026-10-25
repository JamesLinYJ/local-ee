"""Focused Feature measure contracts and owned centroid identity tests."""
from __future__ import annotations

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_geometry_measures import (
    invoke_feature_geometry_measures,
)
from gee.ee_translate import UnsupportedEEError


def translator(steps=0):
    value = Translator([], {}, {})
    value.steps = steps
    return value


def geodesic_polygon():
    return {
        "type": "Polygon",
        "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
    }


def feature(geometry=None):
    return {
        "type": "Feature",
        "id": "actual-feature-id",
        "geometry": geodesic_polygon() if geometry is None else geometry,
        "properties": {"system:index": "actual-feature-id", "name": "parcel"},
    }


def test_feature_scalars_call_independent_requested_native_metric(monkeypatch):
    from gee.compat.earthengine import spherical_native

    calls = []
    monkeypatch.setattr(
        spherical_native, "run_ellipsoid_measure",
        lambda _geometry, method: calls.append(method) or (1.0, 7.5),
    )
    for method in ("area", "length", "perimeter"):
        assert invoke_feature_geometry_measures(
            translator(), "Feature." + method, {"feature": feature()},
        ) == 7.5
    assert calls == ["area", "length", "perimeter"]


def test_feature_centroid_preserves_actual_id_properties_and_owns_output(monkeypatch):
    from gee.compat.earthengine import spherical_native

    monkeypatch.setattr(
        spherical_native, "run_measures",
        lambda _geometry: (1.0, 2.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0),
    )
    source = feature()
    result = invoke_feature_geometry_measures(
        translator(), "Feature.centroid", {"feature": source},
    )
    assert result["type"] == "Feature"
    assert result["id"] == "actual-feature-id"
    assert result["properties"] == {
        "system:index": "actual-feature-id", "name": "parcel",
    }
    assert result["geometry"]["coordinates"] == [0.0, 0.0]
    assert result["properties"] is not source["properties"]
    assert result["geometry"] is not source["geometry"]
    source["properties"]["name"] = "mutated"
    source["geometry"]["coordinates"][0][0][0] = 99
    assert result["properties"]["name"] == "parcel"
    assert result["geometry"]["coordinates"] == [0.0, 0.0]


def test_feature_centroid_preserves_system_index_without_fabricating_top_id(monkeypatch):
    from gee.compat.earthengine import spherical_native

    monkeypatch.setattr(
        spherical_native, "run_measures",
        lambda _geometry: (1.0, 2.0, 1.0, 1.0, 1.0, 0.0, 1.0, 0.0),
    )
    source = {
        "type": "Feature",
        "geometry": geodesic_polygon(),
        "properties": {"system:index": "index-7", "value": 3},
    }
    result = invoke_feature_geometry_measures(
        translator(), "Feature.centroid", {"feature": source},
    )
    assert "id" not in result
    assert result["properties"]["system:index"] == "index-7"
    assert result["geometry"]["coordinates"] == [90.0, 0.0]


def test_feature_null_geometry_has_zero_scalar_and_empty_centroid_rejection():
    source = {
        "type": "Feature", "id": "null-geometry",
        "geometry": None, "properties": {"system:index": "null-geometry"},
    }
    for method in ("area", "length", "perimeter"):
        assert invoke_feature_geometry_measures(
            translator(), "Feature." + method, {"feature": source},
        ) == 0.0
    with pytest.raises(UnsupportedEEError, match="highest-dimension component"):
        invoke_feature_geometry_measures(
            translator(), "Feature.centroid", {"feature": source},
        )


def test_feature_arguments_reject_unknown_fields_and_conflicting_identity():
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_feature_geometry_measures(
            translator(), "Feature.area", {"feature": feature(), "other": True},
        )
    conflict = feature()
    conflict["properties"]["system:index"] = "different"
    for method in ("area", "centroid"):
        with pytest.raises(UnsupportedEEError, match="identify different elements"):
            invoke_feature_geometry_measures(
                translator(), "Feature." + method, {"feature": conflict},
            )


def test_dispatch_and_capability_inventory_include_all_eight_measure_methods(monkeypatch):
    from gee.compat.earthengine.capabilities import SUPPORTED_FUNCTIONS, get_capabilities
    from gee.compat.earthengine.dispatch import invoke
    from gee.compat.earthengine import spherical_native

    methods = {
        f"{owner}.{method}"
        for owner in ("Geometry", "Feature")
        for method in ("area", "length", "perimeter", "centroid")
    }
    assert methods <= SUPPORTED_FUNCTIONS
    assert any("Geometry/Feature area" in item
               and "binary64 resolution guard" in item
               for item in get_capabilities()["restrictions"])
    monkeypatch.setattr(
        spherical_native, "run_ellipsoid_measure",
        lambda _geometry, metric: (1.0, 2.5),
    )
    assert invoke(
        translator(), "Geometry.area", {"geometry": geodesic_polygon()},
    ) == 2.5


def _read_feature(method, source, budget):
    if method == "id":
        from gee.compat.earthengine.feature_structure import invoke_feature_structure

        return invoke_feature_structure(budget, "Feature.id", {"element": source})
    return invoke_feature_geometry_measures(
        budget, "Feature." + method, {"feature": source},
    )


@pytest.mark.parametrize("method", ["id", "area", "length", "perimeter", "centroid"])
@pytest.mark.parametrize("invalid", [
    "oversized_key", "oversized_string", "infinite_geometry",
    "nonfinite_extension", "oversized_nested_list", "cycle",
])
def test_feature_readers_validate_complete_metadata_before_native(
        monkeypatch, method, invalid):
    from gee.compat.earthengine import spherical_native

    def forbidden(*_args):
        pytest.fail("invalid Feature reached a native measure")

    monkeypatch.setattr(spherical_native, "run_measures", forbidden)
    monkeypatch.setattr(spherical_native, "run_ellipsoid_measure", forbidden)
    source = feature()
    if invalid == "oversized_key":
        source["properties"]["k" * 50_001] = 0
    elif invalid == "oversized_string":
        source["properties"]["payload"] = "v" * 1_000_001
    elif invalid == "infinite_geometry":
        source["geometry"]["coordinates"][0][0][0] = float("inf")
    elif invalid == "nonfinite_extension":
        source["extension"] = float("nan")
    elif invalid == "oversized_nested_list":
        source["properties"]["payload"] = [0] * 10_001
    else:
        source["properties"]["self"] = source["properties"]
    budget = translator()
    with pytest.raises(UnsupportedEEError):
        _read_feature(method, source, budget)
    assert 0 <= budget.steps <= 50_000


@pytest.mark.parametrize("method", ["id", "area", "length", "perimeter", "centroid"])
def test_feature_readers_keep_exact_shared_budget_boundary(method):
    source = feature({"type": "Point", "coordinates": [1, 2]})
    calibration = translator()
    expected = _read_feature(method, source, calibration)
    cost = calibration.steps
    assert 0 < cost < 50_000

    exact = translator(50_000 - cost)
    assert _read_feature(method, source, exact) == expected
    assert exact.steps == 50_000
    one_over = translator(50_001 - cost)
    with pytest.raises(UnsupportedEEError, match="50000|limits"):
        _read_feature(method, source, one_over)


def test_feature_centroid_preserves_owned_typed_metadata_and_geometry_sidecars():
    from gee.compat.earthengine.array_core import StaticArray
    from gee.compat.earthengine.geometry_values import GeometryValue
    from gee.compat.earthengine.ir import Image, Pixel

    geometry = GeometryValue(
        {"type": "Point", "coordinates": [3, 4]},
        {"crs": "EPSG:4326", "geodesic": True, "evenOdd": True},
    )
    array = StaticArray(np.array([5.0, 6.0]))
    joined = Image([("b", Pixel("constant", (7,)))], {"nested": [8]})
    source = feature({"type": "Point", "coordinates": [1, 2]})
    source["properties"].update({"array": array, "joined": joined, "shape": geometry})

    output = _read_feature("centroid", source, translator())
    properties = output["properties"]
    assert type(properties["array"]) is StaticArray
    assert not properties["array"].data.flags.writeable
    assert type(properties["joined"]) is Image
    assert properties["joined"].bands[0][1] is joined.bands[0][1]
    assert type(properties["shape"]) is GeometryValue
    assert properties["shape"].geometry_metadata == geometry.geometry_metadata

    array.data[0] = 50
    joined.props["nested"][0] = 80
    geometry.geometry_metadata["geodesic"] = False
    geometry["coordinates"][0] = 30
    assert properties["array"].data.tolist() == [5.0, 6.0]
    assert properties["joined"].props["nested"] == [8]
    assert properties["shape"]["coordinates"] == [3, 4]
    assert properties["shape"].geometry_metadata["geodesic"] is True
    properties["joined"].props["nested"].append(9)
    properties["shape"].geometry_metadata["evenOdd"] = False
    assert joined.props["nested"] == [80]
    assert geometry.geometry_metadata["evenOdd"] is True


@pytest.mark.parametrize("method", ["id", "area", "centroid"])
@pytest.mark.parametrize("invalid", ["array", "mapped_image", "geometry_sidecar"])
def test_feature_metadata_typed_boundaries_remain_checked(method, invalid):
    from gee.compat.earthengine.array_core import StaticArray
    from gee.compat.earthengine.geometry_values import GeometryValue
    from gee.compat.earthengine.ir import Image

    source = feature({"type": "Point", "coordinates": [1, 2]})
    if invalid == "array":
        value = StaticArray(np.ones(10_001))
    elif invalid == "mapped_image":
        value = Image([], {}, mapped=True)
    else:
        value = GeometryValue(
            {"type": "Point", "coordinates": [3, 4]},
            {"crs": "EPSG:4326", "extension": float("nan")},
        )
    source["properties"]["typed"] = value
    with pytest.raises(UnsupportedEEError):
        _read_feature(method, source, translator())
