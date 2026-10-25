"""Frozen provenance and official client parity for the original full formulas."""
from __future__ import annotations

import hashlib
import json

from ee_measures_references import (
    planar_reference, spherical_centroid_coordinates, verify_frozen_wgs84_reference,
)
from ee_measure_reuse_sdk import (
    ROOT, configured_ee, encoded, expanded, fixture, javascript_wires,
    original_collection, receipt, wire_hash,
)
from scripts.ee_python_api.offline import OfflineGuard


def test_original_sources_and_official_sdk_versions_remain_pinned():
    import ee

    data = fixture()
    for source in data["preserved_sources"]:
        assert hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest() == source["sha256"]
    api = data["official_api"]
    lock = json.loads((ROOT / "vendor/earthengine-js/upstream-lock.json").read_bytes())
    assert ee.__version__ == api["python_sdk"].split()[-1] == "1.7.49"
    assert lock["version"] == api["javascript_sdk"].split()[-1] == "1.7.49"
    assert lock["source_commit"] == api["source_commit"]
    for name, key in (("earthengine.cjs", "javascript_bundle_sha256"),
                      ("algorithms.json", "pinned_algorithm_sha256")):
        actual = hashlib.sha256((ROOT / "vendor/earthengine-js" / name).read_bytes()).hexdigest()
        assert actual == api[key] == lock["files"][name]


def test_frozen_full_formula_references_match_the_unchanged_independent_controls():
    data = fixture()
    controls = {row["id"]: row for row in verify_frozen_wgs84_reference()}
    for name, frozen in data["frozen_wgs84_controls"].items():
        assert frozen == controls[name]
    for workflow in data["workflows"].values():
        assert not workflow["accepted"]
        assert "shared 50000-step compilation work budget" in workflow["error"]
        for row in workflow["expected_rows"]:
            geometry = data["cases"][row["name"]]["geometry"]
            if workflow["route"] == "default_wgs84":
                expected = {method: controls[reference]["expected"]
                            for method, reference in row["control_ids"].items()}
                assert row["metrics"] == {method: expected.get(method, 0.0)
                                          for method in ("area", "length", "perimeter")}
                assert row["centroid"] == spherical_centroid_coordinates(geometry)
            else:
                reference = planar_reference(geometry)
                assert row["fraction_area"] == str(reference["area_square_degrees"])
                assert row["metrics"] == {
                    "area": float(reference["area_square_degrees"]),
                    "length": reference["linear_length_degrees"],
                    "perimeter": reference["polygon_perimeter_degrees"],
                }
                assert row["centroid"] == [float(value) for value in reference["centroid_lon_lat_degrees"]]


def test_official_python_keeps_exact_original_wires_and_javascript_matches_full_formulas():
    data = fixture()
    with OfflineGuard() as guard:
        ee = configured_ee()
        javascript = javascript_wires(data)
        python = {}
        for name, record in data["workflows"].items():
            wire = encoded(ee, original_collection(ee, record))
            assert wire == record["wire"]
            assert wire_hash(wire) == record["canonical_wire_sha256"]
            assert expanded(wire) == expanded(javascript[name]), name
            python[name] = wire
        evidence = guard.evidence()
    assert evidence["attempt_count"] == 0
    receipt("sdk-wires", {"python": python, "javascript": javascript,
                          "python_offline_guard": evidence,
                          "javascript_network_attempts": 0,
                          "original_rows": [4, 6, 6], "original_columns": [19, 13, 13]})
