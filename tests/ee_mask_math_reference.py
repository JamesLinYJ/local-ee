"""Independent Float64 references for Wave66 masked image arithmetic."""
from __future__ import annotations

from fractions import Fraction
import json
import math
from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-mask-math-wave66-v1.json"
CORE_UNARY = ("abs", "sqrt", "log", "log10", "exp", "round", "floor", "ceil",
              "sin", "cos", "tan", "Not")
BINARY = ("add", "subtract", "multiply", "divide", "pow", "mod", "eq", "neq",
          "gt", "gte", "lt", "lte", "And", "Or", "min", "max")
PIXEL_MATH_UNARY = ("asin", "acos", "atan", "sinh", "cosh", "tanh", "cbrt",
                    "signum", "gamma", "digamma", "trigamma", "erf", "erfc",
                    "erfInv", "erfcInv")
DOUBLE_LIBM_OPERATIONS = frozenset({
    "sqrt", "log", "log10", "exp", "sin", "cos", "tan", "pow", "mod",
})


def comparison_policy(output_name: str) -> str:
    """Select value-check precision from the named operation and dtype boundary.

    The legacy Float32 callback allowance is limited to `math_*` special
    functions, including atan2 and the explicit Float32 asin probe. Basic
    Float64 math and conversions remain bit-exact; Double libm operations use
    an ULP check against the independent reference.
    """
    if output_name.startswith("wide_pixel_") or output_name == "wide_float32_asin":
        return "float32_callback"
    if output_name == "wide_to_float":
        return "float32_cast_exact"
    if output_name.endswith("_unit_scale"):
        return "float64_ulp"
    parts = output_name.split("_")
    operation = parts[-2] if parts[-1] in {"left", "right"} else parts[-1]
    if operation in DOUBLE_LIBM_OPERATIONS:
        return "float64_ulp"
    return "float64_exact"


def load_fixture() -> dict:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if fixture.get("schema") != "local-ee-mask-math-wave66/v1":
        raise ValueError("unexpected Wave66 mask-math fixture schema")
    return fixture


def parse_number(value):
    if value is None:
        return None
    if value == "Infinity":
        return math.inf
    if value == "-Infinity":
        return -math.inf
    if value == "NaN":
        return math.nan
    return float(value)


def float32(value: float) -> float:
    """Round to IEEE binary32, preserving overflow as signed infinity."""
    try:
        return struct.unpack("!f", struct.pack("!f", value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


def _rounded(value: float) -> float:
    # Match the local ties-toward-positive-infinity policy independently of Scala.
    if abs(value) >= 2**52:
        return value
    lower = math.floor(value)
    return float(lower + (value - lower >= 0.5))


def unary_value(operation: str, value: float) -> float:
    """Evaluate a core unary function; invalid domains return IEEE NaN/Infinity."""
    if math.isnan(value):
        return math.nan
    try:
        if operation == "abs":
            return abs(value)
        if operation == "sqrt":
            return math.sqrt(value) if value >= 0 else math.nan
        if operation == "log":
            return math.log(value) if value > 0 else (-math.inf if value == 0 else math.nan)
        if operation == "log10":
            return math.log10(value) if value > 0 else (-math.inf if value == 0 else math.nan)
        if operation == "exp":
            return math.exp(value)
        if operation == "round":
            return _rounded(value)
        if operation == "floor":
            return float(math.floor(value))
        if operation == "ceil":
            # IEEE ceil keeps the sign bit when a negative fraction rounds to
            # zero; Python's math.ceil returns integer 0 and loses that bit.
            if -1.0 < value < 0.0:
                return -0.0
            return float(math.ceil(value))
        if operation == "sin":
            return math.sin(value)
        if operation == "cos":
            return math.cos(value)
        if operation == "tan":
            return math.tan(value)
        if operation == "Not":
            return 0.0 if value != 0.0 else 1.0
    except (OverflowError, ValueError):
        return math.inf if operation == "exp" and value > 0 else math.nan
    raise ValueError(f"unsupported unary operation: {operation}")


def _exact_binary(operation: str, left: float, right: float) -> float | None:
    """Use exact binary rationals for basic arithmetic before one final rounding."""
    if operation not in {"add", "subtract", "multiply", "divide"}:
        return None
    if operation == "divide" and right == 0.0:
        return 0.0
    a, b = Fraction.from_float(left), Fraction.from_float(right)
    value = {
        "add": lambda: a + b,
        "subtract": lambda: a - b,
        "multiply": lambda: a * b,
        "divide": lambda: a / b,
    }[operation]()
    try:
        return float(value)
    except OverflowError:
        return math.copysign(math.inf, value.numerator)


def binary_value(operation: str, left: float, right: float) -> float:
    """Evaluate one supported image/scalar operation without using the native kernel."""
    if math.isnan(left) or math.isnan(right):
        return math.nan
    exact = _exact_binary(operation, left, right)
    if exact is not None:
        return exact
    if operation == "pow":
        try:
            return math.pow(left, right)
        except (OverflowError, ValueError):
            return math.copysign(math.inf, left) if abs(left) > 1 and right > 0 else math.nan
    if operation == "mod":
        if right == 0.0:
            return math.nan
        return math.fmod(left, right)
    if operation == "eq":
        return float(left == right)
    if operation == "neq":
        return float(left != right)
    if operation == "gt":
        return float(left > right)
    if operation == "gte":
        return float(left >= right)
    if operation == "lt":
        return float(left < right)
    if operation == "lte":
        return float(left <= right)
    if operation == "And":
        return float(left != 0.0 and right != 0.0)
    if operation == "Or":
        return float(left != 0.0 or right != 0.0)
    if operation == "min":
        return min(left, right)
    if operation == "max":
        return max(left, right)
    raise ValueError(f"unsupported binary operation: {operation}")


def clamp_value(value: float, low: float, high: float) -> float:
    if not high > low:
        raise ValueError("clamp requires high > low")
    return min(max(value, low), high)


def unit_scale_value(value: float, low: float, high: float) -> float:
    if not high > low:
        raise ValueError("unitScale requires high > low")
    x, a, b = map(Fraction.from_float, (value, low, high))
    return float((x - a) / (b - a))


def _digamma(value: float) -> float:
    if value <= 0 and value == math.floor(value):
        return math.nan
    if value < 0:
        fraction = value - math.floor(value)
        reflected = _digamma(1.0 - value)
        return reflected - math.pi * math.cos(math.pi * fraction) / math.sin(math.pi * fraction)
    result = 0.0
    while value < 8.0:
        result -= 1.0 / value
        value += 1.0
    inverse = 1.0 / value
    square = inverse * inverse
    return result + math.log(value) - inverse / 2.0 - square * (
        1.0 / 12.0 - square * (1.0 / 120.0 - square / 252.0)
    )


def _trigamma(value: float) -> float:
    if value <= 0 and value == math.floor(value):
        return math.nan
    if value < 0:
        fraction = value - math.floor(value)
        sine = math.sin(math.pi * fraction)
        return math.pi * math.pi / (sine * sine) - _trigamma(1.0 - value)
    result = 0.0
    while value < 8.0:
        result += 1.0 / (value * value)
        value += 1.0
    inverse = 1.0 / value
    square = inverse * inverse
    return result + inverse + square / 2.0 + inverse * square / 6.0 - (
        inverse * square * square / 30.0
    )


def _inverse_erf(value: float) -> float:
    if not -1.0 < value < 1.0:
        return math.nan
    low, high = -6.0, 6.0
    for _ in range(100):
        middle = (low + high) / 2.0
        if math.erf(middle) < value:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def pixel_math_value(operation: str, value: float) -> float:
    """Float32 input/output reference for the retained math_* callback family."""
    staged = float32(value)
    if not math.isfinite(staged):
        return math.nan
    try:
        result = {
            "asin": lambda: math.asin(staged),
            "acos": lambda: math.acos(staged),
            "atan": lambda: math.atan(staged),
            "sinh": lambda: math.sinh(staged),
            "cosh": lambda: math.cosh(staged),
            "tanh": lambda: math.tanh(staged),
            "cbrt": lambda: math.copysign(abs(staged) ** (1.0 / 3.0), staged),
            "signum": lambda: math.copysign(1.0, staged) if staged else staged,
            "gamma": lambda: math.gamma(staged),
            "digamma": lambda: _digamma(staged),
            "trigamma": lambda: _trigamma(staged),
            "erf": lambda: math.erf(staged),
            "erfc": lambda: math.erfc(staged),
            "erfInv": lambda: _inverse_erf(staged),
            "erfcInv": lambda: _inverse_erf(1.0 - staged),
        }[operation]()
    except (OverflowError, ValueError, ZeroDivisionError):
        return math.nan
    return float32(result) if math.isfinite(result) else math.nan


def masked_result(value, weight, operation, *, input_float32: bool = False):
    """Return (science, weight) after one operation and local result-validity masking."""
    raw = parse_number(value)
    mask = parse_number(weight)
    if raw is not None and not math.isfinite(raw):
        raise ValueError("source scientific values must be finite or NoData")
    if raw is None:
        return None, 0.0
    if mask is None:
        mask = 0.0
    if not math.isfinite(mask) or not 0.0 <= mask <= 1.0:
        raise ValueError("fractional mask weight must be finite and in [0,1]")
    staged = float32(raw) if input_float32 else raw
    try:
        result = operation(staged)
    except (OverflowError, ValueError, ZeroDivisionError):
        result = math.nan
    if not math.isfinite(result):
        return None, 0.0
    if mask == 0.0:
        return None, 0.0
    return float(result), mask


def source_bands(fixture: dict) -> tuple[dict[str, list], dict[str, list]]:
    tile = fixture["tiles"][0]
    raw = {row["name"]: row["values"] for row in tile["raw_bands"]}
    weights = {row["name"]: row["values"] for row in tile["mask_bands"]}
    return raw, weights


def expected_outputs(fixture: dict) -> dict[str, dict[str, list]]:
    """Build expected sampled values and separately retained mask weights."""
    raw, weights = source_bands(fixture)
    output: dict[str, dict[str, list]] = {}

    def evaluate(name: str, band: str, function, *, f32: bool = False) -> None:
        values, masks = [], []
        weight_band = f"{band}_weight"
        for value, weight in zip(raw[band], weights[weight_band]):
            result, result_weight = masked_result(value, weight, function, input_float32=f32)
            values.append(result)
            masks.append(result_weight)
        output[name] = {"values": values, "weights": masks}

    for band in fixture["bands"]:
        for operation in fixture["operations"]["unary"]:
            evaluate(f"{band}_{operation.lower()}", band,
                     lambda value, op=operation: unary_value(op, value))

    constant = float(fixture["operations"]["binary_constant"])
    for operation in fixture["operations"]["binary"]:
        evaluate(f"wide_{operation.lower()}_right", "wide",
                 lambda value, op=operation: binary_value(op, value, constant))
        evaluate(f"wide_{operation.lower()}_left", "wide",
                 lambda value, op=operation: binary_value(op, constant, value))

    zero = float(fixture["operations"]["logic_zero"])
    for operation in ("And", "Or"):
        evaluate(f"red_{operation.lower()}_zero", "red",
                 lambda value, op=operation: binary_value(op, value, zero))
        evaluate(f"red_zero_{operation.lower()}", "red",
                 lambda value, op=operation: binary_value(op, zero, value))

    pixel_constant = float(fixture["operations"]["atan2_constant"])
    for operation in fixture["operations"]["pixel_math_unary"]:
        evaluate(f"wide_pixel_{operation.lower()}", "wide",
                 lambda value, op=operation: pixel_math_value(op, value), f32=True)
    for operation in fixture["operations"]["pixel_math_binary"]:
        evaluate(f"wide_pixel_{operation.lower()}_right", "wide",
                 lambda value: float32(math.atan2(float32(pixel_constant), float32(value)))
                 if math.isfinite(float32(value)) else math.nan, f32=True)
        evaluate(f"wide_pixel_{operation.lower()}_left", "wide",
                 lambda value: float32(math.atan2(float32(value), float32(pixel_constant)))
                 if math.isfinite(float32(value)) else math.nan, f32=True)

    low, high = map(float, fixture["operations"]["clamp"])
    evaluate("red_clamp", "red", lambda value: clamp_value(value, low, high))
    low, high = map(float, fixture["operations"]["unit_scale"])
    evaluate("red_unit_scale", "red", lambda value: unit_scale_value(value, low, high))

    band = fixture["operations"]["float32_band"]
    evaluate(f"{band}_to_float", band, float32)
    math_op = fixture["operations"]["float32_function"]
    evaluate(f"{band}_float32_{math_op}", band,
             lambda value: math.asin(value) if -1.0 <= value <= 1.0 else math.nan,
             f32=True)
    return output

