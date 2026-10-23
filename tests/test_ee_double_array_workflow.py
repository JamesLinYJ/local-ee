"""Offline Python/JavaScript parity for fixed Float64 raster-array fitting."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess

import numpy as np
import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_array_reshape import local as existing_array_fixture
from ee_float64_graph_reference import (
    double_matrix_sample_reference, evaluate_float64_graph,
    float64_values_handler,
)


ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLE = ROOT / "examples/56_GEE_python_double_matrix.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/10_双精度数组回归.js"
COLLECTION_ID = "sentinel-2-l2a"
PROJECTION = {
    "proj:code": "EPSG:32649",
    "proj:transform": [10, 0, 220000, 0, -10, 3420000],
}
EXPECTED_BANDS = {
    "coefficients": ["intercept", "slope"],
    "predictions": ["x0", "x1", "x2"],
    "prediction_frobenius_norm": ["prediction_frobenius_norm"],
    "selected_prediction": ["prediction_at_x1"],
    "observation_trace": ["observation_trace"],
    "precision_controls": [
        "blue_float64", "blue_float32", "blue_float32_then_float64",
    ],
}


def _example():
    spec = importlib.util.spec_from_file_location("double_matrix_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _local_fixture():
    local = existing_array_fixture.__wrapped__()
    for item in local["items"][COLLECTION_ID]:
        item["properties"].update(PROJECTION)
    return local


def _make_ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def _encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def _invocation_names(expression):
    return [
        node["functionName"]
        for _key, node in expression.get("scope", [])
        if isinstance(node, dict) and node.get("type") == "Invocation"
    ]


def _python_results(local):
    metadata, items = local["catalog"][0], local["items"]
    with OfflineGuard() as guard:
        ee = _make_ee()
        outputs = _example().build_workflow(
            ee, ee.ImageCollection(COLLECTION_ID).first(),
        )
        assert set(outputs) == set(EXPECTED_BANDS)
        compiled = {
            name: compile_expression(_encode(ee, value), [metadata], items)
            for name, value in outputs.items()
        }
        encoded = {name: _encode(ee, value) for name, value in outputs.items()}
    assert guard.evidence()["attempt_count"] == 0
    return compiled, encoded


def _javascript_expressions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for pinned JavaScript SDK serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + f"""
const exampleSource = fs.readFileSync({json.dumps(JAVASCRIPT_EXAMPLE)}, 'utf8');
const factory = new Function('ee', exampleSource + '\\nreturn outputs;');
const outputs = factory(ee);
console.log(JSON.stringify({{
  attempts,
  outputs: Object.fromEntries(Object.entries(outputs).map(([name, value]) =>
    [name, ee.Serializer.encode(value)]))
}}));
"""
    completed = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True,
        text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["attempts"] == 0
    return result["outputs"]


def _numeric_result(compiled, name, local):
    result = compiled[name]
    validate(result["process_graph"])
    assert result["kind"] == "image"
    assert len(result["process_graph"]) <= 500
    assert result["source_item_ids"] == ["reshape-scene"]
    values, names, timed = evaluate_float64_graph(
        result, local["arrays"], grid=local["grid"],
        source_geometries={"reshape-scene": local["geometry"]},
    )
    assert names == EXPECTED_BANDS[name]
    assert timed is False
    return values


def test_python_javascript_compile_the_same_bounded_double_array_graphs():
    local = _local_fixture()
    python, encoded = _python_results(local)
    javascript = _javascript_expressions()
    assert set(javascript) == set(python) == set(EXPECTED_BANDS)
    for name, expression in javascript.items():
        result = compile_expression(expression, local["catalog"], local["items"])
        assert result == python[name], name
        assert result["bands"] == EXPECTED_BANDS[name]
        assert len(result["process_graph"]) <= 500
        assert _invocation_names(expression) == _invocation_names(encoded[name])

    calls = _invocation_names(encoded["coefficients"])
    for operation in (
        "Image.toDouble", "Image.toArray", "Image.arrayReshape",
        "Image.matrixSolve", "Image.copyProperties",
    ):
        assert operation in calls
    assert calls.index("Image.arrayReshape") < calls.index("Image.matrixSolve")
    assert max(index for index, name in enumerate(calls)
               if name == "Image.toDouble") < calls.index("Image.toArray")
    assert {"Image.matrixMultiply", "Image.arrayGet"} <= set(
        _invocation_names(encoded["selected_prediction"])
    )
    assert "Image.matrixFnorm" in _invocation_names(
        encoded["prediction_frobenius_norm"]
    )
    assert {"Image.matrixToDiag", "Image.matrixTrace"} <= set(
        _invocation_names(encoded["observation_trace"])
    )
    controls = _invocation_names(encoded["precision_controls"])
    assert {"Image.toFloat", "Image.toDouble"} <= set(controls)

    # Keep the three-scalar order, fixed array sizes, and original input metadata.
    assert _example().BANDS == ["red", "nir", "blue"]
    assert _example().DESIGN_MATRIX == [[1, 0], [1, 1], [1, 2]]
    for result in python.values():
        properties = result["properties"]
        assert properties["workflow"] == _example().SYNTHETIC_VERSION
        assert properties["system:index"] == "reshape-scene"
        assert properties["system:time_start"] == 1000
        assert properties["proj:code"] == "EPSG:32649"
        assert properties["proj:transform"] == PROJECTION["proj:transform"]
    assert python["coefficients"]["source_item_ids"] == ["reshape-scene"]
    source_load = next(
        node for node in python["coefficients"]["process_graph"].values()
        if node["process_id"] == "load_collection"
    )
    assert source_load["arguments"]["spatial_extent"] == {
        "west": 0, "south": 0, "east": 4, "north": 1,
    }


def test_double_solve_predictions_masks_and_cast_boundary_match_fraction_reference():
    local = _local_fixture()
    compiled, _encoded = _python_results(local)
    reference = double_matrix_sample_reference(
        local["arrays"]["reshape-scene"], local["grid"], local["geometry"],
    )
    actual = {
        name: _numeric_result(compiled, name, local)
        for name in EXPECTED_BANDS
    }

    for output_name, reference_name in (
        ("coefficients", "coefficients"),
        ("predictions", "predictions"),
        ("prediction_frobenius_norm", "prediction_frobenius_norm"),
        ("selected_prediction", "selected_prediction"),
        ("observation_trace", "observation_trace"),
        ("precision_controls", "precision_controls"),
    ):
        np.testing.assert_allclose(
            actual[output_name], reference[reference_name],
            rtol=2e-13, atol=2e-8, equal_nan=True,
        )

    # A missing red input masks every coefficient and prediction at that pixel.
    for name in ("coefficients", "predictions", "selected_prediction"):
        assert np.isnan(actual[name][:, 2]).all()
    # The independent blue precision control remains valid at all source pixels.
    controls = actual["precision_controls"]
    assert controls[0, 0] == 16_777_217.0
    assert controls[1, 0] == controls[2, 0] == 16_777_216.0
    assert controls[0, 0] - controls[1, 0] == 1.0
    # The selected x=1 prediction is the OLS mean and differs after Float32 loss.
    assert actual["selected_prediction"][0, 0] == pytest.approx(
        (100 + 1000 + 16_777_217) / 3, abs=2e-8,
    )


def test_fixed_array_shapes_and_existing_compiler_limits_are_kept():
    from gee.compat.earthengine.array_core import MAX_ARRAY_WORK
    from gee.compat.earthengine.raster_array_core import (
        MAX_RASTER_ARRAY_CELLS, MAX_RASTER_ARRAY_RANK,
    )

    assert MAX_ARRAY_WORK == 50_000
    assert MAX_RASTER_ARRAY_CELLS == 64
    assert MAX_RASTER_ARRAY_RANK == 8
    # The actual graph uses only 3x1 observations, 3x2 design, 2x1
    # coefficients, and 3x1 predictions: all far below existing array caps.
    assert 3 * 1 + 3 * 2 + 2 * 1 + 3 * 1 <= MAX_RASTER_ARRAY_CELLS


@pytest.mark.parametrize("case", [
    "source-positive-infinity", "source-negative-infinity",
    "float32-positive-overflow", "float32-negative-overflow",
])
def test_graph_oracle_rejects_direct_and_float32_overflow_infinities(case):
    if case == "source-positive-infinity":
        value = np.inf
    elif case == "source-negative-infinity":
        value = -np.inf
    else:
        finite_source = 1e40 if case == "float32-positive-overflow" else -1e40
        with np.errstate(over="ignore"):
            value = float(np.float32(finite_source))
        assert np.isinf(value)

    spec = {
        "dtype": None, "op": "add",
        "operands": [{"band": 0}, {"constant": struct.pack(">d", 0.0).hex()}],
        "v": 1,
    }
    arguments = {
        "data": {"from_node": "source"}, "spec": json.dumps(spec),
    }
    values = {"source": (np.array([[value]], dtype=np.float64), ["sample"], False)}
    with pytest.raises(ValueError, match="valid infinity"):
        float64_values_handler(arguments, values)


def test_graph_oracle_masks_nan_but_converts_nonfinite_results_to_nan():
    def evaluate_one(value, operation, right):
        spec = {
            "dtype": None, "op": operation,
            "operands": [
                {"band": 0}, {"constant": struct.pack(">d", right).hex()},
            ],
            "v": 1,
        }
        arguments = {
            "data": {"from_node": "source"}, "spec": json.dumps(spec),
        }
        values = {"source": (np.array([[value]], dtype=np.float64), ["sample"], False)}
        return float64_values_handler(arguments, values)[0]

    masked = evaluate_one(np.nan, "add", 0.0)
    overflowed = evaluate_one(np.finfo(np.float64).max, "multiply",
                              np.finfo(np.float64).max)
    assert np.isnan(masked).all()
    assert np.isnan(overflowed).all()
