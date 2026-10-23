"""Stable population central-moment kernels for bounded finite values."""
from __future__ import annotations

import math


def standardized_moment(values: list[float], order: int) -> float | None:
    """Compute population skew or excess kurtosis with center/scale protection.

    Exact power-of-two scaling happens before subtraction so opposite extreme
    finite values cannot overflow. Anchoring after that scaling preserves
    representable increments around large shared offsets. A second scale on
    centered deviations keeps powers bounded and handles subnormal inputs.
    """
    if order not in (3, 4) or not values:
        return None

    maximum = max(abs(value) for value in values)
    if maximum == 0.0:
        return None
    _, exponent = math.frexp(maximum)
    scaled = [math.ldexp(value, -exponent) for value in values]
    anchor = scaled[0]
    offsets = [value - anchor for value in scaled]
    mean_offset = math.fsum(offsets) / len(offsets)
    centered = [value - mean_offset for value in offsets]
    spread = max(abs(value) for value in centered)
    if spread == 0.0:
        return None

    standardized = [value / spread for value in centered]
    count = len(standardized)
    second = math.fsum(value * value for value in standardized) / count
    if second == 0.0:
        return None
    if order == 3:
        third = math.fsum(value * value * value for value in standardized) / count
        result = third / (second * math.sqrt(second))
    else:
        fourth = math.fsum(value * value * value * value for value in standardized) / count
        result = fourth / (second * second) - 3.0
    return 0.0 if result == 0.0 else result
