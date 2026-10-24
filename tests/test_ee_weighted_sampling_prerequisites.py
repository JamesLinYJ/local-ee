"""Portable-checkout behavior for optional, ignored native audit prerequisites."""
from __future__ import annotations

import json

import pytest

from ee_weighted_sampling_native import native_probe_or_skip


def test_missing_native_manifest_skips_with_native_only_scope_receipt(tmp_path):
    manifest = tmp_path / "ignored-wave64-manifest.json"
    receipts = tmp_path / "receipts"
    with pytest.raises(pytest.skip.Exception, match="manifest is absent"):
        native_probe_or_skip(manifest, receipts)

    rows = list(receipts.glob("native-prerequisite-missing-*.json"))
    assert len(rows) == 1
    receipt = json.loads(rows[0].read_text(encoding="utf-8"))
    assert receipt["status"] == "skipped"
    assert receipt["missing_prerequisite"] == str(manifest.resolve())
    assert "native mask apply" in receipt["skipped_scope"][0]
    assert "offline official Python/JavaScript SDK wire parity" in receipt["still_runnable_scope"]
    assert receipt["google_requests"] == 0
    assert receipt["spark_context_started"] is False
    assert receipt["deployment_eligible"] is False


def test_present_but_invalid_native_manifest_fails_instead_of_skipping(tmp_path):
    manifest = tmp_path / "present-invalid-wave64-manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")

    def reject_present_manifest(*, manifest_path, receipt_dir):
        raise ValueError("audit manifest hash mismatch")

    with pytest.raises(ValueError, match="audit manifest hash mismatch"):
        native_probe_or_skip(manifest, tmp_path / "receipts", reject_present_manifest)
    assert not (tmp_path / "receipts").exists()


def test_broken_symlink_is_present_and_reaches_strict_validation(tmp_path):
    manifest = tmp_path / "broken-wave64-manifest.json"
    manifest.symlink_to(tmp_path / "missing-manifest-target.json")

    def reject_broken_symlink(*, manifest_path, receipt_dir):
        raise FileNotFoundError(f"strict manifest resolution failed: {manifest_path}")

    with pytest.raises(FileNotFoundError, match="strict manifest resolution failed"):
        native_probe_or_skip(manifest, tmp_path / "receipts", reject_broken_symlink)
    assert not (tmp_path / "receipts").exists()
