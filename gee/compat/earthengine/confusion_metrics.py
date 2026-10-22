"""Finite per-class metrics for bounded static Earth Engine confusion matrices."""
from __future__ import annotations

from fractions import Fraction
import math

import numpy as np

from .array_core import charge_array, wrap_array
from .ir import fail


CONFUSION_METRIC_FUNCTIONS = frozenset({
    "ConfusionMatrix.consumersAccuracy",
    "ConfusionMatrix.producersAccuracy",
    "ConfusionMatrix.fscore",
})
_MAX_EXACT_COUNT = 2 ** 53


def _ratio_vector(translator, data, *, totals, function_name):
    """Return diagonal divided by the documented row or column totals."""
    classes = int(data.shape[0])
    # Charge the result allocation before building the Python list or ndarray.
    charge_array(translator, classes)
    values = []
    for index in range(classes):
        if totals == "row":
            total = sum(int(value) for value in data[index, :])
        else:
            total = sum(int(value) for value in data[:, index])
        if total == 0:
            fail(f"{function_name} is undefined for class {index} with zero {totals} total")
        values.append(float(Fraction(int(data[index, index]), total)))
    return wrap_array(np.asarray(values, dtype=np.float64))


def _beta_fraction(value):
    if type(value) not in (int, float):
        fail("ConfusionMatrix.fscore beta must be a finite positive static number")
    if type(value) is int and abs(value) > _MAX_EXACT_COUNT:
        fail("ConfusionMatrix.fscore beta exceeds the exact Float64 domain")
    try:
        beta = float(value)
    except OverflowError:
        fail("ConfusionMatrix.fscore beta must be a finite positive static number")
    if not math.isfinite(beta) or beta <= 0:
        fail("ConfusionMatrix.fscore beta must be a finite positive static number")
    return Fraction.from_float(beta)


def _fscore_vector(translator, data, beta):
    """Return conventional per-class F-beta using actual rows and predicted columns.

    Earth Engine documents confusion-matrix rows as actual classes and columns
    as predicted classes, while its separate consumer/producer descriptions
    attach those metric names to the opposite statistical labels. Since fscore
    documents only that beta weights recall, this follows the standard axis
    meaning: recall uses actual-row totals and precision uses predicted-column
    totals. This interpretation is explicit and has no Google execution oracle.
    """
    beta_value = _beta_fraction(beta)
    beta_squared = beta_value * beta_value
    one_plus_beta_squared = 1 + beta_squared
    classes = int(data.shape[0])
    # The caller charged one matrix scan. F-beta scans both actual rows and
    # predicted columns, so charge the second full scan plus the result before
    # either traversal or any output allocation.
    charge_array(translator, int(data.size) + classes)
    values = []
    for index in range(classes):
        true_positive = int(data[index, index])
        actual_total = sum(int(value) for value in data[index, :])
        predicted_total = sum(int(data[row, index]) for row in range(classes))
        # Algebraically equivalent to (1 + beta^2) * P * R /
        # (beta^2 * P + R), with P=TP/predicted_total and R=TP/actual_total.
        denominator = beta_squared * actual_total + predicted_total
        if denominator == 0:
            fail(f"ConfusionMatrix.fscore is undefined for class {index} with zero total")
        score = one_plus_beta_squared * true_positive / denominator
        values.append(float(score))
    return wrap_array(np.asarray(values, dtype=np.float64))


def invoke_confusion_metric(translator, name, data, beta=1.0):
    """Evaluate a validated finite confusion-matrix metric as a rank-1 Array.

    The pinned descriptions promise an Array return but do not specify its
    dimensions. This implementation's explicit local output policy is a
    rank-1 vector with one value per class; it is not a verified Google rank
    or dtype equivalence claim.
    """
    if name == "ConfusionMatrix.consumersAccuracy":
        return _ratio_vector(
            translator, data, totals="row",
            function_name="ConfusionMatrix.consumersAccuracy",
        )
    if name == "ConfusionMatrix.producersAccuracy":
        return _ratio_vector(
            translator, data, totals="column",
            function_name="ConfusionMatrix.producersAccuracy",
        )
    if name == "ConfusionMatrix.fscore":
        return _fscore_vector(translator, data, beta)
    fail(f"Unsupported Earth Engine algorithm: {name}")
