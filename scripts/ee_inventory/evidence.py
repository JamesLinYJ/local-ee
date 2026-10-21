"""Build sanitized snapshots only when explicitly requested."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .audit_extract import _safe_numerical_evidence, _safe_probe_snapshot, _safe_workflows
from .shared import ROOT, _snapshot_path, read_json, render_json
from .validation import _validate_snapshot

def build_local_evidence_snapshot(root: Path = ROOT) -> dict[str, Any]:
    """Create a sanitized, reviewable evidence input from local audit allowlists.

    This opt-in refresh path is the only code that reads untracked local audit
    artifacts. Normal report generation consumes the checked-in snapshot only.
    """
    lock = read_json(root / "vendor" / "earthengine-js" / "upstream-lock.json")
    observations, audit_summary = _safe_probe_snapshot(root / "audit", lock["version"])
    api_context_counts = {
        name: {
            "sdk_serialization_expression_count": len(value["sdk_examples"]),
            "compile_success_expression_count": len(value["compiled_contexts"]),
            "compile_rejection_expression_count": len(value["rejected_contexts"]),
        }
        for name, value in sorted(observations.items())
    }
    snapshot = {
        "schema_version": 1,
        "sdk_version": lock["version"],
        "provenance": "Allowlisted and sanitized counters/labels derived from local compatibility and numerical audit records; raw records and paths are excluded.",
        "api_context_counts": api_context_counts,
        "targeted_audit_summary": audit_summary,
        "workflow_source_review": _safe_workflows(root / "audit"),
        "numerical_evidence_contexts": _safe_numerical_evidence(root / "audit"),
    }
    _validate_snapshot(snapshot, lock["version"])
    return snapshot


def refresh_local_evidence_snapshot(root: Path = ROOT) -> Path:
    snapshot = build_local_evidence_snapshot(root)
    output = _snapshot_path(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_json(snapshot), encoding="utf-8")
    return output
