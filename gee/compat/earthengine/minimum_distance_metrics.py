"""Exact bounded ranking rules for static minimum-distance classifiers."""
from __future__ import annotations

from fractions import Fraction

from .array_core import charge_array
from .ir import fail


SUPPORTED_METRICS = frozenset({"euclidean", "manhattan", "cosine"})


def require_metric(value):
    if type(value) is not str or value not in SUPPORTED_METRICS:
        fail("Classifier.minimumDistance metric must be euclidean, manhattan or cosine")
    return value


def _work(metric, classes, dimensions):
    if metric == "euclidean":
        return classes * dimensions
    if metric == "manhattan":
        return classes * dimensions * 2
    # Dot products, center norms and exact squared cross-products use several
    # rational operations per coordinate and class. Charge their upper bound
    # before creating any metric scores or entering the candidate loop.
    return classes * (dimensions * 8 + 8)


def _compare_cosine(left, right):
    """Compare exact dot/sqrt(center norm squared) scores, larger first."""
    left_dot, left_norm = left
    right_dot, right_norm = right
    left_sign = (left_dot > 0) - (left_dot < 0)
    right_sign = (right_dot > 0) - (right_dot < 0)
    if left_sign != right_sign:
        return (left_sign > right_sign) - (left_sign < right_sign)
    if left_sign == 0:
        return 0

    # Squaring exact rationals avoids sqrt, acos and Float64 overflow or
    # underflow. For negative dots, a smaller absolute cosine is the larger
    # (better) signed score, so reverse the comparison.
    left_cross = left_dot * left_dot * right_norm
    right_cross = right_dot * right_dot * left_norm
    order = (left_cross > right_cross) - (left_cross < right_cross)
    return order if left_sign > 0 else -order


def _cosine_score(query, center):
    dot = sum((value * mean for value, mean in zip(query, center)), Fraction(0))
    center_norm = sum((mean * mean for mean in center), Fraction(0))
    if center_norm == 0:
        fail("Cosine minimum-distance prediction rejects a zero-norm class center")
    return dot, center_norm


def predict_unique(translator, metric, query, labels, centers):
    """Return one unique nearest class using the selected pinned metric."""
    metric = require_metric(metric)
    dimensions = len(query)
    charge_array(translator, _work(metric, len(labels), dimensions))

    if metric == "cosine":
        query_norm = sum((value * value for value in query), Fraction(0))
        if query_norm == 0:
            fail("Cosine minimum-distance prediction rejects a zero-norm query")
        best_score = None
        best_label = None
        tied = False
        for label, center in zip(labels, centers):
            score = _cosine_score(query, center)
            if best_score is None:
                best_score, best_label = score, label
                continue
            order = _compare_cosine(score, best_score)
            if order > 0:
                best_score, best_label, tied = score, label, False
            elif order == 0:
                tied = True
    else:
        best_distance = None
        best_label = None
        tied = False
        for label, center in zip(labels, centers):
            if metric == "manhattan":
                distance = sum(
                    (abs(value - mean) for value, mean in zip(query, center)),
                    Fraction(0),
                )
            else:
                distance = sum(
                    ((value - mean) ** 2 for value, mean in zip(query, center)),
                    Fraction(0),
                )
            if best_distance is None or distance < best_distance:
                best_distance, best_label, tied = distance, label, False
            elif distance == best_distance:
                tied = True

    if tied:
        fail("Minimum-distance prediction is unsupported for equal-distance class centers")
    return best_label
