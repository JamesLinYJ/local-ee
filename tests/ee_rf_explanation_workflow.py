"""Trusted offline fixture compilation shared by SDK/native explanation proofs."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.rf_explanation_processes import RF_EXPLAIN
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-rf-explanation-v1.json"


def example_module():
    spec = importlib.util.spec_from_file_location(
        "rf_explanation_example", ROOT / "examples/37_GEE_python_rf_explanation.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compiled_program():
    fixture = json.loads(FIXTURE.read_text())
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        results = {key: compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), [], {},
        ) for key, value in example_module().build_workflow(ee, fixture).items()}
    assert guard.evidence()["attempt_count"] == 0
    for result in results.values():
        if "process_graph" in result:
            validate(result["process_graph"])
    graph = results["explanation"]["process_graph"]
    explanation = next(node for node in graph.values() if node["process_id"] == RF_EXPLAIN)
    trainer = graph[explanation["arguments"]["model"]["from_node"]]
    return fixture, results, trainer["arguments"]
