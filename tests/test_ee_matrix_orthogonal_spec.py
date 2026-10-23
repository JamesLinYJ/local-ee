"""Compact orthogonal-factor wire shapes are bounded independently of inputs."""
import json

import pytest

from gee.matrix_values_spec import (
    decode_matrix_values_spec, matrix_factor_layout, matrix_input_bands,
    matrix_output_cells, matrix_output_layout, matrix_output_shape,
    prepare_matrix_values_spec,
)


def _wire(op, rows, cols):
    return prepare_matrix_values_spec(
        op, rows, cols, 0, [{"band": i} for i in range(rows * cols)],
    )


@pytest.mark.parametrize("op,rows,cols,expected", [
    ("qr", 3, 2, (("Q", (3, 2)), ("R", (2, 2)))),
    ("qr", 2, 3, (("Q", (2, 2)), ("R", (2, 3)))),
    ("qr", 7, 5, (("Q", (7, 5)), ("R", (5, 5)))),
    ("svd", 8, 3, (("U", (8, 3)), ("S", (3, 3)), ("V", (3, 3)))),
    ("svd", 3, 8, (("U", (3, 3)), ("S", (3, 3)), ("V", (8, 3)))),
    ("svd", 4, 4, (("U", (4, 4)), ("S", (4, 4)), ("V", (4, 4)))),
    ("svd", 8, 4, (("U", (8, 4)), ("S", (4, 4)), ("V", (4, 4)))),
    ("svd", 4, 8, (("U", (4, 4)), ("S", (4, 4)), ("V", (8, 4)))),
])
def test_compact_factor_layout_wire_count_and_multiple_shape_guard(op, rows, cols, expected):
    encoded = _wire(op, rows, cols)
    spec = decode_matrix_values_spec(encoded)
    assert set(spec) == {"v", "op", "rows", "cols", "rhs_cols", "operands"}
    assert matrix_output_layout(spec) == matrix_factor_layout(op, rows, cols) == expected
    assert matrix_output_cells(spec) == sum(a * b for _name, (a, b) in expected)
    assert matrix_input_bands(spec) == rows * cols
    assert encoded == json.dumps(spec, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="multiple factor shapes"):
        matrix_output_shape(spec)


def test_all_bounded_axis_pairs_follow_independent_combined_output_formula():
    for op in ("qr", "svd"):
        for rows in range(1, 9):
            for cols in range(1, 9):
                inner = min(rows, cols)
                count = inner * (rows + cols + (inner if op == "svd" else 0))
                if count > 64:
                    with pytest.raises(ValueError, match="64-cell"):
                        _wire(op, rows, cols)
                else:
                    assert matrix_output_cells(decode_matrix_values_spec(_wire(op, rows, cols))) == count


@pytest.mark.parametrize("op,rows,cols", [
    ("qr", 8, 5), ("qr", 5, 8), ("svd", 5, 5), ("svd", 8, 5),
    ("svd", 5, 8), ("qr", 8, 8),
])
def test_valid_input_shape_still_rejects_excessive_combined_factor_output(op, rows, cols):
    assert rows * cols <= 64
    with pytest.raises(ValueError, match="combined factor outputs"):
        _wire(op, rows, cols)


@pytest.mark.parametrize("op,rows,cols", [
    ("qr", True, 1), ("qr", 1, False), ("svd", 0, 2), ("svd", 2, 9),
    ("svd", 2.0, 2), ("qr", 2, None), ("unknown", 2, 2), (None, 2, 2),
])
def test_layout_helper_rejects_invalid_axes_or_operation_without_wire(op, rows, cols):
    with pytest.raises(ValueError):
        matrix_factor_layout(op, rows, cols)


@pytest.mark.parametrize("op", ["qr", "svd"])
def test_orthogonal_specs_keep_exact_rhs_and_contiguous_band_contract(op):
    valid = json.loads(_wire(op, 2, 3))
    invalid = [dict(valid, rhs_cols=True), dict(valid, rhs_cols=1),
               dict(valid, operands=[{"band": 1}] * 6),
               dict(valid, operands=[{"band": 0}] * 5), dict(valid, compact=True)]
    for value in invalid:
        with pytest.raises(ValueError):
            decode_matrix_values_spec(json.dumps(value, sort_keys=True, separators=(",", ":")))
    with pytest.raises(ValueError, match="canonical"):
        decode_matrix_values_spec(json.dumps(valid, indent=2))


def test_legacy_factor_layouts_and_old_pseudoinverse_wire_remain_identical():
    assert matrix_factor_layout("cholesky", 8, 8) == (("L", (8, 8)),)
    assert matrix_factor_layout("lu", 4, 4) == tuple((name, (4, 4)) for name in ("L", "U", "P"))
    with pytest.raises(ValueError, match="square"):
        matrix_factor_layout("cholesky", 2, 3)
    assert _wire("pinverse", 1, 2) == (
        '{"cols":2,"op":"pinverse","operands":[{"band":0},{"band":1}],'
        '"rhs_cols":0,"rows":1,"v":1}'
    )
