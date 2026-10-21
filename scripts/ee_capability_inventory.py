#!/usr/bin/env python3
"""Generate a privacy-safe, pinned Earth Engine API compatibility inventory.

Normal generation reads the pinned public SDK metadata, local source
declarations, and a checked-in sanitized evidence snapshot. The opt-in refresh
mode reads only allowlisted fields from local audit records to regenerate that
snapshot. This tool never imports application modules, executes user code,
starts services, or accesses a network. SDK signatures and local compiler
declarations are reported as separate evidence layers.
"""
from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1

# These limits are curated from the local translator and compatibility docs.
# They describe known partial semantics; absence from this table is not evidence
# that every argument is implemented.
KNOWN_PARTIAL_LIMITS: dict[str, list[str]] = {
    "ImageCollection.load": ["A non-null versioned collection load is rejected."],
    "Image.load": ["Image version values other than the unversioned sentinel are rejected."],
    "Collection.map": ["dropNulls=true routes through finite per-image evaluation and remains subject to the 1000-frame local cap."],
    "Image.updateMask": ["Binary masks only; fractional masks and opacity semantics are not supported."],
    "Image.mask": ["The getter path is declared; the mask setter path is rejected."],
    "Image.reduceRegion": ["crsTransform, bestEffort, and custom tileScale are rejected; local pixel/resource limits also apply."],
    "List.sequence": ["The count form is rejected; start/end/step is the supported local form."],
    "Projection": ["Projection transforms are rejected; supported local geometry/grid behavior is narrower than GEE."],
    "GeometryConstructors": ["Geodesic and non-EPSG:4326 geometry semantics are rejected by the local translator."],
    "ImageCollection.reduce": ["Only implemented reducer families and local collection/data semantics are available."],
    "ImageCollection.qualityMosaic": ["Requires a nonempty local collection, the requested quality band, and identical band names/order on every image. Invalid quality pixels are excluded and the selected scene's payload masks are retained; equal valid qualities currently select the last collection item. These semantics have not been compared with Google."],
    "Date.difference": ["Inputs must resolve to local millisecond scalars in the supported calendar range; only year, month, week, day, hour, minute, and second units are accepted. Year/month use average-duration constants as a local policy, and direct Google numerical parity is unverified."],
    "Date.getRelative": ["Inputs must resolve to local scalar dates in years 1..9999; only UTC is supported. Selected calendar pairs use ISO Monday-based week rules; week-of-month, same-unit, unsupported pairs, and unsupported containing units are rejected. Week boundaries are not Google-verified."],
    "Date.getFraction": ["Inputs must resolve to local scalar dates in years 1..9999; only UTC is supported. Week fractions use ISO Monday-based boundaries, with no direct Google boundary comparison."],
    "Number.bitCount": ["Static scalar inputs only; accepts exact signed-64-bit integers and counts the 64-bit two's-complement representation. Raster Image.bitCount is not implied."],
    "Number.bitwiseNot": ["Static scalar inputs only; accepts exact signed-64-bit integers and applies the smallest containing signed width among 8/16/32/64 bits. Raster Image.bitwiseNot is not implied."],
    "Number.bitwiseAnd": ["Static scalar inputs only; verified subset is nonnegative exact signed-64-bit integer operands. Negative operand coercion and raster Image.bitwiseAnd are not supported by this handler."],
    "Number.bitwiseOr": ["Static scalar inputs only; verified subset is nonnegative exact signed-64-bit integer operands. Negative operand coercion and raster Image.bitwiseOr are not supported by this handler."],
    "Number.bitwiseXor": ["Static scalar inputs only; verified subset is nonnegative exact signed-64-bit integer operands. Negative operand coercion and raster Image.bitwiseXor are not supported by this handler."],
    "Number.leftShift": ["Static scalar inputs only; shift counts must be 0..63, the left operand must be nonnegative, and the result must fit signed 64-bit. Raster Image.leftShift is not implied."],
    "Number.rightShift": ["Static scalar inputs only; accepts exact signed-64-bit operands and shift counts 0..63, with signed arithmetic right shift. Raster Image.rightShift is not implied."],
    "Image.toFloat": ["Uses the local adapter to cast raster cells to Float32; Float32 callback arithmetic is the supported path, not a claim of Google numerical parity."],
    "Image.toDouble": ["Uses the local adapter to cast raster cells to Float64, but subsequent Float64 pixel arithmetic and temporal reductions are rejected by the pinned callback backend. Cast after arithmetic or explicitly use toFloat before arithmetic; Google parity is unverified."],
    "reduce": ["Only the explicitly implemented reducer names and local semantics are available."],
}

CLIENT_ALIAS_LOWERINGS = [
    {
        "client_api": "Filter.eq",
        "serialized_calls": ["Filter.equals"],
        "detail": "The convenience method maps eq to the canonical equals algorithm.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.neq",
        "serialized_calls": ["Filter.equals", "Filter.not"],
        "detail": "The convenience method builds eq and negates it.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.lt",
        "serialized_calls": ["Filter.lessThan"],
        "detail": "The convenience method maps lt to the canonical lessThan algorithm.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.gte",
        "serialized_calls": ["Filter.lessThan", "Filter.not"],
        "detail": "The convenience method builds lt and negates it.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.gt",
        "serialized_calls": ["Filter.greaterThan"],
        "detail": "The convenience method maps gt to the canonical greaterThan algorithm.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.lte",
        "serialized_calls": ["Filter.greaterThan", "Filter.not"],
        "detail": "The convenience method builds gt and negates it.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.inList",
        "serialized_calls": ["Filter.listContains"],
        "detail": "The official helper swaps field/value roles while constructing Filter.listContains; there is no distinct Filter.inList RPC signature.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.date",
        "serialized_calls": ["DateRange", "Filter.dateRangeContains"],
        "detail": "The helper builds a DateRange and then a dateRangeContains filter on system:time_start.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.bounds",
        "serialized_calls": ["Feature", "Filter.intersects"],
        "detail": "The helper constructs a Feature and an intersects filter for the all-geometry field.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.metadata",
        "serialized_calls": ["Filter.equals", "Filter.not", "other Filter.* operators"],
        "detail": "The helper maps a metadata operator string to a Filter algorithm and can wrap it with Filter.not.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Collection.filterDate",
        "serialized_calls": ["DateRange", "Filter.dateRangeContains", "Collection.filter"],
        "detail": "The client helper creates a date filter and applies Collection.filter.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Collection.filterBounds",
        "serialized_calls": ["Feature", "Filter.intersects", "Collection.filter"],
        "detail": "The client helper creates a bounds filter and applies Collection.filter.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Collection.filterMetadata",
        "serialized_calls": ["Filter.*", "Collection.filter"],
        "detail": "The helper resolves the operator name to a Filter call and applies Collection.filter.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Collection.sort",
        "serialized_calls": ["Collection.limit"],
        "detail": "The pinned client calls Collection.limit with an undefined max and the property/order arguments; the backend must honor that exact serialized form.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "ImageCollection.first",
        "serialized_calls": ["Collection.first"],
        "detail": "The typed client method serializes through the generic Collection.first operation.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "ImageCollection.select",
        "serialized_calls": ["Collection.map", "Image.select"],
        "detail": "The client maps Image.select over the collection; it is not a separate API algorithm signature.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Image.cat / Image.rgb",
        "serialized_calls": ["Image.constant", "Image.addBands", "Image.select"],
        "detail": "These client-side constructors lower to constant/addBands and optional select calls.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
]


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _expand_handler_expression(node: ast.AST, symbols: dict[str, set[str]] | None = None) -> set[str]:
    """Evaluate the simple literal/generator expression used for handlers."""
    symbols = symbols or {}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "frozenset" and len(node.args) == 1:
        return _expand_handler_expression(node.args[0], symbols)
    if isinstance(node, ast.Name) and node.id in symbols:
        return set(symbols[node.id])
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Set):
        return set().union(*(_expand_handler_expression(item, symbols) for item in node.elts)) if node.elts else set()
    if isinstance(node, ast.Tuple):
        return set().union(*(_expand_handler_expression(item, symbols) for item in node.elts)) if node.elts else set()
    if isinstance(node, ast.Starred):
        return _expand_handler_expression(node.value, symbols)
    if isinstance(node, ast.GeneratorExp) and len(node.generators) == 1:
        generator = node.generators[0]
        if not isinstance(generator.target, ast.Name) or not isinstance(generator.iter, (ast.Tuple, ast.List)):
            raise ValueError("Unsupported handler generator expression")
        values: set[str] = set()
        for item in generator.iter.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                raise ValueError("Handler generator must enumerate string literals")
            if isinstance(node.elt, ast.BinOp) and isinstance(node.elt.op, ast.Add):
                if isinstance(node.elt.left, ast.Constant) and isinstance(node.elt.left.value, str) and isinstance(node.elt.right, ast.Name) and node.elt.right.id == generator.target.id:
                    values.add(node.elt.left.value + item.value)
                    continue
            raise ValueError("Unsupported handler generator template")
        return values
    raise ValueError(f"Unsupported handler inventory syntax: {type(node).__name__}")


def read_declared_handlers(source: Path) -> set[str]:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename="gee/ee_translate.py")
    date_tree = ast.parse(source.with_name("ee_dates.py").read_text(encoding="utf-8"), filename="gee/ee_dates.py")
    integer_tree = ast.parse(source.with_name("ee_integer.py").read_text(encoding="utf-8"), filename="gee/ee_integer.py")
    symbols: dict[str, set[str]] = {}
    for module_tree, symbol_name in (
        (date_tree, "SUPPORTED_DATE_FUNCTIONS"),
        (integer_tree, "SUPPORTED_INTEGER_FUNCTIONS"),
    ):
        for statement in module_tree.body:
            if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == symbol_name for target in statement.targets
            ):
                symbols[symbol_name] = _expand_handler_expression(statement.value)
                break
        else:
            raise ValueError(f"{symbol_name} declaration was not found")
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "SUPPORTED_FUNCTIONS" for target in statement.targets):
            continue
        value = statement.value
        if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Sub):
            handlers = _expand_handler_expression(value.left, symbols) - _expand_handler_expression(value.right, symbols)
        else:
            handlers = _expand_handler_expression(value, symbols)
        return handlers
    raise ValueError("SUPPORTED_FUNCTIONS declaration was not found")


def _canonical_name(official_name: str) -> str:
    return official_name.removeprefix("algorithms/")


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


def _snapshot_path(root: Path) -> Path:
    return root / "reports" / "gee-evidence-snapshot.json"


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


def render_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root (defaults to this checkout)")
    parser.add_argument("--output", type=Path, default=Path("reports/gee-api-inventory.json"), help="Output path relative to --root unless absolute")
    parser.add_argument(
        "--refresh-local-evidence",
        action="store_true",
        help="Explicitly read allowlisted local audit fields and write the sanitized reports/gee-evidence-snapshot.json before generating the report",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    if args.refresh_local_evidence:
        snapshot = refresh_local_evidence_snapshot(root)
        print(f"Wrote {snapshot.relative_to(root) if snapshot.is_relative_to(root) else snapshot.name}")
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_json(build_inventory(root)), encoding="utf-8")
    print(f"Wrote {output.relative_to(root) if output.is_relative_to(root) else output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
