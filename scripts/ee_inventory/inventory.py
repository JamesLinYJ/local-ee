"""Combine pinned signatures and declared handlers with sanitized evidence."""
from __future__ import annotations

import collections
from pathlib import Path
from typing import Any

from .catalogue import CLIENT_ALIAS_LOWERINGS, KNOWN_PARTIAL_LIMITS
from .declarations import read_declared_handlers
from .shared import ROOT, SCHEMA_VERSION, _snapshot_path, read_json, sha256
from .validation import _validate_snapshot

def _canonical_name(official_name: str) -> str:
    return official_name.removeprefix("algorithms/")


def build_inventory(root: Path = ROOT) -> dict[str, Any]:
    signature_path = root / "vendor" / "earthengine-js" / "algorithms.json"
    lock_path = root / "vendor" / "earthengine-js" / "upstream-lock.json"
    lock = read_json(lock_path)
    signature_hash = sha256(signature_path)
    expected_hash = lock.get("files", {}).get("algorithms.json")
    if expected_hash and signature_hash != expected_hash:
        raise ValueError("Pinned algorithms.json does not match the vendor lock checksum")
    raw = read_json(signature_path)
    algorithms = raw.get("algorithms")
    if not isinstance(algorithms, list):
        raise ValueError("Pinned algorithms.json has no algorithms list")
    canonical_names = [_canonical_name(item["name"]) for item in algorithms]
    if len(set(canonical_names)) != len(canonical_names):
        raise ValueError("Pinned algorithm file contains duplicate function signatures")

    declared = read_declared_handlers(root / "gee" / "ee_translate.py")
    evidence_snapshot = read_json(_snapshot_path(root))
    _validate_snapshot(evidence_snapshot, lock["version"])
    observations = evidence_snapshot["api_context_counts"]
    audit_summary = evidence_snapshot["targeted_audit_summary"]
    workflow_review = []
    for workflow in evidence_snapshot["workflow_source_review"]:
        row = dict(workflow)
        row["current_exact_name_handler_checks"] = [
            {
                "reported_name": gap,
                "same_name_handler_declared": gap in declared,
                "interpretation": (
                    "A same-name compiler entry exists in the current source, but that does not validate full signature or semantics."
                    if gap in declared else
                    "No same-name compiler entry is declared; this alone is not a complete proof that the API form is unsupported."
                ),
            }
            for gap in row["audit_reported_gaps"]
        ]
        workflow_review.append(row)
    families: dict[str, dict[str, int]] = collections.defaultdict(lambda: {
        "signature_count": 0,
        "declared_handler_count": 0,
        "appears_in_selected_sdk_serialization": 0,
        "appears_in_successful_compile_context": 0,
        "appears_in_rejected_compile_context": 0,
    })
    entries: list[dict[str, Any]] = []
    for item, name in sorted(zip(algorithms, canonical_names), key=lambda pair: pair[1]):
        family = name.split(".", 1)[0]
        observation = observations.get(name, {
            "sdk_serialization_expression_count": 0,
            "compile_success_expression_count": 0,
            "compile_rejection_expression_count": 0,
        })
        has_handler = name in declared
        families[family]["signature_count"] += 1
        families[family]["declared_handler_count"] += int(has_handler)
        families[family]["appears_in_selected_sdk_serialization"] += int(observation["sdk_serialization_expression_count"] > 0)
        families[family]["appears_in_successful_compile_context"] += int(observation["compile_success_expression_count"] > 0)
        families[family]["appears_in_rejected_compile_context"] += int(observation["compile_rejection_expression_count"] > 0)
        entries.append({
            "name": name,
            "official_name": item["name"],
            "family": family,
            "description": item.get("description", ""),
            "return_type": item.get("returnType", ""),
            "arguments": item.get("arguments", []),
            "evidence": {
                "pinned_sdk_signature_present": True,
                "declared_compiler_handler": has_handler,
                "declared_handler_interpretation": (
                    "The name appears in gee.ee_translate.SUPPORTED_FUNCTIONS; this is dispatch inventory only, not proof that all overloads/arguments or GEE semantics work."
                    if has_handler else
                    "The name is absent from gee.ee_translate.SUPPORTED_FUNCTIONS. This says only that no same-name handler is declared; it does not establish that all forms are impossible or unsupported."
                ),
                "argument_coverage_complete": False,
                "limit_catalogue_status": (
                    "known_local_limitations_listed"
                    if name in KNOWN_PARTIAL_LIMITS else
                    "no_limit_entry_recorded_not_evidence_of_full_support"
                ),
                "known_local_limits": KNOWN_PARTIAL_LIMITS.get(name, []),
                "selected_audit_context_counts": {
                    **observation,
                    "interpretation": "These are whole-expression co-occurrence records only. A successful or rejected expression does not validate this function's full signature, parameter space, isolated runtime result, or numerical behavior.",
                },
                "runtime_execution_verified_per_signature": False,
                "independent_numerical_equivalence_verified_per_signature": False,
                "google_same_data_comparison_verified_per_signature": False,
            },
        })

    signature_set = set(canonical_names)
    unmatched_declarations = sorted(declared - signature_set)
    audit_summary["native_runner_probes"] = sorted(audit_summary["native_runner_probes"], key=lambda row: row["surface"])
    return {
        "schema_version": SCHEMA_VERSION,
        "title": "Pinned Earth Engine API signature and local compatibility evidence inventory",
        "generated_by": "scripts/ee_capability_inventory.py",
        "source": {
            "package": lock.get("name"),
            "version": lock.get("version"),
            "license": lock.get("license"),
            "repository": lock.get("source"),
            "upstream_commit": lock.get("source_commit"),
            "signature_source": lock.get("algorithm_signatures_source"),
            "signature_file_sha256": signature_hash,
            "interpretation": "The official algorithms.json is a signature catalogue. Its presence is not evidence that a local service implements that algorithm.",
        },
        "evidence_model": {
            "S_signature": "A function/signature/argument list is present in the pinned official SDK metadata. Separate from observing a generated call in one selected fixture.",
            "S_probe": "The SDK serialized an expression containing the name in a selected fixture; this is not exhaustive syntax or parameter verification.",
            "C_declaration": "A same-name entry exists in the local advertised compiler handler inventory; declared presence alone does not validate arguments or implementation semantics.",
            "C_probe_context": "The API name co-occurred in an expression whose local compile succeeded or failed. Outcomes apply to the entire expression, not an isolated API signature.",
            "E": "This inventory does not claim isolated runtime execution for each signature.",
            "N": "Only the separately summarized fixtures have independent local numerical reference evidence; no per-signature N claim is inferred.",
            "G": "No same-data Google Earth Engine service comparison is claimed.",
            "coverage_rule": "No API coverage percentage is calculated from targeted workflows or handler declarations.",
        },
        "summary": {
            "algorithm_signature_count": len(entries),
            "unique_function_name_count": len(signature_set),
            "duplicate_or_overloaded_signature_names": 0,
            "declared_handler_name_count": len(declared),
            "pinned_signatures_with_same_name_declared_handler": sum(name in declared for name in canonical_names),
            "declared_handler_names_without_exact_signature_name": unmatched_declarations,
            "argument_count_total": sum(len(item.get("arguments", [])) for item in algorithms),
            "families": {family: dict(families[family]) for family in sorted(families)},
        },
        "algorithms": entries,
        "selected_client_helper_lowerings": CLIENT_ALIAS_LOWERINGS,
        "local_javascript_runtime_surface": [
            {"surface": "print", "status": "locally_adapted", "scope": "Synchronous local getInfo/console formatting; computed reads run through local bridge.", "source": "runtimes/eejs/runner.cjs"},
            {"surface": "Map", "status": "locally_adapted_partial", "scope": ["addLayer", "centerObject", "setCenter", "setOptions", "clear", "setControlVisibility"], "limitations": "Uses the local workbench/map pipeline and local basemap; this is not the Code Editor Map/UI component model.", "source": "runtimes/eejs/runner.cjs"},
            {"surface": "Export.image.toDrive", "status": "locally_adapted", "scope": "Creates a local image export task handled by the local job service.", "source": "runtimes/eejs/runner.cjs"},
            {"surface": "Export.table.toDrive", "status": "locally_adapted", "scope": "Creates a local table export task handled by the local job service.", "source": "runtimes/eejs/runner.cjs"},
            {"surface": "Export to Cloud Storage / EE Assets", "status": "explicitly_unavailable_in_local_adapter", "scope": "The runner throws for toCloudStorage and toAsset; export to local files instead.", "source": "runtimes/eejs/runner.cjs"},
            {"surface": "ui.* / ui.Chart", "status": "not_available_in_current_runner", "scope": "Two isolated runtime probes report the ui namespace missing; no local UI API compatibility is implied.", "source": "reports/gee-evidence-snapshot.json"},
            {"surface": "require('users/...')", "status": "remote_user_modules_not_available", "scope": "The selected LandTrendr module probe could not resolve a remote users module; no external fetch is allowed.", "source": "reports/gee-evidence-snapshot.json"},
        ],
        "selected_workflow_review": workflow_review,
        "sanitized_targeted_audit_summary": audit_summary,
        "numerical_evidence_contexts": evidence_snapshot["numerical_evidence_contexts"],
        "limits": [
            "Algorithm signatures are the complete pinned 1.7.49 signature list, not the complete Code Editor JavaScript surface, global data catalogue, private assets, or managed Google services.",
            "Declared compiler handler presence is separate from per-argument validation, runtime behavior, numerical equivalence, and Google service equivalence.",
            "No-declared-handler labels are intentionally not rendered as definitely unsupported; some client aliases lower to other API calls and signatures can have non-identical local pathways.",
            "Targeted complex-workflow probes are purposive and can stop at an earlier missing operation; they do not estimate the share of all GEE APIs supported.",
            "The local API/data alias and execution policies impose additional scope limits beyond function signatures; external data, private assets, Drive, Cloud Storage, and user modules require separate local adapters and data migration.",
        ],
    }
