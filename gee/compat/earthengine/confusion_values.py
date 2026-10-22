"""Bounded static confusion matrices over typed EE Array values."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math

import numpy as np

from .array_core import StaticArray, charge_array, require_array, wrap_array
from .ir import fail


MAX_CONFUSION_CLASSES = 64
MAX_CONFUSION_CELLS = MAX_CONFUSION_CLASSES ** 2
MAX_EXACT_COUNT = 2 ** 53

CONFUSION_FUNCTIONS = frozenset({
    "ConfusionMatrix",
    "ConfusionMatrix.array",
    "ConfusionMatrix.order",
    "ConfusionMatrix.accuracy",
    "ConfusionMatrix.kappa",
})


@dataclass(frozen=True)
class StaticConfusionMatrix:
    """A finite matrix and its row/column class labels."""

    matrix: StaticArray
    order: tuple[int, ...]


def _label(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ConfusionMatrix order labels must be finite integers")
    if isinstance(value, float) and not math.isfinite(value):
        fail("ConfusionMatrix order labels must be finite integers")
    if int(value) != value:
        fail("ConfusionMatrix order labels must be finite integers")
    result = int(value)
    if abs(result) > MAX_EXACT_COUNT:
        fail("ConfusionMatrix order labels exceed the exact Float64 domain")
    return result


def make_confusion(t, matrix, order=None):
    """Validate and freeze a typed static matrix with its optional class order."""
    if isinstance(matrix, StaticConfusionMatrix):
        if order is not None:
            fail("ConfusionMatrix cannot override the order of an existing matrix")
        return matrix
    data = require_array(matrix)
    if data.ndim != 2 or data.shape[0] != data.shape[1]:
        fail("ConfusionMatrix requires a square rank-2 static Array")
    classes = int(data.shape[0])
    if classes > MAX_CONFUSION_CLASSES:
        fail(f"ConfusionMatrix supports at most {MAX_CONFUSION_CLASSES} classes")
    cells = classes * classes
    if cells > MAX_CONFUSION_CELLS:
        fail(f"ConfusionMatrix exceeds {MAX_CONFUSION_CELLS} cells")
    if data.dtype.kind not in {"i", "u"}:
        fail("ConfusionMatrix requires an integer-typed static Array")
    if order is not None:
        if not isinstance(order, list):
            fail("ConfusionMatrix order must be a list of integer labels")
        if len(order) != classes:
            fail("ConfusionMatrix order length must match the matrix dimensions")
    # Charge before copying the matrix or constructing its tuple of labels.
    charge_array(t, cells + (classes if order is not None else 0))

    total = 0
    for value in data.flat:
        count = int(value)
        if count < 0:
            fail("ConfusionMatrix counts must be nonnegative")
        total += count
        if total > MAX_EXACT_COUNT:
            fail("ConfusionMatrix total exceeds the exact Float64 domain")

    labels = tuple(range(classes)) if order is None else tuple(_label(value) for value in order)
    if len(set(labels)) != len(labels):
        fail("ConfusionMatrix order labels must be unique")

    # wrap_array makes a detached, read-only copy after all shape and work
    # limits have been checked. The source StaticArray remains independent.
    frozen = wrap_array(data)
    return StaticConfusionMatrix(frozen, labels)


def _matrix(t, value):
    if not isinstance(value, StaticConfusionMatrix):
        fail("ConfusionMatrix method requires a static ConfusionMatrix")
    data = require_array(value.matrix)
    charge_array(t, int(data.size))
    return data


def _totals(data):
    rows = [0] * int(data.shape[0])
    columns = [0] * int(data.shape[1])
    trace = 0
    total = 0
    for row in range(data.shape[0]):
        for column in range(data.shape[1]):
            count = int(data[row, column])
            rows[row] += count
            columns[column] += count
            total += count
            if row == column:
                trace += count
    return total, trace, rows, columns


def _float64_ratio(numerator, denominator, label):
    if denominator == 0:
        fail(f"ConfusionMatrix.{label} is undefined for this matrix")
    result = float(Fraction(numerator, denominator))
    if not math.isfinite(result):
        fail(f"ConfusionMatrix.{label} exceeds the finite Float64 domain")
    return result


def invoke_confusion(t, name, args):
    """Evaluate only the constructor and four pinned ConfusionMatrix methods."""
    if name not in CONFUSION_FUNCTIONS:
        fail(f"Unsupported Earth Engine algorithm: {name}")
    if name == "ConfusionMatrix":
        t.allowed(args, {"array", "order"})
        if "array" not in args:
            fail("ConfusionMatrix requires array")
        return make_confusion(t, args["array"], args.get("order"))

    t.allowed(args, {"confusionMatrix"})
    if "confusionMatrix" not in args:
        fail(f"{name} requires confusionMatrix")
    value = args["confusionMatrix"]
    if name == "ConfusionMatrix.array":
        if not isinstance(value, StaticConfusionMatrix):
            fail("ConfusionMatrix.array requires a static ConfusionMatrix")
        return value.matrix
    if name == "ConfusionMatrix.order":
        if not isinstance(value, StaticConfusionMatrix):
            fail("ConfusionMatrix.order requires a static ConfusionMatrix")
        charge_array(t, len(value.order))
        return list(value.order)

    data = _matrix(t, value)
    total, trace, rows, columns = _totals(data)
    if name == "ConfusionMatrix.accuracy":
        return _float64_ratio(trace, total, "accuracy")
    expected = sum(row * column for row, column in zip(rows, columns))
    return _float64_ratio(total * trace - expected, total * total - expected, "kappa")
