"""Official SDK serialization and frozen original-wire provenance for Wave72."""
from __future__ import annotations

import hashlib
import json

from ee_multipolygon_sdk import (
    ROOT, configured_ee, expanded, fixture, javascript_wires, python_wires, receipt,
)
from scripts.ee_python_api.offline import OfflineGuard


def test_frozen_original_records_and_pinned_official_sdks():
    import ee

    data = fixture()
    api = data["official_api"]
    assert ee.__version__ == api["python_sdk"].split()[-1] == "1.7.49"
    lock = json.loads((ROOT / "vendor/earthengine-js/upstream-lock.json").read_bytes())
    assert lock["version"] == api["javascript_sdk"].split()[-1] == "1.7.49"
    assert lock["source_commit"] == api["source_commit"]
    for name, key in (("earthengine.cjs", "javascript_bundle_sha256"),
                      ("algorithms.json", "pinned_algorithm_sha256")):
        actual = hashlib.sha256((ROOT / "vendor/earthengine-js" / name).read_bytes()).hexdigest()
        assert actual == api[key] == lock["files"][name]
    for path, digest in data["old_fixture_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    original = data["original_evidence"]
    assert original["sha256"] == "fd2a59f187262d56d8dcab9c67694c80ff820218a057dc62d5d4d5530b8d2931"
    assert len(original["records"]) == 16
    assert all(not row["passed"] for row in original["records"])
    assert {row["error"] for row in original["records"]} == {
        "UnsupportedEEError: Invalid planar GeoJSON geometry topology",
    }
    # Audit files are intentionally ignored and may not exist in clean CI.
    source = ROOT / original["path"]
    if source.exists():
        assert hashlib.sha256(source.read_bytes()).hexdigest() == original["sha256"]
        assert json.loads(source.read_bytes())["records"] == original["records"]


def test_python_javascript_preserve_original_multipolygon_formulas_offline():
    data = fixture()
    with OfflineGuard() as guard:
        python = python_wires(configured_ee(), data)
        javascript = javascript_wires(data)
        for group in ("originals", "controls"):
            assert set(python[group]) == set(javascript[group])
            for key in python[group]:
                assert expanded(python[group][key]) == expanded(javascript[group][key]), key
        assert expanded(python["workflow"]) == expanded(javascript["workflow"])
        for row in data["original_evidence"]["records"]:
            # Python generates the very same frozen bytes after canonical JSON
            # encoding, not only a semantically related GeometryCollection.
            assert python["originals"][row["id"]] == row["wire"]
            assert expanded(javascript["originals"][row["id"]]) == expanded(row["wire"])
        for client in (python, javascript):
            for name in data["cases"]:
                value = expanded(client["controls"][f"{name}/Feature.centroid"])
                metadata = value["arguments"]["feature"]["arguments"]["metadata"]
                assert metadata["value"]["system:index"] == f"wave72-{name}"
        evidence = guard.evidence()
    assert evidence["attempt_count"] == 0
    receipt("sdk-wires", {"python": python, "javascript": javascript,
                          "python_offline_guard": evidence,
                          "javascript_intercepted_network_attempts": 0,
                          "original_records": 16, "control_records_per_client": 72})
