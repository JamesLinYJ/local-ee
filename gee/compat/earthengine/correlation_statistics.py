"""Numerical kernels for bounded finite correlation reducers."""
from __future__ import annotations

import math


MAX_BETA_ITERATIONS = 128
_BETA_EPSILON = 3e-14
_BETA_FLOOR = 1e-300


def _scaled_center(values: list[float]) -> list[float]:
    """Center values after exact power-of-two scaling into a safe range."""
    maximum = max(abs(value) for value in values)
    if maximum == 0.0:
        return [0.0] * len(values)
    _, exponent = math.frexp(maximum)
    scaled = [math.ldexp(value, -exponent) for value in values]
    # Shift before taking the mean. Centering the absolute scaled values can
    # round their large common offset and erase small representable deltas.
    anchor = scaled[0]
    offsets = [value - anchor for value in scaled]
    mean_offset = math.fsum(offsets) / len(offsets)
    return [value - mean_offset for value in offsets]


def pearson_correlation(x: list[float], y: list[float]) -> float | None:
    """Return centered Pearson r, or None for insufficient/constant data."""
    if len(x) < 2 or min(x) == max(x) or min(y) == max(y):
        return None
    if len(x) == 2:
        # Any two nonconstant observations lie exactly on a line. Comparing
        # order avoids overflow in a direct difference of extreme values.
        return 1.0 if (x[1] > x[0]) == (y[1] > y[0]) else -1.0
    centered_x = _scaled_center(x)
    centered_y = _scaled_center(y)
    sum_xx = math.fsum(value * value for value in centered_x)
    sum_yy = math.fsum(value * value for value in centered_y)
    if sum_xx == 0.0 or sum_yy == 0.0:
        return None
    result = math.fsum(a * b for a, b in zip(centered_x, centered_y))
    result /= math.sqrt(sum_xx) * math.sqrt(sum_yy)
    if abs(result) > 1.0:
        if abs(result) <= 1.0 + 64.0 * math.ulp(1.0):
            result = math.copysign(1.0, result)
        else:
            raise ArithmeticError("Pearson correlation escaped its finite range")
    return result


def _beta_fraction(a: float, b: float, x: float) -> float:
    """Evaluate the continued fraction for the regularized beta function."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _BETA_FLOOR:
        d = _BETA_FLOOR
    d = 1.0 / d
    result = d
    for iteration in range(1, MAX_BETA_ITERATIONS + 1):
        twice = 2 * iteration
        coefficient = iteration * (b - iteration) * x / ((qam + twice) * (a + twice))
        d = 1.0 + coefficient * d
        if abs(d) < _BETA_FLOOR:
            d = _BETA_FLOOR
        c = 1.0 + coefficient / c
        if abs(c) < _BETA_FLOOR:
            c = _BETA_FLOOR
        d = 1.0 / d
        result *= d * c

        coefficient = (-(a + iteration) * (qab + iteration) * x
                       / ((a + twice) * (qap + twice)))
        d = 1.0 + coefficient * d
        if abs(d) < _BETA_FLOOR:
            d = _BETA_FLOOR
        c = 1.0 + coefficient / c
        if abs(c) < _BETA_FLOOR:
            c = _BETA_FLOOR
        d = 1.0 / d
        adjustment = d * c
        result *= adjustment
        if abs(adjustment - 1.0) <= _BETA_EPSILON:
            return result
    raise ArithmeticError("Pearson p-value continued fraction did not converge")


def regularized_beta(x: float, a: float, b: float) -> float:
    """Return I_x(a,b) using a bounded, symmetric continued fraction."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_factor = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
                  + a * math.log(x) + b * math.log1p(-x))
    factor = math.exp(log_factor) if log_factor > -746.0 else 0.0
    if x < (a + 1.0) / (a + b + 2.0):
        result = factor * _beta_fraction(a, b, x) / a
    else:
        result = 1.0 - factor * _beta_fraction(b, a, 1.0 - x) / b
    return min(1.0, max(0.0, result))


def pearson_two_sided_p_value(correlation: float, count: int) -> float:
    """Student-t two-sided p-value for the null hypothesis rho = 0."""
    if count < 3:
        raise ValueError("Pearson p-value requires at least three pairs")
    magnitude = abs(correlation)
    if magnitude == 0.0:
        return 1.0
    if magnitude >= 1.0:
        return 0.0
    if count == 3:
        # With one degree of freedom, t is Cauchy and the two-sided tail is
        # 2*acos(|r|)/pi. This also avoids losing tiny r when forming 1-r^2.
        return 2.0 * math.acos(magnitude) / math.pi
    if count == 4:
        # With two degrees of freedom the Student-t two-sided tail simplifies
        # exactly to 1-|r|.
        return 1.0 - magnitude
    # The t tail equals I_(1-r^2)((n-2)/2, 1/2). Near |r|=1, compute
    # 1-r^2 as (1-r)(1+r); near zero, use the complementary I_(r^2) tail.
    beta_x = (1.0 - magnitude) * (1.0 + magnitude)
    degrees_half = (count - 2.0) / 2.0
    threshold = (degrees_half + 1.0) / (degrees_half + 2.5)
    if beta_x >= threshold:
        # Use r^2 directly for the complementary beta tail. Computing 1-x
        # from beta_x loses precision when r is small and can even round it
        # to zero, despite the accurately representable r^2.
        complement = regularized_beta(
            magnitude * magnitude, 0.5, degrees_half,
        )
        return 1.0 - complement
    return regularized_beta(beta_x, degrees_half, 0.5)


def average_ranks(values: list[float]) -> list[float]:
    """Assign 1-based average ranks to equal finite values."""
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = rank
        start = end
    return ranks


def spearman_correlation(x: list[float], y: list[float]) -> float | None:
    """Return Pearson correlation of the two average-rank vectors."""
    if len(x) < 2:
        return None
    return pearson_correlation(average_ranks(x), average_ranks(y))


def _tie_pairs(values: list[float]) -> int:
    counts: dict[float, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return sum(count * (count - 1) // 2 for count in counts.values())


def kendall_tau_b(x: list[float], y: list[float]) -> float | None:
    """Count concordant/discordant pairs and return tie-adjusted tau-b."""
    count = len(x)
    if count < 2:
        return None
    concordant = 0
    discordant = 0
    for left in range(count - 1):
        for right in range(left + 1, count):
            dx = (x[right] > x[left]) - (x[right] < x[left])
            dy = (y[right] > y[left]) - (y[right] < y[left])
            if dx and dy:
                if dx == dy:
                    concordant += 1
                else:
                    discordant += 1
    pair_total = count * (count - 1) // 2
    untied_x = pair_total - _tie_pairs(x)
    untied_y = pair_total - _tie_pairs(y)
    denominator = math.sqrt(untied_x) * math.sqrt(untied_y)
    if denominator == 0.0:
        return None
    return (concordant - discordant) / denominator
