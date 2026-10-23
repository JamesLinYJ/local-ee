"""Direct edge controls for the independent per-pixel matrix graph oracle."""
from fractions import Fraction
import json
import struct

import numpy as np
import pytest

from ee_matrix_graph_reference import matrix_values_handler


def _wire(op, rows, cols, rhs_cols, operands):
    return json.dumps({
        "v": 1, "op": op, "rows": rows, "cols": cols,
        "rhs_cols": rhs_cols, "operands": operands,
    }, sort_keys=True, separators=(",", ":"))


def test_reference_uses_actual_timed_band_axis_and_decodes_hex_constants():
    zero = struct.pack(">d", 0.0).hex()
    seven = struct.pack(">d", 7.0).hex()
    spec = _wire("solve", 2, 2, 1, [
        {"band": 0}, {"constant": zero}, {"band": 1}, {"band": 2},
        {"band": 3}, {"constant": seven},
    ])
    cube = np.array([
        [[2.0], [0.0], [3.0], [5.0]],
        [[4.0], [1.0], [2.0], [9.0]],
    ])
    actual, names, timed = matrix_values_handler(
        {"data": {"from_node": "source"}, "spec": spec},
        {"source": (cube, ["m00", "m10", "m11", "b0"], True)},
    )
    assert timed is True
    assert names == ["matrix0", "matrix1"]
    assert actual.shape == (2, 2, 1)
    np.testing.assert_allclose(actual[:, :, 0], [[2.5, 7 / 3], [2.25, 19 / 8]])


def test_reference_rejects_input_infinity_and_masks_nan_or_overflow_as_whole_matrices():
    inverse_spec = _wire("inverse", 2, 2, 0, [{"band": index} for index in range(4)])
    args = {"data": {"from_node": "source"}, "spec": inverse_spec}
    cube = np.array([
        [2.0, 1.0, 1e-320],
        [1.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [2.0, np.nan, 1e-320],
    ])
    actual, _names, timed = matrix_values_handler(
        args, {"source": (cube, ["a", "b", "c", "d"], False)},
    )
    assert timed is False
    assert actual.shape == (4, 3)
    assert np.isfinite(actual[:, 0]).all()
    assert np.isnan(actual[:, 1]).all()
    assert np.isnan(actual[:, 2]).all()

    cube[0, 0] = np.inf
    with pytest.raises(ValueError, match="valid infinity"):
        matrix_values_handler(
            args, {"source": (cube, ["a", "b", "c", "d"], False)},
        )


def test_reference_solve_keeps_subnormal_rhs_beside_large_rhs_components():
    tiny = float(np.nextafter(0.0, 1.0))
    identity_scale = 1e-16
    first_spec = _wire("solve", 2, 2, 1, [{"band": index} for index in range(6)])
    first_cube = np.array([
        [identity_scale], [0.0], [0.0], [identity_scale], [tiny], [1e292],
    ])
    first, _names, _timed = matrix_values_handler(
        {"data": {"from_node": "source"}, "spec": first_spec},
        {"source": (first_cube, [f"b{index}" for index in range(6)], False)},
    )
    expected_first = float(
        Fraction.from_float(tiny) / Fraction.from_float(identity_scale)
    )
    assert first[0, 0] == expected_first
    assert first[1, 0] == 1e308

    second_spec = _wire("solve", 2, 1, 1, [{"band": index} for index in range(4)])
    second_cube = np.array([[1e-308], [0.0], [tiny], [1e308]])
    second, _names, _timed = matrix_values_handler(
        {"data": {"from_node": "source"}, "spec": second_spec},
        {"source": (second_cube, [f"b{index}" for index in range(4)], False)},
    )
    expected_second = float(
        Fraction.from_float(tiny) / Fraction.from_float(1e-308)
    )
    assert second[0, 0] == expected_second


def test_reference_constant_column_centers_large_rhs_against_fraction_ols():
    baseline = 1e292
    step = float(np.spacing(baseline))
    right = [baseline + index * step for index in range(4)]
    spec = _wire("solve", 4, 2, 1, [{"band": index} for index in range(12)])
    matrix_row_major = [1.0, 0.0, 1.0, 1.0, 1.0, 2.0, 1.0, 3.0]
    cube = np.asarray(matrix_row_major + right, dtype=np.float64)[:, None]
    actual, _names, _timed = matrix_values_handler(
        {"data": {"from_node": "source"}, "spec": spec},
        {"source": (cube, [f"b{index}" for index in range(12)], False)},
    )

    exact_right = [Fraction.from_float(value) for value in right]
    mean_x = Fraction(3, 2)
    mean_y = sum(exact_right, Fraction()) / 4
    slope = sum(
        (Fraction(index) - mean_x) * (value - mean_y)
        for index, value in enumerate(exact_right)
    ) / sum((Fraction(index) - mean_x) ** 2 for index in range(4))
    intercept = mean_y - slope * mean_x
    assert actual[1, 0] == pytest.approx(float(slope), rel=2e-15, abs=0)
    assert actual[0, 0] == float(intercept)
