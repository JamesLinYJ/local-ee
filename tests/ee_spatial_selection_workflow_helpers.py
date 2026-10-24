"""Offline dual-client harness for spatial selection and ROI export workflows."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

from ee_random_split_parity import JAVASCRIPT, semantic_wire
from gee.ee_python_client import configure_local_ee
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLE = ROOT / "examples/67_GEE_python_spatial_selection.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/21_球面筛选与研究区.js"


def load_python_example():
    spec = importlib.util.spec_from_file_location(
        "spatial_selection_example", PYTHON_EXAMPLE,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_wire(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def python_wires():
    example = load_python_example()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        values = example.build_workflow(ee)
        wires = json_wire(example.encode_workflow(ee, values))
    assert guard.evidence()["attempt_count"] == 0
    return wires


def javascript_wires():
    node = shutil.which("node")
    assert node is not None, "Node is required for pinned JavaScript SDK parity"
    prefix = JAVASCRIPT.split("const config = JSON.parse", 1)[0]
    script = prefix + r"""
const example = require('./examples/javascript/21_球面筛选与研究区.js');
const values = example.buildWorkflow(ee);
const outputs = example.encodeWorkflow(ee, values);
process.stdout.write(JSON.stringify({outputs, regions: example.REGIONS,
  points: example.POINTS, attempts}));
"""
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT, text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    return json_wire(decoded["outputs"]), decoded["regions"], decoded["points"]


def semantic(value):
    return semantic_wire(json_wire(value))


def invocation_calls(value, function_name=None):
    calls = []
    if type(value) is list:
        for child in value:
            calls.extend(invocation_calls(child, function_name))
    elif type(value) is dict:
        if (value.get("type") == "Invocation"
                and (function_name is None or value.get("functionName") == function_name)):
            calls.append(value)
        for child in value.values():
            calls.extend(invocation_calls(child, function_name))
    return calls


def compile_wires(wires):
    from gee.ee_translate import compile_expression

    outputs = {
        name: compile_expression(wires[name], [], {})["value"]
        for name in ("dateline_selected", "polar_selected", "merge_omitted",
                     "merge_null", "merge_typed")
    }
    outputs["filter_results"] = {
        name: compile_expression(wire, [], {})["value"]
        for name, wire in wires["filter_results"].items()
    }
    outputs["selected"] = compile_expression(wires["selected"], [], {})["value"]
    outputs["table"] = compile_expression(
        wires["table"], [], {}, for_table_export=True,
    )["value"]
    return outputs
