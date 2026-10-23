"""Unsupported forms, shape limits and preflight guards for raster matrixSolve."""
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.compat.earthengine.raster_matrix_solve import invoke_raster_matrix
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_matrix_solve import (
    compile_value,
    design_image,
    encode,
    first_image,
    local,
    response_column,
    ee,
)


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def constant_array_image(ee, matrix, cast=True):
    image = ee.Image.constant(ee.Array(matrix))
    return image.toFloat() if cast else image


def valid_expression(ee):
    return design_image(ee).matrixSolve(response_column(ee))


def compile_raw(value, local):
    return compile_expression(value, local["catalog"], local["items"])


def test_sdk_signature_requires_image1_image2_and_rejects_unknown_arguments(ee, local):
    encoded = encode(ee, valid_expression(ee).arrayFlatten([["a", "b"], ["rhs"]]))
    calls = [node for _, node in encoded["scope"]
             if isinstance(node, dict) and node.get("type") == "Invocation"
             and node.get("functionName") == "Image.matrixSolve"]
    assert len(calls) == 1
    assert set(calls[0]["arguments"]) == {"image1", "image2"}

    mutated = encode(ee, valid_expression(ee).arrayFlatten([["a", "b"], ["rhs"]]))
    solve_call = next(node for _, node in mutated["scope"]
                      if isinstance(node, dict) and node.get("functionName") == "Image.matrixSolve")
    solve_call["arguments"]["ignored"] = 4
    with pytest.raises(UnsupportedEEError):
        compile_raw(mutated, local)

    with pytest.raises(UnsupportedEEError):
        compile_raw({"type": "Invocation", "functionName": "Image.matrixSolve",
                     "arguments": {"image1": [], "image2": []}}, local)
    with pytest.raises(UnsupportedEEError):
        compile_raw({"type": "Invocation", "functionName": "Image.matrixSolve",
                     "arguments": {"left": [], "right": []}}, local)


def test_only_typed_raster_arrays_with_explicit_top_level_casts_are_accepted(ee, local):
    right = response_column(ee)
    uncast_design = ee.Image.constant(ee.Array([[1, 0], [1, 1], [1, 2]]))
    with pytest.raises(UnsupportedEEError, match="explicit top-level toFloat"):
        compile_value(ee, uncast_design.matrixSolve(right), local)

    no_cast_response = (first_image(ee).select(["y0", "y1", "y2"])
                        .toArray().toArray(axis=1))
    with pytest.raises(UnsupportedEEError, match="explicit top-level toFloat"):
        compile_value(ee, design_image(ee).matrixSolve(no_cast_response), local)

    for bad_left, bad_right in (
        (ee.Image.constant(1), ee.Image.constant(1)),
        (ee.Image.constant(ee.Array([[1]])), ee.Image.constant(ee.Array([[1]]))),
    ):
        with pytest.raises(UnsupportedEEError):
            compile_value(ee, bad_left.matrixSolve(bad_right), local)

    raw_list = {"type": "Invocation", "functionName": "Image.matrixSolve",
                "arguments": {"image1": [[1]], "image2": [[1]]}}
    with pytest.raises(UnsupportedEEError):
        compile_raw(raw_list, local)


def test_double_design_promotes_rhs_but_dynamic_design_still_rejects(ee, local):
    output = ee.Image.constant(ee.Array([[1, 0], [1, 1], [1, 2]])).toDouble().matrixSolve(
        response_column(ee),
    ).arrayFlatten([["intercept", "slope"], ["rhs"]])
    result = compile_value(ee, output, local)
    assert result["bands"] == ["intercept_rhs", "slope_rhs"]
    assert any(node["process_id"] == "local_ee_integer_values"
               for node in result["process_graph"].values())

    dynamic_design = response_column(ee)
    with pytest.raises(UnsupportedEEError, match="literal constants"):
        compile_value(ee, dynamic_design.matrixSolve(response_column(ee)), local)


@pytest.mark.parametrize("design,response", [
    ([[1, 0, 0], [0, 1, 0]], [[1], [2]]),  # m < n
    ([[1], [1], [1], [1], [1], [1], [1], [1], [1]], [[1]] * 9),  # m > 8
    ([[1, 0, 0, 0, 0]] * 5, [[1]] * 5),  # n > 4
    ([[1, 0], [1, 1], [1, 2]], [[1], [2]]),  # incompatible row counts
    ([1, 2, 3], [[1], [2], [3]]),  # left rank 1
    ([[1], [2], [3]], [1, 2, 3]),  # right rank 1
])
def test_invalid_solver_shapes_are_rejected_at_the_static_boundary(ee, local, design, response):
    left = constant_array_image(ee, design)
    right = constant_array_image(ee, response)
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, left.matrixSolve(right), local)


def test_more_than_four_rhs_columns_are_rejected(ee, local):
    source = (first_image(ee).select(["y0", "y1", "y2"])
              .toFloat().toArray().toArray(axis=1))
    right = source.matrixMultiply(ee.Image.constant(ee.Array([[1, 2, 3, 4, 5]]))).toFloat()
    with pytest.raises(UnsupportedEEError, match="1<=k<=4"):
        compile_value(ee, constant_array_image(ee, [[1], [1], [1]]).matrixSolve(right), local)


def test_rank_deficiency_and_float32_overflow_are_rejected(ee, local):
    rank_deficient = constant_array_image(ee, [[1, 1], [2, 2], [3, 3]])
    with pytest.raises(UnsupportedEEError, match="full column rank"):
        compile_value(ee, rank_deficient.matrixSolve(response_column(ee)), local)

    too_large_for_float32 = constant_array_image(ee, [[1e39]])
    with pytest.raises(UnsupportedEEError, match="Float32"):
        compile_value(ee, too_large_for_float32.matrixSolve(
            constant_array_image(ee, [[1]])), local)


def test_finite_float32_design_can_still_overflow_the_pseudoinverse(ee, local):
    tiny_but_nonzero = constant_array_image(ee, [[1e-39]])
    with pytest.raises(UnsupportedEEError, match="finite Float32 pseudoinverse"):
        compile_value(ee, tiny_but_nonzero.matrixSolve(constant_array_image(ee, [[1]])), local)


def test_direct_and_nested_raster_array_results_are_not_public_json(ee, local):
    fit = valid_expression(ee)
    with pytest.raises(UnsupportedEEError, match="arrayFlatten or arrayGet"):
        compile_value(ee, fit, local)
    with pytest.raises(UnsupportedEEError):
        compile_value(ee, ee.List([fit]), local)


def test_shared_work_preflight_runs_before_numpy_lstsq(monkeypatch):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("NumPy kernel ran before shared-work preflight")

    monkeypatch.setattr(np.linalg, "lstsq", should_not_run)
    to_float = lambda value: Pixel("to_float", (const(value),))
    left = wrap_array_image(Image([], {}), (1, 1), (to_float(1.0),), const(True))
    right = wrap_array_image(Image([], {}), (1, 1), (to_float(2.0),), const(True))
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_raster_matrix(translator, "Image.matrixSolve", {
            "image1": left, "image2": right,
        })
    assert translator.steps == 49_999


def test_shared_cast_suffix_is_bounded_and_keeps_the_expected_solution():
    chain = const(1.0)
    for index in range(48):
        chain = Pixel("to_double" if index % 2 else "to_float", (chain,))
    left = wrap_array_image(
        Image([], {}), (8, 1),
        tuple(Pixel("to_float", (chain,)) for _ in range(8)), const(True),
    )
    right = wrap_array_image(
        Image([], {}), (8, 1),
        tuple(Pixel("to_float", (const(float(value)),)) for value in range(1, 9)),
        const(True),
    )
    translator = Translator([], {}, {})
    translator.steps = 49_400
    result = invoke_raster_matrix(translator, "Image.matrixSolve", {
        "image1": left, "image2": right,
    })

    def scalar(pixel):
        if pixel.op == "constant":
            return pixel.args[0]
        if pixel.op == "to_float":
            return float(np.float32(scalar(pixel.args[0])))
        if pixel.op == "to_double":
            return float(scalar(pixel.args[0]))
        left_value, right_value = map(scalar, pixel.args)
        return left_value * right_value if pixel.op == "multiply" else left_value + right_value

    assert result.shape == (1, 1)
    assert scalar(result.cells[0]) == pytest.approx(4.5, abs=2e-6)
    assert 49_400 < translator.steps <= 50_000


def test_real_balanced_pixel_graph_above_500_nodes_is_rejected(ee, local):
    base = first_image(ee).select(["y0"])
    layer = [base.add(index) for index in range(256)]
    while len(layer) > 1:
        layer = [layer[index].add(layer[index + 1])
                 for index in range(0, len(layer), 2)]
    response = layer[0].toFloat().toArray().toArray(axis=1)
    fit = (constant_array_image(ee, [[1]]).matrixSolve(response)
           .arrayFlatten([["coefficient"], ["response"]]))
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compile_value(ee, fit, local)
