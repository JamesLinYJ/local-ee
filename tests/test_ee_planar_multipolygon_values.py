"""Independent planar arithmetic for unchanged official MultiPolygon requests."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext

import pytest

from ee_multipolygon_reference import numeric_expected, reference
from ee_multipolygon_sdk import (
    METHODS, configured_ee, encoded, fixture, javascript_wires, python_wires, receipt,
    source_feature,
)
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


DATA = fixture()
ORIGINALS = DATA["original_evidence"]["records"]


def _assert_measure(actual, expected, owner, method):
    if method == "centroid":
        point = actual["geometry"] if owner == "Feature" else actual
        assert point["type"] == "Point"
        actual = point["coordinates"]
    assert actual == pytest.approx(expected, rel=2e-12, abs=2e-12)


def test_frozen_references_are_independent_fraction_decimal_controls():
    for case in DATA["cases"].values():
        assert reference(case["geometry"]) == case["reference"]
    cases = DATA["cases"]
    assert cases["duplicate"]["reference"]["area"] == "16"
    assert cases["overlap"]["reference"]["area"] == "20"
    assert cases["duplicate_holes"]["reference"]["area"] == "44"
    assert cases["nested_collection"]["reference"]["area"] == "38"
    assert cases["nested_collection"]["reference"]["length"] == "5"
    assert cases["mixed_highest_dimension"]["reference"]["centroid"] == ["2.6", "1.9"]
    assert cases["empty"]["reference"]["centroid"] is None
    assert cases["empty_plus_line"]["reference"]["highest_dimension"] == 1
    assert cases["empty_plus_points"]["reference"]["highest_dimension"] == 0
    with localcontext() as context:
        context.prec = 70
        expected = Decimal(6) + 2 * Decimal(5).sqrt()
        actual = Decimal(cases["diagonal_duplicate"]["reference"]["perimeter"])
        assert abs(expected - actual) < Decimal("1e-66")
    # Union controls: duplicate union area would be 8, overlap union area17.
    assert float(cases["duplicate"]["reference"]["area"]) != 8
    assert float(cases["overlap"]["reference"]["area"]) != 17


@pytest.mark.parametrize("record", ORIGINALS, ids=lambda row: row["id"])
def test_exact_sixteen_original_sdk_wires_now_compute_the_original_expectations(record):
    original = deepcopy(record)
    with OfflineGuard() as guard:
        actual = compile_expression(record["wire"], [], {})["value"]
        owner = "Feature" if record["feature"] else "Geometry"
        _assert_measure(actual, record["expected"], owner, record["method"])
    assert record == original
    assert guard.evidence()["attempt_count"] == 0
    receipt(record["id"].replace("/", "-"), {
        "original": record, "observed": actual, "offline_guard": guard.evidence(),
    })


@pytest.fixture(scope="module")
def both_client_controls():
    with OfflineGuard() as guard:
        python = python_wires(configured_ee(), DATA)["controls"]
        javascript = javascript_wires(DATA)["controls"]
    assert guard.evidence()["attempt_count"] == 0
    return python, javascript


@pytest.mark.parametrize("case", list(DATA["cases"]))
@pytest.mark.parametrize("owner", ["Geometry", "Feature"])
@pytest.mark.parametrize("method", METHODS)
def test_both_official_clients_match_independent_component_measures(
        case, owner, method, both_client_controls):
    expected = numeric_expected(DATA["cases"][case]["reference"], method)
    key = f"{case}/{owner}.{method}"
    with OfflineGuard() as guard:
        for controls in both_client_controls:
            wire = controls[key]
            before = deepcopy(wire)
            if expected is None:
                with pytest.raises(UnsupportedEEError, match="centroid"):
                    compile_expression(wire, [], {})
            else:
                actual = compile_expression(wire, [], {})["value"]
                _assert_measure(actual, expected, owner, method)
                if owner == "Feature" and method == "centroid":
                    # Both pinned SDKs serialize GeoJSON id as system:index.
                    assert actual["properties"]["system:index"] == f"wave72-{case}"
                    assert actual["properties"]["nested"]["labels"] == [case, "preserved"]
            assert wire == before
    assert guard.evidence()["attempt_count"] == 0


@pytest.mark.parametrize("case", list(DATA["invalid_atoms"]))
@pytest.mark.parametrize("owner", ["Geometry", "Feature"])
@pytest.mark.parametrize("method", METHODS)
def test_individually_invalid_polygon_atoms_still_reject(case, owner, method):
    mapping = DATA["invalid_atoms"][case]
    with OfflineGuard() as guard:
        ee = configured_ee()
        value = (ee.Geometry(mapping) if owner == "Geometry"
                 else source_feature(ee, case, mapping, 0))
        wire = encoded(ee, getattr(value, method)(proj="EPSG:4326"))
        with pytest.raises(UnsupportedEEError, match="invalid|Invalid|topology"):
            compile_expression(wire, [], {})
    assert guard.evidence()["attempt_count"] == 0


@pytest.mark.parametrize("method", METHODS)
def test_planar_left_inside_interiors_are_not_authorized_by_multipolygon_support(method):
    mapping = deepcopy(DATA["cases"]["duplicate"]["geometry"])
    mapping["evenOdd"] = False
    with OfflineGuard() as guard:
        ee = configured_ee()
        expression = getattr(ee.Geometry(mapping), method)(proj="EPSG:4326")
        with pytest.raises(UnsupportedEEError, match="evenOdd=false|left-inside"):
            compile_expression(encoded(ee, expression), [], {})
    assert guard.evidence()["attempt_count"] == 0


@pytest.mark.parametrize("case", [name for name in DATA["cases"] if name != "empty"])
def test_source_and_centroid_feature_id_preserve_the_official_sdk_identity(case):
    with OfflineGuard() as guard:
        ee = configured_ee()
        source = source_feature(ee, case, DATA["cases"][case]["geometry"], 0)
        centroid = source.centroid(proj="EPSG:4326")
        for expression in (source.id(), centroid.id()):
            result = compile_expression(encoded(ee, expression), [], {})
            assert result["value"] == f"wave72-{case}"
    assert guard.evidence()["attempt_count"] == 0
