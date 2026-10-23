"""Closed descriptors and work limits for finite quantile-style reducers."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math

from .ir import fail


MAX_QUANTILE_ROWS = 1_000
MAX_QUANTILE_OUTPUTS = 256
MAX_QUANTILE_NAME_CHARS = 64
MAX_QUANTILE_WORK = 50_000
MAX_QUANTILE_OUTPUT_BYTES = 1_000_000
MAX_EXACT_INTEGER = 2**53
MAX_QUANTILE_SCALAR_BITS = 1_100
_QUANTILE_SCALAR_LIMBS = (MAX_QUANTILE_SCALAR_BITS + 63) // 64

QUANTILE_REDUCER_NAMES = frozenset({
    "Reducer.percentile",
    "Reducer.intervalMean",
    "Reducer.mode",
})


@dataclass(frozen=True, slots=True)
class QuantileReducerLeaf:
    """Detached immutable parameters for one finite scalar reducer."""

    name: str
    percentiles: tuple[Fraction, ...]
    outputs: tuple[str, ...]
    max_raw: int | None


def _charge(translator, amount: int, purpose: str) -> None:
    if type(amount) is not int or amount < 0 or amount > MAX_QUANTILE_WORK:
        fail(f"{purpose} exceeds the shared 50000-step work budget")
    if translator is None:
        return
    if type(getattr(translator, "steps", None)) is not int:
        fail("Quantile reducer requires a translator work counter")
    if translator.steps + amount > MAX_QUANTILE_WORK:
        fail(f"{purpose} exceeds the shared 50000-step work budget")
    translator.steps += amount


def _argument_number(value, label: str) -> tuple[Fraction, float]:
    if type(value) is int:
        if value.bit_length() > 54:
            fail(f"{label} must be within the exact ±2^53 integer range")
        if not -MAX_EXACT_INTEGER <= value <= MAX_EXACT_INTEGER:
            fail(f"{label} must be within the exact ±2^53 integer range")
        return Fraction(value), float(value)
    if type(value) is float and math.isfinite(value):
        return Fraction.from_float(value), value
    fail(f"{label} must be a finite number")


def _percentile_label(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return repr(value)


def _max_raw(arguments) -> int | None:
    raw = arguments.get("maxRaw")
    if raw is None:
        return None
    if type(raw) is int:
        if raw.bit_length() > 54:
            fail("Quantile reducer maxRaw must be a nonnegative exact integer")
        result = raw
    elif type(raw) is float and math.isfinite(raw) and raw.is_integer():
        if raw < 0 or raw > MAX_EXACT_INTEGER:
            fail("Quantile reducer maxRaw must be a nonnegative exact integer")
        result = int(raw)
    else:
        fail("Quantile reducer maxRaw must be a nonnegative exact integer")
    if result < 0 or result > MAX_EXACT_INTEGER:
        fail("Quantile reducer maxRaw must be a nonnegative exact integer")
    return result


def _validate_leaf(translator, leaf: QuantileReducerLeaf):
    if type(leaf) is not QuantileReducerLeaf:
        fail("Quantile reducer leaf has an invalid type")
    name, percentiles, outputs, max_raw = (
        leaf.name, leaf.percentiles, leaf.outputs, leaf.max_raw,
    )
    if type(name) is not str:
        fail("Quantile reducer leaf has an invalid canonical name")
    if len(name) > MAX_QUANTILE_NAME_CHARS:
        fail("Quantile reducer leaf name exceeds the bounded length")
    _charge(translator, 1 + len(name), "Quantile reducer leaf name")
    if name not in QUANTILE_REDUCER_NAMES:
        fail("Quantile reducer leaf has an invalid canonical name")
    if (type(percentiles) is not tuple or type(outputs) is not tuple
            or (max_raw is not None and type(max_raw) is not int)):
        fail("Quantile reducer leaf has invalid canonical fields")
    if max_raw is not None:
        if max_raw.bit_length() > 54:
            fail("Quantile reducer leaf has an invalid maxRaw limit")
        _charge(translator, 1, "Quantile reducer maxRaw limit")
        if not 0 <= max_raw <= MAX_EXACT_INTEGER:
            fail("Quantile reducer leaf has an invalid maxRaw limit")
    if len(percentiles) > MAX_QUANTILE_OUTPUTS or len(outputs) > MAX_QUANTILE_OUTPUTS:
        fail("Quantile reducer exceeds the 256-output limit")
    _charge(translator, 1 + len(percentiles) + len(outputs),
            "Quantile reducer parameter scans")
    for output in outputs:
        if type(output) is not str or len(output) > MAX_QUANTILE_NAME_CHARS:
            fail("Quantile reducer output names must be bounded strings")
        _charge(translator, 1 + len(output), "Quantile reducer output name")
    for value in percentiles:
        if type(value) is not Fraction:
            fail("Quantile reducer leaf has invalid percentile values")
        bit_count = value.numerator.bit_length() + value.denominator.bit_length()
        if bit_count > MAX_QUANTILE_SCALAR_BITS:
            fail("Quantile reducer percentile rational exceeds its bounded size")
        _charge(translator, 1 + (bit_count + 63) // 64,
                "Quantile reducer percentile rational")
        if not 0 <= value <= 100:
            fail("Quantile reducer leaf has invalid percentile values")
    expected = {
        "Reducer.mode": (0, 1, ("mode",)),
        "Reducer.intervalMean": (2, 1, ("intervalMean",)),
    }
    if name == "Reducer.percentile":
        if not 1 <= len(percentiles) <= MAX_QUANTILE_OUTPUTS or len(outputs) != len(percentiles):
            fail("Reducer.percentile requires 1 to 256 matching percentile outputs")
    else:
        minimum, maximum, canonical_outputs = expected[name]
        if (len(percentiles) != minimum or len(outputs) != maximum
                or outputs != canonical_outputs):
            fail("Quantile reducer leaf does not match its canonical parameters")
        if name == "Reducer.intervalMean" and percentiles[0] > percentiles[1]:
            fail("Reducer.intervalMean percentiles must be ordered")
    if sum(6 * len(output) + 32 for output in outputs) + 2 > MAX_QUANTILE_OUTPUT_BYTES:
        fail("Quantile reducer output exceeds the 1 MB JSON size limit")
    return 1, outputs


def make_quantile_reducer(translator, name, arguments) -> QuantileReducerLeaf:
    """Parse a pinned Reducer constructor into a bounded immutable leaf."""
    if type(name) is not str:
        fail(f"Unsupported quantile reducer: {name}")
    if len(name) > MAX_QUANTILE_NAME_CHARS:
        fail("Quantile reducer name exceeds the bounded length")
    _charge(translator, 1 + len(name), "Quantile reducer name")
    if name not in QUANTILE_REDUCER_NAMES:
        fail(f"Unsupported quantile reducer: {name}")
    if type(arguments) is not dict:
        fail("Quantile reducer arguments must be a dictionary")
    if len(arguments) > 8:
        fail("Quantile reducer has too many arguments")
    _charge(translator, 1 + len(arguments), "Quantile reducer arguments")
    for key in arguments:
        if type(key) is not str or len(key) > MAX_QUANTILE_NAME_CHARS:
            fail("Quantile reducer argument names must be bounded strings")
        _charge(translator, 1 + len(key), "Quantile reducer argument names")

    common = {"maxBuckets", "minBucketWidth", "maxRaw"}
    if name == "Reducer.percentile":
        allowed = common | {"percentiles", "outputNames"}
        required = {"percentiles"}
    elif name == "Reducer.intervalMean":
        allowed = common | {"minPercentile", "maxPercentile"}
        required = {"minPercentile", "maxPercentile"}
    else:
        allowed, required = common, set()
    translator.allowed(arguments, allowed)
    if required - arguments.keys():
        fail(f"{name} is missing required arguments")
    if any(key in arguments and arguments[key] is not None
           for key in ("maxBuckets", "minBucketWidth")):
        fail(f"{name} does not support explicit histogram parameters")
    max_raw = _max_raw(arguments)

    percentiles: tuple[Fraction, ...]
    if name == "Reducer.percentile":
        raw_percentiles = arguments["percentiles"]
        if type(raw_percentiles) is not list:
            fail("Reducer.percentile percentiles must be a list")
        if not 1 <= len(raw_percentiles) <= MAX_QUANTILE_OUTPUTS:
            fail("Reducer.percentile requires 1 to 256 percentiles")
        _charge(translator, 1 + len(raw_percentiles), "Percentile input list")
        fractions, numeric = [], []
        for value in raw_percentiles:
            _charge(translator, 1 + _QUANTILE_SCALAR_LIMBS,
                    "Percentile rational conversion")
            exact, number = _argument_number(value, "Reducer.percentile values")
            if not 0 <= exact <= 100:
                fail("Reducer.percentile values must be between 0 and 100")
            fractions.append(exact)
            numeric.append(number)
        raw_outputs = arguments.get("outputNames")
        if raw_outputs is None:
            _charge(translator, 1 + len(numeric), "Default percentile output names")
            labels = [f"p{_percentile_label(value)}" for value in numeric]
            _charge(translator, sum(1 + len(label) for label in labels),
                    "Default percentile output-name copy")
            outputs = tuple(labels)
        else:
            if type(raw_outputs) is not list or len(raw_outputs) != len(fractions):
                fail("Reducer.percentile outputNames must match the percentile list")
            _charge(translator, 1 + len(raw_outputs), "Percentile output-name list")
            copied = []
            for output in raw_outputs:
                if type(output) is not str or len(output) > MAX_QUANTILE_NAME_CHARS:
                    fail("Reducer.percentile outputNames must be bounded strings")
                _charge(translator, 1 + len(output), "Percentile output name")
                copied.append(output)
            _charge(translator, 1 + len(copied), "Percentile output-name copy")
            outputs = tuple(copied)
        _charge(translator, 1 + len(fractions), "Percentile rational copy")
        percentiles = tuple(fractions)
    elif name == "Reducer.intervalMean":
        _charge(translator, 2 * (1 + _QUANTILE_SCALAR_LIMBS),
                "Interval percentile rational conversion")
        lower, _ = _argument_number(
            arguments["minPercentile"], "Reducer.intervalMean minPercentile",
        )
        upper, _ = _argument_number(
            arguments["maxPercentile"], "Reducer.intervalMean maxPercentile",
        )
        if not 0 <= lower <= upper <= 100:
            fail("Reducer.intervalMean requires 0 <= minPercentile <= maxPercentile <= 100")
        percentiles, outputs = (lower, upper), ("intervalMean",)
    else:
        percentiles, outputs = (), ("mode",)

    leaf = QuantileReducerLeaf(name, percentiles, outputs, max_raw)
    _validate_leaf(translator, leaf)
    return leaf


def describe_quantile_reducer(translator, leaf) -> tuple[int, tuple[str, ...]]:
    """Return the single input arity and output names after leaf validation."""
    return _validate_leaf(translator, leaf)
