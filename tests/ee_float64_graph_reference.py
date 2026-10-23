"""Independent NumPy oracle for the Float64 image SPI in graph tests."""
from __future__ import annotations

import json
import math
import struct

import numpy as np


_BINARY = {
    "add": np.add,
    "subtract": np.subtract,
    "multiply": np.multiply,
    "power": np.power,
    "mod": np.fmod,
    "min2": np.minimum,
    "max2": np.maximum,
    "and": np.logical_and,
    "or": np.logical_or,
    "eq": np.equal,
    "neq": np.not_equal,
    "lt": np.less,
    "lte": np.less_equal,
    "gt": np.greater,
    "gte": np.greater_equal,
}


def _constant(encoded: str) -> float:
    if type(encoded) is not str or len(encoded) != 16:
        raise AssertionError("Float64 oracle received a malformed binary64 constant")
    try:
        value = struct.unpack(">d", bytes.fromhex(encoded))[0]
    except (ValueError, struct.error) as error:
        raise AssertionError("Float64 oracle received a malformed binary64 constant") from error
    if not math.isfinite(value):
        raise AssertionError("Float64 oracle constants must be finite")
    return value


def _operand(descriptor: dict, data: np.ndarray, band_axis: int,
             valid: np.ndarray) -> np.ndarray | float:
    if type(descriptor) is not dict:
        raise AssertionError("Float64 oracle received a malformed operand")
    if set(descriptor) == {"constant"}:
        return _constant(descriptor["constant"])
    if set(descriptor) != {"band"}:
        raise AssertionError("Float64 oracle operand must name a band or constant")
    band = descriptor["band"]
    if type(band) is not int or not 0 <= band < data.shape[band_axis]:
        raise AssertionError("Float64 oracle received an invalid input band")
    values = np.take(data, band, axis=band_axis)
    valid &= np.isfinite(values)
    return values


def _apply(operation: str, operands: list[np.ndarray | float]) -> np.ndarray:
    if operation == "divide":
        if len(operands) != 2:
            raise AssertionError("Float64 divide requires two operands")
        left, right = operands
        left, right = np.broadcast_arrays(left, right)
        result = np.zeros(left.shape, dtype=np.float64)
        np.divide(left, right, out=result, where=right != 0)
        return result
    if operation in _BINARY:
        if len(operands) != 2:
            raise AssertionError(f"Float64 {operation} requires two operands")
        return np.asarray(_BINARY[operation](*operands), dtype=np.float64)
    if len(operands) != 1:
        raise AssertionError(f"Float64 {operation} requires one operand")
    value = np.asarray(operands[0], dtype=np.float64)
    unary = {
        "absolute": np.absolute,
        "sqrt": np.sqrt,
        "log": np.log,
        "log10": np.log10,
        "exp": np.exp,
        "round": lambda x: np.floor(x + 0.5),
        "floor": np.floor,
        "ceil": np.ceil,
        "sin": np.sin,
        "cos": np.cos,
        "tan": np.tan,
        "not": np.logical_not,
    }
    try:
        function = unary[operation]
    except KeyError as error:
        raise AssertionError(f"Float64 oracle has no operation {operation!r}") from error
    return np.asarray(function(value), dtype=np.float64)


def float64_values_handler(arguments: dict, values: dict) -> tuple[np.ndarray, list[str], bool]:
    """Interpret one SPI node from already evaluated graph cubes.

    This is a test oracle only. It decodes the wire independently and applies
    mask intersection, finite-result NoData, and the local divide-by-zero rule.
    """
    if type(arguments) is not dict or set(arguments) != {"data", "spec"}:
        raise AssertionError("Float64 oracle received unexpected SPI arguments")
    data_ref = arguments["data"]
    if type(data_ref) is not dict or set(data_ref) != {"from_node"}:
        raise AssertionError("Float64 oracle requires a graph cube input")
    try:
        data, _names, timed = values[data_ref["from_node"]]
        spec = json.loads(arguments["spec"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise AssertionError("Float64 oracle could not read its graph input or spec") from error
    if (type(spec) is not dict or set(spec) != {"dtype", "op", "operands", "v"}
            or spec["v"] != 1 or type(spec["operands"]) is not list):
        raise AssertionError("Float64 oracle received an unsupported wire object")

    data = np.asarray(data, dtype=np.float64)
    band_axis = 1 if timed else 0
    if data.ndim not in (2, 3) or band_axis >= data.ndim:
        raise AssertionError("Float64 oracle input must be a scalar raster cube")
    valid = np.ones(np.take(data, 0, axis=band_axis).shape, dtype=bool)
    operands = [
        _operand(descriptor, data, band_axis, valid)
        for descriptor in spec["operands"]
    ]
    with np.errstate(all="ignore"):
        result = _apply(spec["op"], operands)
    result = np.asarray(result, dtype=np.float64)
    if result.shape != valid.shape:
        result = np.broadcast_to(result, valid.shape)
    result = np.where(valid & np.isfinite(result), result, np.nan)
    return np.expand_dims(result, axis=band_axis), ["v"], bool(timed)


def evaluate_float64_graph(result: dict, arrays: dict, *, grid=None,
                           source_geometries=None):
    """Evaluate through the existing sample-vector interpreter plus this oracle."""
    from test_ee_translate import evaluate_graph

    return evaluate_graph(
        result, arrays, grid=grid, source_geometries=source_geometries,
        process_handlers={"local_ee_integer_values": float64_values_handler},
    )
