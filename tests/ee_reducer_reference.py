"""Independent exact-rational scalar oracle for compiled synthetic raster graphs.

This evaluates arrays supplied by tests, never native tiles or user data.
"""
from decimal import Decimal, localcontext
from fractions import Fraction
import math

import numpy as np


def _scalar(operation, samples):
    samples = [float(value) for value in samples if not math.isnan(value)]
    if not samples:
        return math.nan
    assert all(math.isfinite(value) for value in samples)
    if operation == "count":
        return float(len(samples))
    if operation in {"first", "last", "min", "max"}:
        return {"first": samples[0], "last": samples[-1],
                "min": min(samples), "max": max(samples)}[operation]
    exact = [Fraction.from_float(value) for value in samples]
    if operation == "product":
        result = math.prod(exact)
        if result == 0:
            sign = (-1) ** sum(math.copysign(1, value) < 0 for value in samples)
            return math.copysign(0.0, sign)
        return float(result)
    if operation == "sum":
        return float(sum(exact))
    if operation == "median":
        ordered = sorted(exact)
        middle = len(ordered) // 2
        return float(ordered[middle] if len(ordered) % 2 else
                     (ordered[middle - 1] + ordered[middle]) / 2)
    mean = sum(exact) / len(exact)
    if operation == "mean":
        return float(mean)
    assert operation in {"sd", "stdDev", "variance", "sampleVariance"}
    denominator = len(exact) - (operation in {"sd", "sampleVariance"})
    if denominator == 0:
        return math.nan
    variance = sum((value - mean) ** 2 for value in exact) / denominator
    if operation in {"sd", "stdDev"}:
        with localcontext() as context:
            context.prec = 200
            return float((Decimal(variance.numerator) / Decimal(variance.denominator)).sqrt())
    return float(variance)


def reduce_bands(arguments, values):
    data, _, timed = values[arguments["data"]["from_node"]]
    axis = 1 if timed else 0
    arranged = np.moveaxis(data, axis, 0)
    output = np.empty(arranged.shape[1:], dtype=np.float64)
    for position in np.ndindex(output.shape):
        output[position] = _scalar(arguments["reducer"], arranged[(slice(None), *position)])
    return np.expand_dims(output, axis), ["v"], timed


def drop_single_time(arguments, values):
    data, names, timed = values[arguments["data"]["from_node"]]
    assert timed and data.shape[0] == 1
    return data[0].copy(), names, False
