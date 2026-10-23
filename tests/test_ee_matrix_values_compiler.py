"""Official-SDK compilation and bounded IR checks for matrix-values routing."""
from __future__ import annotations

import json

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Image, Pixel, Source, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.compat.earthengine.matrix_values_graph import compile_matrix_element
from gee.compat.earthengine.raster_matrix_solve import invoke_raster_matrix
from gee.ee_translate import UnsupportedEEError
from gee.matrix_values_spec import prepare_matrix_values_spec
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_matrix_solve import compile_value, ee, first_image, local


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


def _native_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_matrix_values"]


def _dynamic_operand(source=None, band="y0", cast="to_float"):
    source = source or Source("sentinel-2-l2a", ("a",), (band,))
    return Pixel(cast, (Pixel("band", (source, band)),))


def _component(spec, operands, index=0):
    producer = Pixel("matrix_values", (tuple(operands), spec))
    return Pixel("matrix_element", (producer, index))


def test_official_sdk_dynamic_inverse_and_pseudoinverse_share_one_native_producer(ee, local):
    first = first_image(ee)
    first_column = first.select(["y0", "y1"]).toFloat().toArray().toArray(axis=1)
    second_column = first.select(["y1", "y2"]).toFloat().toArray().toArray(axis=1)
    square = first_column.arrayCat(second_column, 1).toFloat()
    inverse = square.matrixInverse().arrayFlatten(
        [["r0", "r1"], ["c0", "c1"]],
    )
    inverse_result = compile_value(ee, inverse, local)
    inverse_nodes = _native_nodes(inverse_result)
    assert len(inverse_nodes) == 1
    inverse_spec = json.loads(inverse_nodes[0]["arguments"]["spec"])
    assert (inverse_spec["op"], inverse_spec["rows"], inverse_spec["cols"]) == (
        "inverse", 2, 2,
    )
    assert inverse_spec["rhs_cols"] == 0
    assert len(inverse_spec["operands"]) == 4
    assert {operand["band"] for operand in inverse_spec["operands"]} == set(range(4))

    vector = first.select(["y0", "y1", "y2"]).toFloat().toArray().toArray(axis=1)
    pseudo = vector.matrixPseudoInverse().arrayFlatten(
        [["coefficient"], ["row0", "row1", "row2"]],
    )
    pseudo_result = compile_value(ee, pseudo, local)
    pseudo_nodes = _native_nodes(pseudo_result)
    assert len(pseudo_nodes) == 1
    pseudo_spec = json.loads(pseudo_nodes[0]["arguments"]["spec"])
    assert (pseudo_spec["op"], pseudo_spec["rows"], pseudo_spec["cols"]) == (
        "pinverse", 3, 1,
    )
    assert pseudo_spec["rhs_cols"] == 0
    assert len(pseudo_spec["operands"]) == 3
    assert len(pseudo_result["bands"]) == 3


def test_official_sdk_inverse_rejects_rank_and_cast_boundary_violations(ee, local):
    first = first_image(ee)
    vector = first.select(["y0", "y1"]).toFloat().toArray().toArray(axis=1)
    with pytest.raises(UnsupportedEEError, match="square matrix"):
        compile_value(ee, vector.matrixInverse(), local)

    scalar = first.select(["y0"]).toFloat().toArray()
    with pytest.raises(UnsupportedEEError, match="rank-2 RasterArrayImage"):
        compile_value(ee, scalar.matrixInverse(), local)

    uncast = first.select(["y0", "y1"]).toArray().toArray(axis=1)
    square = uncast.arrayCat(
        first.select(["y1", "y2"]).toArray().toArray(axis=1), 1,
    )
    with pytest.raises(UnsupportedEEError, match="explicit top-level toFloat"):
        compile_value(ee, square.matrixInverse(), local)


def _constant_matrix(matrix, cast="to_double", mask=None):
    rows, cols = matrix.shape
    cells = tuple(Pixel(cast, (const(float(value)),)) for value in matrix.flat)
    return wrap_array_image(
        Image([], {"constant_matrix": True}), (rows, cols), cells,
        const(True) if mask is None else mask, "matrix",
    )


def _fold(op, matrix, cast="to_double"):
    translator = Translator([], {}, {})
    value = _constant_matrix(np.asarray(matrix), cast)
    result = invoke_raster_matrix(translator, f"Image.matrix{'PseudoInverse' if op == 'pinverse' else 'Inverse'}", {
        "value": value,
    })
    actual = np.array([
        cell.args[0].args[0] if cell.op == cast else cell.args[0]
        for cell in result.cells
    ], dtype=float).reshape(result.shape)
    return result, actual


def test_source_free_constant_folding_uses_native_rank_cutoff_and_zero_policy():
    epsilon = np.finfo(np.float64).eps
    below_cutoff = np.diag([1.0, epsilon])
    above_cutoff = np.diag([1.0, 8.0 * epsilon])

    with pytest.raises(UnsupportedEEError, match="singular at the native rank cutoff"):
        _fold("inverse", below_cutoff)
    below_result, below_pseudo = _fold("pinverse", below_cutoff)
    assert below_result.shape == (2, 2)
    np.testing.assert_array_equal(below_pseudo, np.diag([1.0, 0.0]))

    _, above_inverse = _fold("inverse", above_cutoff)
    _, above_pseudo = _fold("pinverse", above_cutoff)
    np.testing.assert_allclose(above_inverse, np.diag([1.0, 1.0 / above_cutoff[1, 1]]))
    np.testing.assert_allclose(above_pseudo, above_inverse)

    with pytest.raises(UnsupportedEEError, match="zero constant matrix is singular"):
        _fold("inverse", np.zeros((2, 2)))
    _, zero_pseudo = _fold("pinverse", np.zeros((2, 3)))
    np.testing.assert_array_equal(zero_pseudo, np.zeros((3, 2)))


def test_internal_matrix_component_rejects_bad_spec_index_casts_and_mutable_trees():
    source = Source("sentinel-2-l2a", ("a",), ("y0",))
    operand = _dynamic_operand(source)
    spec = prepare_matrix_values_spec(
        "pinverse", 1, 1, 0, [{"band": 0}],
    )

    with pytest.raises(UnsupportedEEError, match="invalid specification"):
        compile_matrix_element(Graph(Translator([], {}, {})), _component("{}", (operand,)))
    with pytest.raises(UnsupportedEEError, match="outside the output shape"):
        compile_matrix_element(Graph(Translator([], {}, {})), _component(spec, (operand,), 1))

    mixed = (_dynamic_operand(source, "y0", "to_float"),
             _dynamic_operand(source, "y1", "to_double"),
             _dynamic_operand(source, "y2", "to_float"))
    mixed_spec = prepare_matrix_values_spec(
        "solve", 1, 2, 1,
        [{"band": 0}, {"band": 1}, {"band": 2}],
    )
    with pytest.raises(UnsupportedEEError, match="uniform top-level casts"):
        compile_matrix_element(
            Graph(Translator([], {}, {})), _component(mixed_spec, mixed),
        )

    mutable_operand = Pixel("to_float", ([Pixel("band", (source, "y0"))],))
    with pytest.raises(UnsupportedEEError, match="immutable acyclic Pixel operands"):
        compile_matrix_element(
            Graph(Translator([], {}, {})), _component(spec, (mutable_operand,)),
        )

    cyclic = Pixel("add", (const(1.0), const(2.0)))
    object.__setattr__(cyclic, "args", (cyclic,))
    cyclic_operand = Pixel("to_float", (cyclic,))
    with pytest.raises(UnsupportedEEError, match="cyclic Pixel operands"):
        compile_matrix_element(
            Graph(Translator([], {}, {})), _component(spec, (cyclic_operand,)),
        )


def test_component_spec_revalidation_consumes_shared_work_budget():
    source = Source("sentinel-2-l2a", ("a",), ("y0",))
    operand = _dynamic_operand(source)
    spec = prepare_matrix_values_spec(
        "pinverse", 1, 1, 0, [{"band": 0}],
    )
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        compile_matrix_element(
            Graph(translator), _component(spec, (operand,)),
        )
    assert translator.steps == 49_999


def test_internal_matrix_scan_has_an_explicit_depth_limit():
    source = Source("sentinel-2-l2a", ("a",), ("y0",))
    nested = Pixel("to_float", (Pixel("band", (source, "y0")),))
    for _ in range(100):
        nested = Pixel("add", (nested, const(1.0)))
    operand = Pixel("to_float", (nested,))
    spec = prepare_matrix_values_spec(
        "pinverse", 1, 1, 0, [{"band": 0}],
    )
    with pytest.raises(UnsupportedEEError, match="immutable Pixel depth limit"):
        compile_matrix_element(
            Graph(Translator([], {}, {})), _component(spec, (operand,)),
        )


def test_dynamic_design_selection_does_not_swallow_a_literal_cycle():
    cyclic_cast = Pixel("to_float", (const(1.0),))
    object.__setattr__(cyclic_cast, "args", (cyclic_cast,))
    left = wrap_array_image(
        Image([], {}), (1, 1), (Pixel("to_float", (cyclic_cast,)),), const(True),
    )
    right = wrap_array_image(
        Image([], {}), (1, 1), (_dynamic_operand(),), const(True),
    )
    with pytest.raises(UnsupportedEEError, match="cyclic Pixel expressions"):
        invoke_raster_matrix(
            Translator([], {}, {}), "Image.matrixSolve",
            {"image1": left, "image2": right},
        )


def test_constant_fold_rejects_non_explicitly_valid_mask():
    translator = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError, match="masked source-free constant"):
        invoke_raster_matrix(
            translator, "Image.matrixPseudoInverse",
            {"value": _constant_matrix(np.eye(2), mask=const(False))},
        )
