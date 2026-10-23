"""Bounded circular-statistic leaves for finite, unweighted table values."""
from __future__ import annotations

from dataclasses import dataclass
import math
import sys

from .ir import fail


MAX_CIRCULAR_ROWS = 1_000
MAX_CIRCULAR_OUTPUT_BYTES = 1_000_000
_MAX_WORK = 50_000
_MAX_EXACT_INTEGER = 2**53
_TAU = 2.0 * math.pi
_ZERO_RESULTANT = 32.0 * sys.float_info.epsilon

CIRCULAR_REDUCER_NAMES = frozenset({
    "Reducer.circularMean",
    "Reducer.circularStddev",
    "Reducer.circularVariance",
})
_OUTPUTS = {
    "Reducer.circularMean": ("circularMean",),
    "Reducer.circularStddev": ("circularStdDev",),
    "Reducer.circularVariance": ("circularVariance",),
}


@dataclass(frozen=True)
class CircularReducerLeaf:
    """Closed circular reducer descriptor; only its canonical name is stored."""

    name: str


def _charge(translator, work: int) -> None:
    steps = getattr(translator, "steps", None)
    if (type(work) is not int or work < 0 or work > _MAX_WORK
            or type(steps) is not int or steps < 0 or steps + work > _MAX_WORK):
        fail("Circular reducer exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + work


def _validate_leaf(translator, leaf: CircularReducerLeaf) -> str:
    if type(leaf) is not CircularReducerLeaf or type(leaf.name) is not str:
        fail("Circular reducer leaf has invalid fields")
    if len(leaf.name) > 64 or leaf.name not in CIRCULAR_REDUCER_NAMES:
        fail("Circular reducer leaf has an unsupported name")
    _charge(translator, 1 + len(leaf.name))
    return leaf.name


def make_circular_reducer(translator, name, arguments) -> CircularReducerLeaf:
    """Validate a no-argument circular reducer and detach its name."""
    if type(name) is not str or name not in CIRCULAR_REDUCER_NAMES:
        fail(f"Unsupported circular reducer: {name}")
    if type(arguments) is not dict:
        fail(f"{name} arguments must be a dictionary")
    translator.allowed(arguments, set())
    _charge(translator, 1 + len(name))
    return CircularReducerLeaf(name)


def describe_circular_reducer(
    translator, leaf: CircularReducerLeaf,
) -> tuple[int, tuple[str, ...]]:
    """Return the single input and canonical Earth Engine output label."""
    name = _validate_leaf(translator, leaf)
    return 1, _OUTPUTS[name]


def _number(value) -> float | None:
    if value is None:
        return None
    if type(value) is int:
        if value < -_MAX_EXACT_INTEGER or value > _MAX_EXACT_INTEGER:
            fail("Circular reducer integers exceed the exact ±2^53 range")
        return float(value)
    if type(value) is not float or not math.isfinite(value):
        fail("Circular reducer inputs must be finite numbers or null")
    return value


def _relative_difference(angle: float, origin: float, origin_sin: float,
                         origin_cos: float) -> float:
    """Find a wrapped difference without reducing a huge absolute angle."""
    if angle == origin:
        return 0.0
    opposite_signs = (angle < 0.0 < origin) or (origin < 0.0 < angle)
    if opposite_signs and abs(angle) > sys.float_info.max - abs(origin):
        difference = math.inf
    else:
        difference = angle - origin
    if math.isfinite(difference) and abs(difference) <= math.pi:
        return difference

    # libm's sin/cos argument reduction retains the phase of large finite
    # inputs. A manual `angle % tau` would not.
    angle_sin, angle_cos = math.sin(angle), math.cos(angle)
    sine = angle_sin * origin_cos - angle_cos * origin_sin
    cosine = angle_cos * origin_cos + angle_sin * origin_sin
    return math.atan2(sine, cosine)


def _canonical_angle(value: float) -> float:
    # atan2 may return +pi on the branch cut; use the negative equivalent.
    return -math.pi if value >= math.pi else value


def _cosine_sum(differences: list[float]) -> float:
    """Sum cosines without erasing the small remainder near antipodes."""
    def terms():
        for value in differences:
            magnitude = abs(value)
            if magnitude > math.pi / 2.0:
                offset = math.pi - magnitude
                yield -1.0
                yield 2.0 * math.sin(offset / 2.0) ** 2
            else:
                yield math.cos(value)

    return math.fsum(terms())


def _stable_small_spread(residuals: list[float]) -> float:
    """Compute an RMS limit when squared angular differences underflow."""
    scale = max((abs(value) for value in residuals), default=0.0)
    if scale == 0.0:
        return 0.0
    scaled_sum = math.fsum((value / scale) ** 2 for value in residuals)
    return scale * math.sqrt(scaled_sum / len(residuals))


def _kernel(angles: list[float], reducer_name: str) -> float | None:
    count = len(angles)
    if not count:
        return None

    origin = angles[0]
    origin_sin, origin_cos = math.sin(origin), math.cos(origin)
    differences = [
        _relative_difference(value, origin, origin_sin, origin_cos)
        for value in angles
    ]
    local_cosine = _cosine_sum(differences)
    local_sine = math.fsum(math.sin(value) for value in differences)
    resultant = min(1.0, math.hypot(local_cosine, local_sine) / count)

    if resultant <= _ZERO_RESULTANT:
        if reducer_name == "Reducer.circularVariance":
            return 1.0
        return None
    global_cosine = local_cosine * origin_cos - local_sine * origin_sin
    global_sine = local_sine * origin_cos + local_cosine * origin_sin
    mean = _canonical_angle(math.atan2(global_sine, global_cosine))
    if reducer_name == "Reducer.circularMean":
        return mean

    if resultant < 0.5:
        variance = 1.0 - resultant
        standard_deviation = math.sqrt(-2.0 * math.log(resultant))
    else:
        local_mean = math.atan2(local_sine, local_cosine)
        residuals = [
            math.remainder(value - local_mean, _TAU)
            for value in differences
        ]
        deficit = math.fsum(
            2.0 * math.sin(value / 2.0) ** 2 for value in residuals
        ) / count
        variance = min(1.0, max(0.0, deficit))
        if deficit == 0.0 and any(residuals):
            # The variance can be below Float64's representable square range,
            # while its square root is still representable.
            standard_deviation = _stable_small_spread(residuals)
        elif deficit >= 1.0:
            standard_deviation = math.sqrt(-2.0 * math.log(resultant))
        else:
            standard_deviation = math.sqrt(-2.0 * math.log1p(-deficit))

    return standard_deviation if reducer_name == "Reducer.circularStddev" else variance


def _output(translator, output_name: str, value: float | None):
    # A finite binary64 repr is bounded by 24 characters. Reserve the scan,
    # serialization inspection and owned result pair before repr/list creation.
    _charge(translator, 1 + len(output_name) + 24)
    if value is not None and (type(value) is not float or not math.isfinite(value)):
        fail("Circular reducer produced a non-finite output")
    wire_value = "null" if value is None else repr(value)
    if 2 + len(output_name) + len(wire_value) + 3 > MAX_CIRCULAR_OUTPUT_BYTES:
        fail("Circular reducer output exceeds the 1 MB JSON size limit")
    return [(output_name, value)]


def reduce_circular_reducer(
    translator, leaf: CircularReducerLeaf, records,
) -> list[tuple[str, float | None]]:
    """Evaluate one circular statistic over at most 1000 one-column rows.

    Nulls are ignored. Values are radians; inputs are unweighted static scalars.
    """
    name = _validate_leaf(translator, leaf)
    if type(records) is not list or len(records) > MAX_CIRCULAR_ROWS:
        fail("Circular reducer requires at most 1000 inline rows")
    # Reserve the complete row walk and value-vector allocation before reading.
    _charge(translator, 1 + 3 * len(records))
    angles = []
    for row in records:
        if type(row) is not list or len(row) != 1:
            fail("Circular reducer rows must contain exactly one input")
        value = _number(row[0])
        if value is not None:
            angles.append(value)

    # Covers global and relative trig, reductions, centered differences,
    # squared-error accumulation, and residual/value-vector allocations.
    _charge(translator, 32 + 32 * len(angles))
    result = _kernel(angles, name)
    return _output(translator, _OUTPUTS[name][0], result)
