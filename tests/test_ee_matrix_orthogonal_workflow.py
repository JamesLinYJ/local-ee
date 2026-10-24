"""Offline Python/JavaScript graph parity and composition budgets for QR/SVD."""
import copy
import hashlib
import json
import re
import shutil

import numpy as np
import pytest

from ee_matrix_orthogonal_workflow_helpers import (
    ITEM_ID, OUTPUT_BANDS, example_module, javascript_expressions, local_fixture,
    make_ee, numeric_result, python_results, record_evidence,
    budget_limited_outputs,
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


def _wire_sha256(expression):
    canonical = json.dumps(
        expression, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _compile_with_metrics(expression, local, monkeypatch):
    """Capture normal compile-entry work while using the production compiler path."""
    import gee.compat.earthengine.compile as compiler

    captured = {}
    translator_type, graph_type = compiler.Translator, compiler.Graph

    class RecordingTranslator(translator_type):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured["translator"] = self

    class RecordingGraph(graph_type):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured["graph"] = self

    monkeypatch.setattr(compiler, "Translator", RecordingTranslator)
    monkeypatch.setattr(compiler, "Graph", RecordingGraph)
    result = compile_expression(expression, local["catalog"], local["items"])
    return result, captured["translator"].steps, len(captured["graph"].graph)


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
     "Integer Image operation exceeds the 500-node process graph budget"),
    ("svd_truncation_reconstruction",
     "Float64 Image operation is unsupported: Image.multiply exceeds the shared 50000-step compilation work budget"),
])
def test_unavailable_factor_compositions_keep_exact_budget_diagnostics(
    name, diagnostic, monkeypatch,
):
    local = local_fixture()
    with OfflineGuard() as guard:
        ee = make_ee()
        expression = budget_limited_outputs(ee)[name]
        encoded = ee.serializer.encode(expression, for_cloud_api=False)
        original_wire = copy.deepcopy(encoded)
        assert _wire_sha256(encoded) == {
            "qr_tall_normal_residual": "fe9d2b261091d3b93861135205569f1789b109bab8e6fd5837eb3798bd0b7a16",
            "svd_truncation_reconstruction": "cf9ac2f5672e6d7ab1f2d2017bfad18536e0c41a149ecda430f94bee30b2d1bf",
        }[name]
        with pytest.raises(UnsupportedEEError, match=re.escape(diagnostic)) as error:
            _compile_with_metrics(encoded, local, monkeypatch)
    assert guard.evidence()["attempt_count"] == 0
    assert str(error.value) == diagnostic
    assert encoded == original_wire
    record_evidence(f"budget-{name}", {
        "expression": name,
        "diagnostic": str(error.value),
        "work_budget": 50000,
        "wire_sha256": _wire_sha256(encoded),
        "wire_unchanged_after_compile": encoded == original_wire,
        "scope": "real factor composition rejected before graph output; no budget increase",
    })


def test_newly_compiling_truncation_svd_rank2_matches_independent_numpy_reference(
    monkeypatch,
):
    local = local_fixture()
    with OfflineGuard() as guard:
        ee = make_ee()
        expression = budget_limited_outputs(ee)["svd_truncation_rank2"]
        encoded = ee.serializer.encode(expression, for_cloud_api=False)
        original_wire = copy.deepcopy(encoded)
        wire_sha256 = _wire_sha256(encoded)
        assert wire_sha256 == (
            "bbfb9efbe9d032c940fa910b864db60ff61b936d331d030762ee90949335c984"
        )
        graph, steps, nodes = _compile_with_metrics(encoded, local, monkeypatch)
        assert encoded == original_wire
        actual, bands, timed = numeric_result(graph, local)

    assert guard.evidence()["attempt_count"] == 0
    assert graph["kind"] == "image"
    assert graph["source_item_ids"] == [ITEM_ID]
    assert bands == [f"r{row}_c{column}" for row in range(3) for column in range(3)]
    assert timed is False
    assert actual.dtype == np.float64
    assert actual.shape == (9, len(local["grid"]))
    assert 0 < steps <= 50000
    assert 0 < nodes == len(graph["process_graph"]) <= 500
    matrix_nodes = _native_matrix_nodes(graph)
    assert len(matrix_nodes) == 1
    matrix_spec = json.loads(matrix_nodes[0]["arguments"]["spec"])
    assert (matrix_spec["op"], matrix_spec["rows"], matrix_spec["cols"]) == (
        "svd", 3, 3,
    )

    source = local["arrays"][ITEM_ID]
    matrices = np.stack([
        source[name] for name in example_module().TRUNCATION_BANDS
    ], axis=1).reshape((-1, 3, 3))
    masked_pixels = []
    errors = []
    full_rank_residuals = []
    for pixel, matrix in enumerate(matrices):
        observed = actual[:, pixel].reshape((3, 3))
        if not np.isfinite(matrix).all():
            masked_pixels.append(pixel)
            assert np.isnan(observed).all()
            continue
        assert np.isfinite(observed).all()
        left, singular, right = np.linalg.svd(matrix, full_matrices=False)
        expected = (left[:, :2] * singular[:2]) @ right[:2, :]
        np.testing.assert_allclose(observed, expected, rtol=0, atol=1e-12)
        errors.extend(np.abs(observed - expected).ravel().tolist())
        if pixel == 0:
            determinant = (
                matrix[0, 0] * (matrix[1, 1] * matrix[2, 2] - matrix[1, 2] * matrix[2, 1])
                - matrix[0, 1] * (matrix[1, 0] * matrix[2, 2] - matrix[1, 2] * matrix[2, 0])
                + matrix[0, 2] * (matrix[1, 0] * matrix[2, 1] - matrix[1, 1] * matrix[2, 0])
            )
            assert determinant == 9
            residual = float(np.linalg.norm(observed - matrix, ord="fro"))
            assert residual > 0.3
            np.testing.assert_allclose(residual, singular[2], rtol=2e-12, atol=1e-12)
            full_rank_residuals.append(residual)

    assert masked_pixels == [5]
    assert len(matrices) - len(masked_pixels) == 11
    assert len(full_rank_residuals) == 1
    assert max(errors) <= 1e-12
