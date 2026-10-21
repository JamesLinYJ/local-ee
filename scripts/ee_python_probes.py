"""Generate deterministic, network-denied probes with the pinned Python SDK.

Only the fixed SDK expressions in probe_cases.py are evaluated. This generator
owns its process's local EE session; run it as a module in a separate process.
The guard measures denied Python network attempts, not kernel network traffic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from gee import ee_python_client
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import (
    BANDS, CASES, COLLECTION_ID, synthetic_inputs,
)

ROOT = Path(__file__).resolve().parents[1]
SDK = "1.7.49"
SOURCE_COMMIT = "e189e4b89e785019ea5642ea8e80cb644749cd4a"
SIGNATURES = ROOT / "vendor/earthengine-js/algorithms.json"
FIXTURE = ROOT / "tests/fixtures/ee-python-1.7.49.json"
URL = "http://127.0.0.1:8787/openeo/1.2"
TOKEN = "a" * 48  # Synthetic in-process adapter token; no credential is used.


def _encode(ee: Any, value: Any) -> dict[str, Any]:
    return ee.serializer.encode(value, is_compound=True, for_cloud_api=False)


def _compiler_result(expression, metadata, items):
    try:
        result = compile_expression(expression, [metadata], items)
    except UnsupportedEEError as error:
        return {"status": "rejected", "reason": str(error)}
    compiled = {"status": "passed", "kind": result["kind"]}
    for key in ("bands", "reducer"):
        if key in result:
            compiled[key] = result[key]
    if result["kind"] == "value":
        compiled["value"] = result["value"]
    return compiled


def _serialize_case(ee, source, roi):
    obj = eval(source, {"ee": ee, "roi": roi, "__builtins__": {}})
    if not isinstance(obj, ee.batch.Task):
        return _encode(ee, obj), None
    from gee.ee_python_exports import local_options

    action = "export_image" if obj.task_type == ee.batch.Task.Type.EXPORT_IMAGE else "export_table"
    prepared = local_options(ee, action, obj.config.copy(), lambda value: _encode(ee, value))
    return _encode(ee, prepared["expression"]), prepared["options"]


def generate_fixture():
    metadata, items, roi_geojson = synthetic_inputs()
    with OfflineGuard() as guard:
        import ee

        ee_python_client.configure_local_ee(URL, TOKEN, signatures_path=SIGNATURES)
        roi = ee.Geometry(roi_geojson, proj="EPSG:4326", geodesic=False)
        rows = []
        for case_id, family, source in CASES:
            row = {
                "id": case_id, "family": family, "python": source,
                "engine_execution": {"status": "not_run"},
                "independent_numerical_validation": {"status": "not_run"},
                "google_same_data_comparison": {"status": "not_run"},
            }
            try:
                expression, options = _serialize_case(ee, source, roi)
            except (ee.EEException, TypeError, ValueError) as error:
                row["serialization"] = {"status": "rejected", "reason": str(error)}
                row["compilation"] = {"status": "not_run"}
            else:
                row["serialization"] = {"status": "passed", "expression": expression}
                row["compilation"] = _compiler_result(expression, metadata, items)
                if options is not None:
                    row["export_options"] = options
            rows.append(row)
    return {
        "schema": "local-ee-python-probes/v2",
        "sdk": SDK,
        "source_commit": SOURCE_COMMIT,
        "signature_sha256": hashlib.sha256(SIGNATURES.read_bytes()).hexdigest(),
        "signature_count": len(ee_python_client._load_signatures(SIGNATURES)),
        "catalogue": {
            "id": COLLECTION_ID,
            "items": [item["id"] for item in items[COLLECTION_ID]], "bands": BANDS,
        },
        "network_requests": guard.evidence()["attempt_count"],
        "network_evidence": guard.evidence(),
        "interpretation": "Targeted whole-expression S/C probes; compilation does not establish engine, independent numerical or Google equivalence and is not a full-API compatibility rate",
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=FIXTURE)
    parser.add_argument("--check", action="store_true", help="Fail on drift without replacing the output")
    args = parser.parse_args()
    fixture = generate_fixture()
    rendered = json.dumps(fixture, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            parser.exit(1, "Python probe fixture differs; regenerate and review its changes\n")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    counts = {
        stage: sum(row[stage]["status"] == "passed" for row in fixture["cases"])
        for stage in ("serialization", "compilation")
    }
    print(f"{len(fixture['cases'])} targeted cases: {counts['serialization']} SDK-serialized, "
          f"{counts['compilation']} compiled; engine/numerical/Google checks not run")


if __name__ == "__main__":
    main()
