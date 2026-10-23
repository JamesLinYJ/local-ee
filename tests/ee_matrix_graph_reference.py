"""Independent NumPy oracle for the bounded per-pixel matrix graph SPI."""
from __future__ import annotations

import json
import math
import re
import struct
from fractions import Fraction

import numpy as np


_MAX_BYTES = 8192
_MAX_AXIS = 8
_MAX_CELLS = 64


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _decode_spec(text):
    if type(text) is not str or len(text) > _MAX_BYTES or not text.isascii():
        raise AssertionError("Matrix graph oracle requires an ASCII v1 spec")
    try:
        spec = json.loads(text, object_pairs_hook=_unique_object)
    except (TypeError, ValueError, json.JSONDecodeError, RecursionError) as error:
        raise AssertionError("Matrix graph oracle received invalid JSON") from error
    if (type(spec) is not dict
            or set(spec) != {"v", "op", "rows", "cols", "rhs_cols", "operands"}
            or type(spec["v"]) is not int or spec["v"] != 1
            or type(spec["op"]) is not str
            or spec["op"] not in {"solve", "inverse", "pinverse"}
            or type(spec["rows"]) is not int
            or type(spec["cols"]) is not int
            or type(spec["rhs_cols"]) is not int):
        raise AssertionError("Matrix graph oracle received an unsupported spec")
    rows, cols, rhs_cols = spec["rows"], spec["cols"], spec["rhs_cols"]
    if not (1 <= rows <= _MAX_AXIS and 1 <= cols <= _MAX_AXIS):
        raise AssertionError("Matrix graph oracle axes must be in1..8")
    op = spec["op"]
    if op == "solve":
        if not 1 <= rhs_cols <= _MAX_AXIS:
            raise AssertionError("Matrix graph oracle solve needs1..8 RHS columns")
        input_cells = rows * cols + rows * rhs_cols
        output_cells = cols * rhs_cols
    else:
        if rhs_cols != 0 or op == "inverse" and rows != cols:
            raise AssertionError("Matrix graph oracle received invalid matrix dimensions")
        input_cells = rows * cols
        output_cells = cols * rows
    if input_cells > _MAX_CELLS or output_cells > _MAX_CELLS:
        raise AssertionError("Matrix graph oracle exceeds the64-cell limit")
    operands = spec["operands"]
    if type(operands) is not list or len(operands) != input_cells:
        raise AssertionError("Matrix graph oracle operand count disagrees with dimensions")
    bands = set()
    for operand in operands:
        if type(operand) is not dict:
            raise AssertionError("Matrix graph oracle operand must be an object")
        if set(operand) == {"band"}:
            band = operand["band"]
            if type(band) is not int or not 0 <= band < _MAX_CELLS:
                raise AssertionError("Matrix graph oracle received an invalid input band")
            bands.add(band)
        elif set(operand) == {"constant"}:
            encoded = operand["constant"]
            if type(encoded) is not str or re.fullmatch(r"[0-9a-f]{16}", encoded) is None:
                raise AssertionError("Matrix graph oracle constant must be16 lowercase hex digits")
            value = struct.unpack(">d", bytes.fromhex(encoded))[0]
            if not math.isfinite(value):
                raise AssertionError("Matrix graph oracle constant must be finite")
        else:
            raise AssertionError("Matrix graph oracle operand must name one band or constant")
    if not bands or bands != set(range(len(bands))):
        raise AssertionError("Matrix graph oracle input bands must be contiguous from0")
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if canonical != text:
        raise AssertionError("Matrix graph oracle requires canonical compact JSON")
    return spec


def _scaled_svd_pseudoinverse(matrix):
    """Return the normalized pseudoinverse and original matrix scale."""
    matrix = np.asarray(matrix, dtype=np.float64)
    scale = float(np.max(np.abs(matrix)))
    if scale == 0.0:
        return (
            np.zeros((matrix.shape[1], matrix.shape[0]), dtype=np.float64),
            scale, matrix.shape[1] == 0,
        )
    normalized = matrix / scale
    left, singular, right = np.linalg.svd(normalized, full_matrices=False)
    cutoff = (max(matrix.shape) * singular[0]) * np.finfo(np.float64).eps
    reciprocal = np.zeros_like(singular)
    retained = singular > cutoff
    reciprocal[retained] = 1.0 / singular[retained]
    return (right.T * reciprocal) @ left.T, scale, int(np.count_nonzero(retained)) == matrix.shape[1]


def _rescale_pseudoinverse(normalized, scale):
    if scale == 0.0:
        return np.zeros_like(normalized)
    divisor = Fraction.from_float(scale)
    try:
        result = np.asarray([
            float(Fraction.from_float(float(value)) / divisor)
            for value in normalized.flat
        ], dtype=np.float64).reshape(normalized.shape)
    except (OverflowError, ZeroDivisionError):
        return None
    return result if np.isfinite(result).all() else None


def _exact_scaled_dot(normalized_pseudoinverse, right_hand_side, scale,
                      *, constant_column=None):
    """Keep small RHS components beside large ones using exact binary sums."""
    if scale == 0.0:
        return np.zeros(
            (normalized_pseudoinverse.shape[0], right_hand_side.shape[1]),
            dtype=np.float64,
        )
    divisor = Fraction.from_float(scale)
    result = np.empty(
        (normalized_pseudoinverse.shape[0], right_hand_side.shape[1]),
        dtype=np.float64,
    )
    try:
        for row in range(result.shape[0]):
            for column in range(result.shape[1]):
                baseline = (
                    Fraction.from_float(float(right_hand_side[0, column]))
                    if constant_column is not None else Fraction()
                )
                total = sum((
                    Fraction.from_float(float(normalized_pseudoinverse[row, inner]))
                    * (Fraction.from_float(float(right_hand_side[inner, column])) - baseline)
                    for inner in range(normalized_pseudoinverse.shape[1])
                ), Fraction())
                exact_value = total / divisor
                if constant_column is not None:
                    column_index, column_value = constant_column
                    if row == column_index:
                        exact_value += baseline / Fraction.from_float(column_value)
                result[row, column] = float(exact_value)
    except (OverflowError, ZeroDivisionError):
        return None
    return result if np.isfinite(result).all() else None


def _constant_predictor_column(matrix, full_column_rank):
    if not full_column_rank or matrix.shape[0] < matrix.shape[1]:
        return None
    for column in range(matrix.shape[1]):
        value = float(matrix[0, column])
        if value != 0.0 and np.all(matrix[:, column] == value):
            return column, value
    return None


def _matrix_result(operation, matrix, right_hand_side=None):
    """Evaluate one finite matrix using the declared local SVD policy."""
    rows, cols = matrix.shape
    if operation == "inverse":
        scale = float(np.max(np.abs(matrix)))
        if scale == 0.0:
            return None
        normalized = matrix / scale
        try:
            singular = np.linalg.svd(normalized, compute_uv=False)
            cutoff = (max(rows, cols) * singular[0]) * np.finfo(np.float64).eps
            if singular[-1] <= cutoff:
                return None
            with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
                value = np.linalg.inv(normalized) / scale
        except np.linalg.LinAlgError:
            return None
        return value if np.isfinite(value).all() else None

    try:
        normalized_pseudoinverse, scale, full_column_rank = _scaled_svd_pseudoinverse(matrix)
        if operation == "pinverse":
            value = _rescale_pseudoinverse(normalized_pseudoinverse, scale)
        else:
            value = _exact_scaled_dot(
                normalized_pseudoinverse, right_hand_side, scale,
                constant_column=_constant_predictor_column(matrix, full_column_rank),
            )
    except np.linalg.LinAlgError:
        return None
    if value is None or not np.isfinite(value).all():
        return None
    return value


def matrix_values_handler(arguments: dict, values: dict):
    """Interpret one matrix SPI node from already evaluated graph cubes.

    The input cube contains only the ordered real band operands. Constants are
    decoded from binary64 hex independently. A missing scalar invalidates all
    cells of that pixel's result matrix; an input infinity rejects the call.
    """
    if type(arguments) is not dict or set(arguments) != {"data", "spec"}:
        raise AssertionError("Matrix graph oracle received unexpected SPI arguments")
    data_ref = arguments["data"]
    if type(data_ref) is not dict or set(data_ref) != {"from_node"}:
        raise AssertionError("Matrix graph oracle requires one graph-cube input")
    try:
        data, names, timed = values[data_ref["from_node"]]
    except (KeyError, TypeError, ValueError) as error:
        raise AssertionError("Matrix graph oracle cannot resolve its input cube") from error
    spec = _decode_spec(arguments["spec"])
    if type(timed) is not bool or type(names) not in (list, tuple):
        raise AssertionError("Matrix graph oracle input metadata is malformed")
    data = np.asarray(data, dtype=np.float64)
    expected_ndim = 3 if timed else 2
    band_axis = 1 if timed else 0
    if data.ndim != expected_ndim or band_axis >= data.ndim:
        raise AssertionError("Matrix graph oracle input cube has invalid dimensions")
    if data.shape[band_axis] != len(names) or data.shape[band_axis] == 0:
        raise AssertionError("Matrix graph oracle input band metadata disagrees with its values")
    if np.isinf(data).any():
        raise ValueError("Matrix graph input cannot contain valid infinity")

    band_indexes = {operand["band"] for operand in spec["operands"] if "band" in operand}
    if len(band_indexes) != data.shape[band_axis] or band_indexes != set(range(len(names))):
        raise AssertionError("Matrix graph oracle bands disagree with actual input dimensions")

    samples = data if timed else data[np.newaxis, ...]
    sample_count, _band_count, pixel_count = samples.shape
    operand_values = []
    for operand in spec["operands"]:
        if "band" in operand:
            operand_values.append(samples[:, operand["band"], :])
        else:
            value = struct.unpack(">d", bytes.fromhex(operand["constant"]))[0]
            operand_values.append(np.full((sample_count, pixel_count), value))

    rows, cols, rhs_cols = spec["rows"], spec["cols"], spec["rhs_cols"]
    left_count = rows * cols
    left_values = np.stack(operand_values[:left_count], axis=-1).reshape(
        sample_count, pixel_count, rows, cols,
    )
    rhs_values = None
    if spec["op"] == "solve":
        rhs_values = np.stack(operand_values[left_count:], axis=-1).reshape(
            sample_count, pixel_count, rows, rhs_cols,
        )
    valid = np.all(np.isfinite(np.stack(operand_values, axis=-1)), axis=-1)
    output_rows, output_cols = (
        (cols, rhs_cols) if spec["op"] == "solve" else (cols, rows)
    )
    output = np.full(
        (sample_count, pixel_count, output_rows, output_cols),
        np.nan, dtype=np.float64,
    )
    for sample in range(sample_count):
        for pixel in range(pixel_count):
            if not valid[sample, pixel]:
                continue
            matrix = left_values[sample, pixel]
            right = None if rhs_values is None else rhs_values[sample, pixel]
            result = _matrix_result(spec["op"], matrix, right)
            if result is not None:
                output[sample, pixel] = result

    flattened = output.reshape(sample_count, pixel_count, output_rows * output_cols)
    if timed:
        raster = np.moveaxis(flattened, 2, 1)
    else:
        raster = flattened[0].T
    output_names = [f"matrix{index}" for index in range(output_rows * output_cols)]
    return raster, output_names, timed
