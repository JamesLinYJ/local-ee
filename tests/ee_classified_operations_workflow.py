"""Offline official-client expressions for the post-classification example."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.runtime_table_graph import runtime_table_chain
from gee.runtime_table_spec import PROCESS
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


def example_module():
    spec = importlib.util.spec_from_file_location(
        "classified_tables_example", ROOT / "examples/36_GEE_python_classified_tables.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compiled_program(fixture, parameters):
    module = example_module()
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        values = module.build_workflow(ee, fixture, parameters)
        results = {key: compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), *module.local_metadata(fixture),
        ) for key, value in values.items()}
    assert guard.evidence()["attempt_count"] == 0
    for value in results.values():
        validate(value["process_graph"])
    graph = results["limited"]["process_graph"]
    final = next(key for key, node in graph.items() if node.get("result"))
    assert graph[final]["process_id"] == PROCESS
    classifier, operations = runtime_table_chain(graph, final)
    model = graph[classifier["arguments"]["model"]["from_node"]]
    assert len(operations) == 3
    return results, classifier["arguments"]["spec"], model["arguments"]["spec"], operations
