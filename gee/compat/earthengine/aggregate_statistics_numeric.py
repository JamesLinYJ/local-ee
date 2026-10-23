"""Request-specific finite numeric kernels for aggregate statistics."""
from __future__ import annotations

import math

from .ir import fail


def numeric_sum(numbers):
    try:
        result = math.fsum(float(value) for value in numbers)
    except (OverflowError, ValueError):
        fail("Aggregate sum is outside the finite numeric range")
    if not math.isfinite(result):
        fail("Aggregate sum is outside the finite numeric range")
    return result


def _float_values(numbers):
    return [float(value) for value in numbers]


def numeric_mean(numbers):
    """Compute a shifted mean, falling back to scaled inputs on range overflow."""
    if not numbers:
        return None
    values = _float_values(numbers)
    origin = values[0]
    deltas = [value - origin for value in values]
    if all(math.isfinite(value) for value in deltas):
        try:
            mean_delta = math.fsum(value / len(deltas) for value in deltas)
            result = origin + mean_delta
            if math.isfinite(result):
                return result
        except (OverflowError, ValueError):
            pass
    scale = max(abs(value) for value in values)
    if scale == 0:
        return 0.0
    try:
        scaled_mean = math.fsum(value / scale / len(values) for value in values)
    except (OverflowError, ValueError):
        fail("Aggregate mean is outside the finite numeric range")
    result = scale * scaled_mean
    if not math.isfinite(result):
        fail("Aggregate mean is outside the finite numeric range")
    return result


def _scaled_centered(numbers):
    """Return (mean, base scale, normalized scale, deviations) without squaring."""
    values = _float_values(numbers)
    count = len(values)
    origin = values[0]
    deltas = [value - origin for value in values]
    if all(math.isfinite(value) for value in deltas):
        try:
            mean_delta = math.fsum(value / count for value in deltas)
            mean = origin + mean_delta
            centered = [value - mean_delta for value in deltas]
            if (math.isfinite(mean)
                    and all(math.isfinite(value) for value in centered)):
                scale = max((abs(value) for value in centered), default=0.0)
                if scale == 0:
                    return mean, 0.0, 0.0, []
                return mean, scale, 1.0, [value / scale for value in centered]
        except (OverflowError, ValueError):
            pass

    # Opposite-sign extremes can overflow subtraction. Normalize the original
    # values first; the resulting deviations stay within [-2, 2].
    scale = max(abs(value) for value in values)
    if scale == 0:
        return 0.0, 0.0, 0.0, []
    try:
        normalized = [value / scale for value in values]
        mean_normalized = math.fsum(value / count for value in normalized)
        centered = [value - mean_normalized for value in normalized]
    except (OverflowError, ValueError):
        fail("Aggregate variance is outside the finite numeric range")
    normalized_scale = max((abs(value) for value in centered), default=0.0)
    mean = scale * mean_normalized
    if not math.isfinite(mean):
        fail("Aggregate mean is outside the finite numeric range")
    if normalized_scale == 0:
        return mean, 0.0, 0.0, []
    return mean, scale, normalized_scale, [
        value / normalized_scale for value in centered
    ]


def _normalized_ssd(numbers):
    _, base_scale, normalized_scale, normalized = _scaled_centered(numbers)
    if base_scale == 0:
        return base_scale, normalized_scale, 0.0
    try:
        normalized_ssd = math.fsum(value * value for value in normalized)
    except (OverflowError, ValueError):
        fail("Aggregate variance is outside the finite numeric range")
    if not math.isfinite(normalized_ssd):
        fail("Aggregate variance is outside the finite numeric range")
    return base_scale, normalized_scale, normalized_ssd


def _standard_deviation(base_scale, normalized_scale, normalized_ssd, divisor):
    factor = normalized_scale * math.sqrt(normalized_ssd / divisor)
    return base_scale * factor


def numeric_dispersion(numbers, *, sample, standard_deviation):
    """Compute only the requested variance or standard deviation."""
    if not numbers:
        return None
    if sample and len(numbers) < 2:
        return None
    if len(numbers) == 1:
        return 0.0
    base_scale, normalized_scale, normalized_ssd = _normalized_ssd(numbers)
    divisor = len(numbers) - 1 if sample else len(numbers)
    sd = _standard_deviation(base_scale, normalized_scale, normalized_ssd, divisor)
    return sd if standard_deviation else sd * sd


def numeric_variances(numbers):
    """Return both variance/deviation pairs for the full stats request."""
    if not numbers:
        return None, None, None, None
    if len(numbers) == 1:
        return 0.0, None, 0.0, None
    base_scale, normalized_scale, normalized_ssd = _normalized_ssd(numbers)
    total_sd = _standard_deviation(
        base_scale, normalized_scale, normalized_ssd, len(numbers),
    )
    sample_sd = _standard_deviation(
        base_scale, normalized_scale, normalized_ssd, len(numbers) - 1,
    )
    total_var, sample_var = total_sd * total_sd, sample_sd * sample_sd
    return total_var, sample_var, total_sd, sample_sd


def numeric_sum_squares(numbers):
    """Compute aggregate_stats.sum_sq only for the full stats request."""
    squares = []
    try:
        for number in numbers:
            value = float(number)
            square = value * value
            if not math.isfinite(square):
                fail("aggregate_stats sum_sq is outside the finite numeric range")
            squares.append(square)
        result = math.fsum(squares)
    except (OverflowError, ValueError):
        fail("aggregate_stats sum_sq is outside the finite numeric range")
    if not math.isfinite(result):
        fail("aggregate_stats sum_sq is outside the finite numeric range")
    return result
