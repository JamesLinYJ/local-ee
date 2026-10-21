"""Strict schema and privacy validation for sanitized evidence snapshots."""
from __future__ import annotations

import re
from typing import Any

from .shared import render_json

def _validate_snapshot(snapshot: dict[str, Any], expected_sdk: str) -> None:
    expected_keys = {
        "api_context_counts",
        "numerical_evidence_contexts",
        "provenance",
        "schema_version",
        "sdk_version",
        "targeted_audit_summary",
        "workflow_source_review",
    }
    if not isinstance(snapshot, dict) or set(snapshot) != expected_keys:
        raise ValueError("Sanitized evidence snapshot has an unknown or incomplete schema")
    if snapshot.get("schema_version") != 1:
        raise ValueError("Unsupported sanitized evidence snapshot schema")
    if snapshot.get("sdk_version") != expected_sdk:
        raise ValueError("Sanitized evidence snapshot SDK version does not match the pinned client")
    if not isinstance(snapshot.get("api_context_counts"), dict):
        raise ValueError("Sanitized evidence snapshot has no API context counts")
    if not isinstance(snapshot.get("targeted_audit_summary"), dict):
        raise ValueError("Sanitized evidence snapshot has no targeted audit summary")
    if not isinstance(snapshot.get("workflow_source_review"), list):
        raise ValueError("Sanitized evidence snapshot has no workflow review list")
    if not isinstance(snapshot.get("numerical_evidence_contexts"), list):
        raise ValueError("Sanitized evidence snapshot has no numerical evidence list")

    count_keys = {
        "sdk_serialization_expression_count",
        "compile_success_expression_count",
        "compile_rejection_expression_count",
    }
    for name, counts in snapshot["api_context_counts"].items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]*", name) or not isinstance(counts, dict) or set(counts) != count_keys:
            raise ValueError("Sanitized evidence snapshot has an invalid API context row")
        if any(type(value) is not int or value < 0 for value in counts.values()):
            raise ValueError("Sanitized evidence snapshot API context counts must be nonnegative integers")

    summary = snapshot["targeted_audit_summary"]
    summary_keys = {"native_runner_probes", "scale_probes", "scope", "source", "workflow_probes", "workflow_source_review_count"}
    if set(summary) != summary_keys or not isinstance(summary["workflow_probes"], dict) or not isinstance(summary["scale_probes"], dict):
        raise ValueError("Sanitized evidence snapshot has an invalid audit summary schema")
    if any(not isinstance(summary[key], str) for key in ("scope", "source")):
        raise ValueError("Sanitized evidence snapshot audit summary labels must be strings")
    if type(summary["workflow_source_review_count"]) is not int or summary["workflow_source_review_count"] < 0:
        raise ValueError("Sanitized evidence snapshot workflow count is invalid")
    workflow_probe_keys = {"classification_note", "compiled", "count", "data_or_band_rejections", "operation_or_semantic_rejections", "sdk_serialized"}
    workflow_probes = summary["workflow_probes"]
    if set(workflow_probes) != workflow_probe_keys or not isinstance(workflow_probes["classification_note"], str):
        raise ValueError("Sanitized evidence snapshot workflow probe schema is invalid")
    if any(type(workflow_probes[key]) is not int or workflow_probes[key] < 0 for key in workflow_probe_keys - {"classification_note"}):
        raise ValueError("Sanitized evidence snapshot workflow counts must be nonnegative integers")
    scale = summary["scale_probes"]
    scale_keys = {"cases", "classification_note", "compiled", "count", "rejected", "scene_counts"}
    if set(scale) != scale_keys or not isinstance(scale["classification_note"], str):
        raise ValueError("Sanitized evidence snapshot scale probe schema is invalid")
    if any(type(scale[key]) is not int or scale[key] < 0 for key in ("compiled", "count", "rejected")):
        raise ValueError("Sanitized evidence snapshot scale counts must be nonnegative integers")
    if not isinstance(scale["scene_counts"], list) or any(type(value) is not int or value < 0 for value in scale["scene_counts"]):
        raise ValueError("Sanitized evidence snapshot scene counts are invalid")
    if not isinstance(scale["cases"], list):
        raise ValueError("Sanitized evidence snapshot scale cases must be a list")
    for case in scale["cases"]:
        if not isinstance(case, dict) or set(case) != {"compiled", "graph_nodes", "scene_count"}:
            raise ValueError("Sanitized evidence snapshot has an invalid scale case")
        if type(case["compiled"]) is not bool or type(case["scene_count"]) is not int or case["scene_count"] < 0:
            raise ValueError("Sanitized evidence snapshot scale case values are invalid")
        if case["graph_nodes"] is not None and (type(case["graph_nodes"]) is not int or case["graph_nodes"] < 0):
            raise ValueError("Sanitized evidence snapshot graph node count is invalid")
    if len(scale["cases"]) != scale["count"]:
        raise ValueError("Sanitized evidence snapshot scale case count does not match its rows")
    if not isinstance(summary["native_runner_probes"], list):
        raise ValueError("Sanitized evidence snapshot runner probes must be a list")
    for probe in summary["native_runner_probes"]:
        if not isinstance(probe, dict) or set(probe) != {"exit_code", "network_allowed", "observed_class", "surface"}:
            raise ValueError("Sanitized evidence snapshot has an invalid runner probe")
        if type(probe["exit_code"]) is not int or type(probe["network_allowed"]) is not bool:
            raise ValueError("Sanitized evidence snapshot runner probe values are invalid")
        if not all(isinstance(probe[key], str) for key in ("observed_class", "surface")):
            raise ValueError("Sanitized evidence snapshot runner probe labels must be strings")

    workflow_keys = {"audit_reported_gaps", "id", "local_data_blockers", "name", "priority", "public_reference", "scope_note", "whole_workflow_status"}
    workflows = snapshot["workflow_source_review"]
    if len(workflows) != summary["workflow_source_review_count"]:
        raise ValueError("Sanitized evidence snapshot workflow rows do not match their declared count")
    for workflow in workflows:
        if not isinstance(workflow, dict) or set(workflow) != workflow_keys:
            raise ValueError("Sanitized evidence snapshot has an invalid workflow row")
        if not re.fullmatch(r"[a-z0-9_]{1,40}", workflow["id"]):
            raise ValueError("Sanitized evidence snapshot workflow identifier is invalid")
        for key in ("audit_reported_gaps", "local_data_blockers"):
            if not isinstance(workflow[key], list) or any(not isinstance(value, str) or len(value) > 200 for value in workflow[key]):
                raise ValueError("Sanitized evidence snapshot workflow evidence labels are invalid")
        if any(not isinstance(workflow[key], str) or len(workflow[key]) > 500 for key in workflow_keys - {"audit_reported_gaps", "local_data_blockers"}):
            raise ValueError("Sanitized evidence snapshot workflow metadata is invalid")

    for evidence in snapshot["numerical_evidence_contexts"]:
        required = {"context", "google_service_comparison", "passed", "reference", "scope_note"}
        optional = {"crs", "valid_pixels", "mask_mismatches", "max_absolute_error", "tolerance", "output_case_count", "mask_mismatches_total", "maximum_absolute_error"}
        if not isinstance(evidence, dict) or not required.issubset(evidence) or set(evidence) - required - optional:
            raise ValueError("Sanitized evidence snapshot has an invalid numerical evidence row")
        if any(not isinstance(evidence[key], str) for key in ("context", "reference", "scope_note")):
            raise ValueError("Sanitized evidence snapshot numerical evidence labels must be strings")
        if type(evidence["passed"]) is not bool or evidence["google_service_comparison"] is not False:
            raise ValueError("Sanitized evidence snapshot numerical evidence status is invalid")
        for key in {"valid_pixels", "mask_mismatches", "output_case_count", "mask_mismatches_total"} & set(evidence):
            if type(evidence[key]) is not int or evidence[key] < 0:
                raise ValueError("Sanitized evidence snapshot numerical counts must be nonnegative integers")
        for key in {"max_absolute_error", "maximum_absolute_error", "tolerance"} & set(evidence):
            if type(evidence[key]) not in (int, float) or not 0 <= evidence[key] < float("inf"):
                raise ValueError("Sanitized evidence snapshot numerical values must be finite and nonnegative")
        if "crs" in evidence and (not isinstance(evidence["crs"], str) or not re.fullmatch(r"EPSG:[0-9]+", evidence["crs"])):
            raise ValueError("Sanitized evidence snapshot CRS is invalid")

    serialized = render_json(snapshot)
    forbidden_patterns = (
        r"(?<![A-Za-z])/(?:Users|private|tmp|var|home)/",
        r"(?i)\b[A-Z]:\\",
        r"(?i)\b(?:job_id|task_id|backend_sha256|password|authorization|bearer|api[_-]?token)\b",
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    )
    if any(re.search(pattern, serialized) for pattern in forbidden_patterns):
        raise ValueError("Sanitized evidence snapshot contains a forbidden path, identifier, or secret field")
