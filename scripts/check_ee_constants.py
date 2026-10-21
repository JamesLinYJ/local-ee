"""Official SDK constant/date bands -> isolated native engine -> independent reference.

Requires a new GEE_AUDIT_DIR. GEE_EE_CASES may select fixture cases. This does
not query Google or mutate the live catalogue, accounts, scripts or jobs.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import numpy as np
import rasterio

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gee.ee_translate import compile_expression
from scripts.ee_acceptance.constant_fixture import create_inputs, references
from scripts.ee_acceptance.native_fixture import run_native


def run():
    audit = Path(os.environ["GEE_AUDIT_DIR"]).resolve()
    audit.mkdir(parents=True, exist_ok=False)
    folder = audit/"engine"
    folder.mkdir()
    (folder/"out").mkdir()
    metadata, items, arrays = create_inputs(folder)
    sdk = json.loads((ROOT/"tests/fixtures/ee-constant-1.7.49.json").read_text())
    expressions = sdk["raster_expressions"]
    cases = os.environ.get("GEE_EE_CASES", ",".join(expressions)).split(",")
    if not cases or any(name not in expressions for name in cases):
        raise ValueError("GEE_EE_CASES must name official constant fixture cases")
    process, cache = {}, {}
    labels, warnings = [], []

    def append(pid, arguments):
        key = json.dumps([pid, arguments], sort_keys=True)
        if key not in cache:
            nid = "n" + str(len(process))
            process[nid] = {"process_id": pid, "arguments": arguments}
            cache[key] = {"from_node": nid}
        return cache[key]

    outputs = []
    for case in cases:
        compiled = compile_expression(expressions[case], [metadata], {metadata["id"]: items})
        remap = {}
        def refs(value):
            if isinstance(value, list):
                return [refs(item) for item in value]
            if isinstance(value, dict):
                if "process_graph" in value:
                    return copy.deepcopy(value)
                if "from_node" in value:
                    return remap[value["from_node"]]
                return {key: refs(item) for key, item in value.items()}
            return value
        result = None
        for nid, node in compiled["process_graph"].items():
            remap[nid] = append(node["process_id"], refs(node["arguments"]))
            if node.get("result"):
                result = remap[nid]
        names = [case+"__"+band for band in compiled["bands"]]
        labels.extend(names)
        warnings.extend(compiled["warnings"])
        outputs.append(append("rename_labels", {"data": result, "dimension": "bands", "target": names}))
    result = outputs[0]
    for other in outputs[1:]:
        result = append("merge_cubes", {"cube1": result, "cube2": other})
    result = append("save_result", {"data": result, "format": "GTiff"})
    process[result["from_node"]]["result"] = True
    (audit/"compiled.json").write_text(json.dumps({"process_graph": process, "labels": labels,
        "warnings": sorted(set(warnings))}, indent=2))
    path = run_native(ROOT, audit, folder, process, metadata, items)
    comparisons = []
    with rasterio.open(path) as output:
        expected = references(output, items, arrays)
        cursor = 1
        for case in cases:
            for reference in expected[case]:
                actual = output.read(cursor, masked=True).filled(np.nan)
                mask_errors = int(np.sum(np.isfinite(actual) != np.isfinite(reference)))
                valid = np.isfinite(actual) & np.isfinite(reference)
                error = float(np.abs(actual[valid] - reference[valid]).max(initial=0))
                # Date/large constants must stay exact; SD alone needs rounding tolerance.
                tolerance = 1e-12 if case == "dateSd" else 0
                passed = mask_errors == 0 and bool(np.allclose(actual[valid], reference[valid], rtol=0, atol=tolerance))
                comparisons.append({"case": labels[cursor-1], "valid_pixels": int(valid.sum()),
                    "mask_mismatches": mask_errors, "max_absolute_error": error,
                    "absolute_tolerance": tolerance, "passed": passed})
                cursor += 1
        expected_dtype = "float32" if cases == ["boundFloat"] else "float64"
        dtype_passed = all(dtype == expected_dtype for dtype in output.dtypes)
        report = {"sdk": sdk["sdk"], "source_commit": sdk["source_commit"], "cases": comparisons,
            "graph_nodes": len(process), "shape": list(output.shape), "crs": str(output.crs),
            "output_bands": list(output.descriptions), "expected_band_order": labels,
            "band_order_passed": list(output.descriptions) == labels,
            "output_dtypes": list(output.dtypes), "expected_dtype": expected_dtype,
            "dtype_passed": dtype_passed, "fixture": "Synthetic three scenes; differing footprints; a/c share timestamp; blue is entirely NoData.",
            "reference": "Independent Rasterio masks/reprojection and centered NumPy date statistics.",
            "google_service_comparison": False}
    report["passed"] = dtype_passed and report["band_order_passed"] and all(row["passed"] for row in comparisons)
    (audit/"validation.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"passed": report["passed"], "comparisons": comparisons}), flush=True)
    if not report["passed"]:
        raise AssertionError("Constant/date acceptance failed; inputs and outputs retained")
    inputs = []
    for iid in "abc":
        for source in sorted((folder/iid).iterdir()):
            inputs.append({"file": str(source.relative_to(audit)), "bytes": source.stat().st_size,
                           "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
        shutil.rmtree(folder/iid)
    (audit/"generated-input-cleanup.json").write_text(json.dumps({"inputs": inputs,
        "reproduction": "scripts/check_ee_constants.py regenerates these synthetic inputs."}, indent=2)+"\n")


if __name__ == "__main__":
    run()
