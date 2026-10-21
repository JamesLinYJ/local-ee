"""Opt-in extraction of allowlisted local audit fields."""
from __future__ import annotations

import collections
import re
from pathlib import Path
from typing import Any

from .shared import read_json

def _safe_probe_snapshot(audit_root: Path, expected_sdk: str) -> tuple[dict[str, dict[str, set[str]]], dict[str, Any]]:
    """Read only explicitly allowlisted fields; never serialize raw audit JSON."""
    validation_path = audit_root / "gee-complex-compat-v1" / "probe-run-v2" / "validation.json"
    validation = read_json(validation_path)
    if validation.get("sdk") != expected_sdk:
        raise ValueError("Complex compatibility audit SDK version does not match the pinned client")
    observations: dict[str, dict[str, set[str]]] = collections.defaultdict(
        lambda: {"sdk_examples": set(), "compiled_contexts": set(), "rejected_contexts": set()}
    )
    for group in ("probes", "scale_probes"):
        for probe in validation.get(group, []):
            # IDs are short, repository-local probe labels, not user/task IDs.
            probe_id = str(probe.get("id", ""))
            if not re.fullmatch(r"[a-z0-9_]{1,80}", probe_id):
                continue
            for function_name in probe.get("serialized_functions", []):
                if not isinstance(function_name, str):
                    continue
                bucket = observations[function_name]
                if probe.get("sdk_serialized") is True:
                    bucket["sdk_examples"].add(probe_id)
                if probe.get("compiled") is True:
                    bucket["compiled_contexts"].add(probe_id)
                elif probe.get("compiled") is False:
                    bucket["rejected_contexts"].add(probe_id)

    findings = read_json(audit_root / "gee-complex-compat-v1" / "findings.json")
    audited_counts = findings.get("probe_counts", {})
    counts = {
        "source": "sanitized summary of the local complex-compatibility audit",
        "scope": str(validation.get("scope", "")),
        "workflow_probes": {
            "count": len(validation.get("probes", [])),
            "sdk_serialized": sum(p.get("sdk_serialized") is True for p in validation.get("probes", [])),
            "compiled": sum(p.get("compiled") is True for p in validation.get("probes", [])),
            "operation_or_semantic_rejections": audited_counts.get("operation_or_semantic_rejections"),
            "data_or_band_rejections": audited_counts.get("data_or_band_rejections"),
            "classification_note": "Targeted workflow dependencies, not a random API sample; an expression outcome is co-occurrence evidence and not per-signature parameter or numerical verification.",
        },
        "scale_probes": {
            "count": len(validation.get("scale_probes", [])),
            "compiled": sum(p.get("compiled") is True for p in validation.get("scale_probes", [])),
            "rejected": sum(p.get("compiled") is False for p in validation.get("scale_probes", [])),
            "scene_counts": sorted({p.get("fixture_scenes") for p in validation.get("scale_probes", []) if isinstance(p.get("fixture_scenes"), int)}),
            "cases": sorted(
                [
                    {
                        "scene_count": p.get("fixture_scenes"),
                        "graph_nodes": p.get("graph_nodes"),
                        "compiled": p.get("compiled"),
                    }
                    for p in validation.get("scale_probes", [])
                    if isinstance(p.get("fixture_scenes"), int)
                ],
                key=lambda case: (case["scene_count"], case["graph_nodes"] or 0, case["compiled"] is False),
            ),
            "classification_note": "Graph-size probes only; not throughput or full time-series acceptance.",
        },
        "workflow_source_review_count": 6,
        "native_runner_probes": [],
    }
    # Keep only a small, sanitized probe classification. Do not copy raw stderr,
    # execution paths, backend hashes, job identifiers, or full audit documents.
    runtime_classes = {
        "ui_panel": "ui_namespace_missing",
        "ui_chart": "ui_namespace_missing",
        "gee_users_require": "remote_user_module_unavailable",
    }
    for probe in validation.get("runtime_probes", []):
        probe_id = probe.get("id")
        if probe_id in runtime_classes:
            counts["native_runner_probes"].append({
                "surface": {"ui_panel": "ui.Panel", "ui_chart": "ui.Chart", "gee_users_require": "require(users/... module)"}[probe_id],
                "exit_code": probe.get("returncode"),
                "network_allowed": probe.get("network_allowed"),
                "observed_class": runtime_classes[probe_id],
            })
    return observations, counts


def _safe_workflows(audit_root: Path) -> list[dict[str, Any]]:
    findings = read_json(audit_root / "gee-complex-compat-v1" / "findings.json")
    allowlisted_ids = {"s2cloudless", "harmonic", "classification", "arrays", "histarfm", "landtrendr"}
    workflows: list[dict[str, Any]] = []
    for item in findings.get("workflows", []):
        if item.get("id") not in allowlisted_ids:
            continue
        reported_gaps = sorted(str(x) for x in item.get("missing", []))
        workflows.append({
            "id": item["id"],
            "name": item.get("name", ""),
            "priority": item.get("priority", ""),
            "audit_reported_gaps": reported_gaps,
            "local_data_blockers": sorted(str(x) for x in item.get("data_blockers", [])),
            "whole_workflow_status": item.get("whole_workflow_status", ""),
            "public_reference": item.get("source_url", ""),
            "scope_note": "The gap list is a saved source-review finding. Regenerated inventory separately records current same-name handler declarations; neither alone proves full semantics.",
        })
    return sorted(workflows, key=lambda row: row["id"])


def _safe_numerical_evidence(audit_root: Path) -> list[dict[str, Any]]:
    """Extract only numeric facts; omit job IDs, asset IDs, paths and geometries."""
    evidence: list[dict[str, Any]] = []
    real = read_json(audit_root / "react-ui" / "ndvi-validation.json")
    evidence.append({
        "context": "one real local preprocessed Sentinel-2 NDVI sample",
        "reference": "independent Rasterio/NumPy reference on the exact output grid",
        "passed": real.get("passed") is True,
        "crs": real.get("crs"),
        "valid_pixels": real.get("valid_pixels"),
        "mask_mismatches": real.get("mask_mismatches"),
        "max_absolute_error": real.get("max_absolute_error"),
        "tolerance": real.get("tolerance"),
        "google_service_comparison": False,
        "scope_note": "This is an end-to-end sample result; it does not certify every signature or overload used by a general script.",
    })
    multi = read_json(audit_root / "native-macos-multiscene-v5" / "validation.json")
    cases = multi.get("cases", [])
    evidence.append({
        "context": "synthetic three-scene multiband temporal reduction fixture",
        "reference": "independent NumPy reference reprojected to the exact output grid",
        "passed": multi.get("passed") is True,
        "output_case_count": len(cases),
        "mask_mismatches_total": sum(int(c.get("mask_mismatches", 0)) for c in cases),
        "maximum_absolute_error": max((float(c.get("max_abs_error", 0)) for c in cases), default=None),
        "google_service_comparison": False,
        "scope_note": "Fixture-level numerical evidence; not a per-signature support or full GEE-equivalence claim.",
    })
    return evidence
