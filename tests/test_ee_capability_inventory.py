from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ee_capability_inventory.py"
SPEC = importlib.util.spec_from_file_location("ee_capability_inventory", SCRIPT)
assert SPEC and SPEC.loader
inventory_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory_module)


def test_inventory_covers_every_pinned_function_and_argument():
    report = inventory_module.build_inventory(ROOT)
    pinned = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())[
        "algorithms"
    ]
    rows = report["algorithms"]
    assert len(rows) == len(pinned) == report["summary"]["algorithm_signature_count"]
    lock = json.loads((ROOT / "vendor/earthengine-js/upstream-lock.json").read_text())
    assert report["source"]["signature_file_sha256"] == lock["files"]["algorithms.json"]
    assert [row["official_name"] for row in rows] == sorted(
        (item["name"] for item in pinned), key=lambda value: value.removeprefix("algorithms/")
    )
    by_name = {item["name"].removeprefix("algorithms/"): item for item in pinned}
    assert len(by_name) == len(rows)
    declared = inventory_module.read_declared_handlers(ROOT / "gee/ee_translate.py")
    for row in rows:
        signature = by_name[row["name"]]
        assert row["arguments"] == signature.get("arguments", [])
        assert row["return_type"] == signature.get("returnType", "")
        assert row["evidence"]["pinned_sdk_signature_present"] is True
        assert row["evidence"]["runtime_execution_verified_per_signature"] is False
        assert row["evidence"]["independent_numerical_equivalence_verified_per_signature"] is False
        assert row["evidence"]["google_same_data_comparison_verified_per_signature"] is False
        assert row["evidence"]["argument_coverage_complete"] is False
        assert row["evidence"]["declared_compiler_handler"] == (row["name"] in declared)


def test_inventory_does_not_turn_targeted_probes_into_coverage_claims():
    report = inventory_module.build_inventory(ROOT)
    assert "coverage_rule" in report["evidence_model"]
    assert "percentage" in report["evidence_model"]["coverage_rule"]
    assert len(report["selected_workflow_review"]) == 6
    assert report["summary"]["families"]
    assert sum(v["signature_count"] for v in report["summary"]["families"].values()) == len(
        report["algorithms"]
    )
    assert not any("coverage_percent" in row for row in report["algorithms"])
    inventory_by_name = {row["name"]: row for row in report["algorithms"]}
    quality = inventory_by_name["ImageCollection.qualityMosaic"]["evidence"]
    assert quality["declared_compiler_handler"] in (True, False)
    assert "not proof" in quality["declared_handler_interpretation"] or "does not establish" in quality["declared_handler_interpretation"]
    assert any(alias["client_api"] == "Filter.inList" for alias in report["selected_client_helper_lowerings"])
    inventory_by_name = {row["name"]: row for row in report["algorithms"]}
    for name in (
        "Number.bitCount",
        "Number.bitwiseNot",
        "Number.bitwiseAnd",
        "Number.bitwiseOr",
        "Number.bitwiseXor",
        "Number.leftShift",
        "Number.rightShift",
        "Image.toFloat",
        "Image.toDouble",
    ):
        assert inventory_by_name[name]["evidence"]["declared_compiler_handler"] is True
        assert inventory_by_name[name]["evidence"]["known_local_limits"]


def test_generation_is_deterministic_and_privacy_safe(tmp_path: Path):
    first = inventory_module.render_json(inventory_module.build_inventory(ROOT))
    second = inventory_module.render_json(inventory_module.build_inventory(ROOT))
    assert first == second
    for forbidden in ("/Users/", "job_id", "task_id", "backend_sha256", "password", "Authorization"):
        assert forbidden not in first
    output = tmp_path / "inventory.json"
    subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(ROOT), "--output", str(output)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.read_text(encoding="utf-8") == first


def test_clean_checkout_generates_without_private_audit_inputs(tmp_path: Path):
    clean_root = tmp_path / "clean-checkout"
    required = (
        "scripts/ee_capability_inventory.py",
        "gee/ee_translate.py",
        "gee/compat/earthengine/capabilities.py",
        "gee/ee_dates.py",
        "gee/ee_integer.py",
        "vendor/earthengine-js/algorithms.json",
        "vendor/earthengine-js/upstream-lock.json",
        "reports/gee-evidence-snapshot.json",
    )
    for relative in required:
        source = ROOT / relative
        destination = clean_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    assert not (clean_root / "audit").exists()
    output = clean_root / "reports/gee-api-inventory.json"
    subprocess.run(
        [
            sys.executable,
            str(clean_root / "scripts/ee_capability_inventory.py"),
            "--root",
            str(clean_root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.read_text(encoding="utf-8") == inventory_module.render_json(
        inventory_module.build_inventory(clean_root)
    )


def test_snapshot_schema_rejects_unknown_fields_and_noninteger_counts():
    snapshot = json.loads((ROOT / "reports/gee-evidence-snapshot.json").read_text())
    lock = json.loads((ROOT / "vendor/earthengine-js/upstream-lock.json").read_text())

    with_unknown = dict(snapshot, private_field="not allowed")
    with pytest.raises(ValueError, match="unknown or incomplete schema"):
        inventory_module._validate_snapshot(with_unknown, lock["version"])

    invalid_counts = json.loads(json.dumps(snapshot))
    function_name = next(iter(invalid_counts["api_context_counts"]))
    invalid_counts["api_context_counts"][function_name]["sdk_serialization_expression_count"] = True
    with pytest.raises(ValueError, match="nonnegative integers"):
        inventory_module._validate_snapshot(invalid_counts, lock["version"])
