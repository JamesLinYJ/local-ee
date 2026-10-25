"""Geometry result reuse retains numeric, ownership and validation boundaries."""
from copy import deepcopy
import math

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_geometry_measures import invoke_feature_geometry_measures
from gee.compat.earthengine.geometry_components import decode_component_geometry_bounded
from gee.compat.earthengine.geometry_measures import invoke_geometry_measures
from gee.compat.earthengine.geometry_values import GeometryValue, decode_geometry_bounded
from gee.ee_translate import UnsupportedEEError


def translator():
    return Translator([], {}, {})


def polygon(*, geodesic=False):
    return {"type": "Polygon", "geodesic": geodesic,
            "coordinates": [[[0, 0], [4, 0], [4, 2], [0, 2], [0, 0]]]}


def measure(t, method, value, *, planar=True, **options):
    args = {"geometry": value, **options}
    if planar:
        args["proj"] = "EPSG:4326"
    return invoke_geometry_measures(t, "Geometry." + method, args)


def test_same_content_geometry_and_feature_share_only_successful_selected_kernel(monkeypatch):
    from gee.compat.earthengine import spherical_native

    calls, trust = [], []
    monkeypatch.setattr(spherical_native, "run_ellipsoid_measure",
                        lambda _g, method: calls.append(method) or (1.0, 7.25))
    monkeypatch.setattr(spherical_native, "_load", lambda: trust.append(True))
    t, source = translator(), polygon(geodesic=True)
    assert measure(t, "area", source, planar=False) == 7.25
    feature = {"type": "Feature", "geometry": deepcopy(source), "properties": {}}
    assert invoke_feature_geometry_measures(t, "Feature.area", {"feature": feature}) == 7.25
    assert measure(t, "length", source, planar=False) == 7.25
    assert calls == ["area", "length"]
    assert trust == [True]
    assert len(next(iter(t._geometry_measure_cache.buckets.values()))[0].results) == 2


def test_native_result_hit_rechecks_trust_and_reserves_output_before_loading(monkeypatch):
    from gee.compat.earthengine import spherical_native

    t, source = translator(), polygon(geodesic=True)
    monkeypatch.setattr(spherical_native, "run_ellipsoid_measure", lambda *_: (1.0, 2.0))
    assert measure(t, "area", source, planar=False) == 2.0
    observed = []
    monkeypatch.setattr(spherical_native, "_load", lambda: observed.append(t.steps))
    before = t.steps
    assert measure(t, "area", source, planar=False) == 2.0
    hit_work = t.steps - before
    t.steps = 50_000 - hit_work
    assert measure(t, "area", source, planar=False) == 2.0
    assert observed[-1] == t.steps == 50_000
    t.steps = 50_001 - hit_work
    with pytest.raises(UnsupportedEEError, match="50000"):
        measure(t, "area", source, planar=False)
    assert len(observed) == 2
    t.steps = 0

    def stale():
        raise UnsupportedEEError("Pinned spherical artifact changed")

    monkeypatch.setattr(spherical_native, "_load", stale)
    with pytest.raises(UnsupportedEEError, match="artifact changed"):
        measure(t, "area", source, planar=False)


def test_planar_scalar_hit_keeps_int_zero_and_does_not_require_native(monkeypatch):
    from gee.compat.earthengine import spherical_native

    monkeypatch.setattr(spherical_native, "_load", lambda: pytest.fail("planar result loaded S2"))
    t = translator()
    for _ in range(2):
        value = measure(t, "length", polygon())
        assert value == 0 and type(value) is int


@pytest.mark.parametrize("coordinate", [0, 0.0, -0.0])
def test_centroid_hits_preserve_exact_coordinate_type_sign_and_detach(coordinate):
    t = translator()
    source = {"type": "Point", "coordinates": [coordinate, 2]}
    first = measure(t, "centroid", source)
    second = measure(t, "centroid", deepcopy(source))
    assert type(second["coordinates"][0]) is type(coordinate)
    assert math.copysign(1, second["coordinates"][0]) == math.copysign(1, coordinate)
    first["coordinates"][1] = 8
    second.geometry_metadata["crs"] = "changed"
    third = measure(t, "centroid", source)
    assert third["coordinates"] == [coordinate, 2]
    assert third.geometry_metadata["crs"] == "EPSG:4326"
    assert source["coordinates"][1] == 2


def test_numeric_type_and_signed_zero_are_different_geometry_keys():
    t = translator()
    for value in (0, 0.0, -0.0):
        measure(t, "centroid", {"type": "Point", "coordinates": [value, 2]})
    assert t._geometry_measure_cache.entries == 3


@pytest.mark.parametrize("mutation", ["coordinate", "public_model", "sidecar_model", "crs", "interior"])
def test_current_geometry_mutation_cannot_reuse_a_previous_result(mutation):
    t = translator()
    source = GeometryValue(polygon(), {"crs": "EPSG:4326", "evenOdd": True})
    assert measure(t, "area", source) == 8
    if mutation == "coordinate":
        source["coordinates"][0] = [[0, 0], [4, 2], [4, 0], [0, 2], [0, 0]]
    elif mutation == "public_model":
        source["geodesic"] = True
    elif mutation == "sidecar_model":
        del source["geodesic"]
        source.geometry_metadata["geodesic"] = True
    elif mutation == "crs":
        source.geometry_metadata["crs"] = "EPSG:3857"
    else:
        source.geometry_metadata["evenOdd"] = False
    with pytest.raises(UnsupportedEEError):
        measure(t, "area", source)


def test_invalid_numeric_slot_cycles_and_deep_payloads_never_recurse_in_snapshot():
    cycle = []
    cycle.append(cycle)
    deep = 1
    for _ in range(200):
        deep = [deep]
    for invalid in (cycle, deep, {"payload": list(range(10_001))}):
        with pytest.raises(UnsupportedEEError, match="finite two-dimensional"):
            measure(translator(), "centroid", {"type": "Point", "coordinates": [invalid, 0]})


def test_failed_native_output_is_not_admitted_as_a_successful_result(monkeypatch):
    from gee.compat.earthengine import spherical_native

    t, source, calls = translator(), polygon(geodesic=True), []
    monkeypatch.setattr(spherical_native, "run_ellipsoid_measure",
                        lambda *_: calls.append(True) or (1.0, float("nan")))
    for _ in range(2):
        with pytest.raises(UnsupportedEEError, match="non-finite"):
            measure(t, "area", source, planar=False)
    assert len(calls) == 2
    assert t._geometry_measure_cache.entries == 0


def test_component_proof_hits_copy_normalized_sidecars_and_strict_decode_stays_separate(monkeypatch):
    from gee.compat.earthengine import geometry_components

    t = translator()
    source = {"type": "MultiPolygon", "geodesic": False,
              "coordinates": [polygon()["coordinates"]] * 2}
    assert measure(t, "area", source) == 16
    original = geometry_components._validate_components
    calls = []

    def validate(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(geometry_components, "_validate_components", validate)
    first = decode_component_geometry_bounded(t, source)
    second = decode_component_geometry_bounded(t, source)
    assert len(calls) == 1 and type(second) is GeometryValue
    first["coordinates"][0][0][0][0] = 99
    first.geometry_metadata["geodesic"] = True
    assert second["coordinates"][0][0][0][0] == 0
    assert second.geometry_metadata["geodesic"] is False
    with pytest.raises(UnsupportedEEError, match="topology"):
        decode_geometry_bounded(t, source)


def test_invalid_options_and_separate_translators_do_not_borrow_cached_results(monkeypatch):
    from gee.compat.earthengine import spherical_native

    calls = []
    monkeypatch.setattr(spherical_native, "run_ellipsoid_measure",
                        lambda *_: calls.append(True) or (1.0, 3.0))
    source = polygon(geodesic=True)
    first = translator()
    measure(first, "area", source, planar=False)
    with pytest.raises(UnsupportedEEError):
        measure(first, "area", source, planar=False, maxError=False)
    measure(translator(), "area", source, planar=False)
    assert len(calls) == 2
