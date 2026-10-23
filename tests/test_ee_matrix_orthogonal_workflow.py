"""Offline Python/JavaScript graph parity and composition budgets for QR/SVD."""
import re
import shutil

import pytest

from ee_matrix_orthogonal_workflow_helpers import (
    ITEM_ID, OUTPUT_BANDS, example_module, javascript_expressions, local_fixture,
    make_ee, python_results, record_evidence, budget_limited_outputs,
)
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


def _sdk_calls(expressions):
    return [node for expression in expressions.values()
            for _key, node in expression.get("scope", [])
            if isinstance(node, dict) and node.get("type") == "Invocation"]


def _compile_javascript(local, expressions):
    return {
        name: compile_expression(expression, local["catalog"], local["items"])
        for name, expression in expressions.items()
    }


def _native_matrix_nodes(graph):
    return [node for node in graph["process_graph"].values()
            if node["process_id"] == "local_ee_matrix_values"]


def test_offline_python_and_javascript_serialize_and_compile_same_factor_workflows():
    if shutil.which("node") is None:
        pytest.skip("Node is required for pinned JavaScript SDK graph parity")
    local = local_fixture()
    python_graphs, python_expressions, python_attempts = python_results(local)
    javascript, javascript_attempts = javascript_expressions()
    js_graphs = _compile_javascript(local, javascript)

    assert python_attempts == javascript_attempts == 0
    assert set(python_graphs) == set(javascript) == set(OUTPUT_BANDS)
    for name, bands in OUTPUT_BANDS.items():
        assert python_graphs[name] == js_graphs[name], name
        assert python_graphs[name]["bands"] == bands
        assert python_graphs[name]["source_item_ids"] == [ITEM_ID]
        assert python_graphs[name]["properties"]["workflow"] == \
            example_module().SYNTHETIC_VERSION
        assert len(python_graphs[name]["process_graph"]) <= 500

    for name in (
        "svd_tall_reconstruction", "svd_tall_rank2",
        "svd_wide_reconstruction", "svd_wide_rank2",
        "svd_float32_then_double_reconstruction",
        "svd_truncation_u", "svd_truncation_s", "svd_truncation_v",
    ):
        assert len(_native_matrix_nodes(python_graphs[name])) == 1, name

    calls = _sdk_calls(python_expressions)
    factor_calls = [node for node in calls if node["functionName"] in {
        "Image.matrixQRDecomposition", "Image.matrixSingularValueDecomposition",
    }]
    assert {node["functionName"] for node in factor_calls} == {
        "Image.matrixQRDecomposition", "Image.matrixSingularValueDecomposition",
    }
    assert all(set(node["arguments"]) == {"image"} for node in factor_calls)
    names = {node["functionName"] for node in calls}
    assert {"Image.matrixMultiply", "Image.matrixSolve", "Image.arraySlice",
            "Image.arrayFlatten"} <= names

    record_evidence("graph-parity", {
        "fixture": example_module().SYNTHETIC_VERSION,
        "source_collection": "sentinel-2-l2a",
        "source_item_id": ITEM_ID,
        "source_values": "declared synthetic Float64 bands; no private imagery",
        "outputs": list(OUTPUT_BANDS),
        "graph_node_counts": {
            name: len(graph["process_graph"])
            for name, graph in python_graphs.items()
        },
        "native_matrix_producer_counts": {
            name: len(_native_matrix_nodes(python_graphs[name]))
            for name in python_graphs
        },
        "one_native_matrix_producer_outputs": [
            "svd_tall_reconstruction", "svd_tall_rank2",
            "svd_wide_reconstruction", "svd_wide_rank2",
            "svd_float32_then_double_reconstruction",
            "svd_truncation_u", "svd_truncation_s", "svd_truncation_v",
        ],
        "python_javascript_graphs_equal": True,
        "python_network_attempts": python_attempts,
        "javascript_network_attempts": javascript_attempts,
        "scope": "offline SDK serialization and local graph compilation; no service or Spark",
    })


@pytest.mark.parametrize(("name", "diagnostic"), [
    ("qr_tall_normal_residual",
     "Integer Image graph exceeds the shared 50000-step work budget"),
    ("svd_truncation_reconstruction",
     "Static Array operation exceeds the compilation work budget"),
    ("svd_truncation_rank2",
     "Static Array operation exceeds the compilation work budget"),
])
def test_unavailable_factor_compositions_keep_exact_budget_diagnostics(name, diagnostic):
    local = local_fixture()
    with OfflineGuard() as guard:
        ee = make_ee()
        expression = budget_limited_outputs(ee)[name]
        encoded = ee.serializer.encode(expression, for_cloud_api=False)
        with pytest.raises(UnsupportedEEError, match=re.escape(diagnostic)) as error:
            compile_expression(encoded, local["catalog"], local["items"])
    assert guard.evidence()["attempt_count"] == 0
    assert str(error.value) == diagnostic
    record_evidence(f"budget-{name}", {
        "expression": name,
        "diagnostic": str(error.value),
        "work_budget": 50000,
        "scope": "real factor composition rejected before graph output; no budget increase",
    })
