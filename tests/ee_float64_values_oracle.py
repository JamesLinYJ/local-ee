"""Independent Fraction/Decimal numerical oracle for Float64 kernel fixtures."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, localcontext
from fractions import Fraction
import json
import math
import struct
import sys
from typing import Any


OPERATIONS = (
    "add", "subtract", "multiply", "divide", "power", "mod", "min2", "max2",
    "and", "or", "absolute", "sqrt", "log", "log10", "exp", "round", "floor",
    "ceil", "sin", "cos", "tan", "not",
)
MIN_SUBNORMAL = math.ulp(0.0)
MAX_FLOAT = sys.float_info.max
PI = Decimal(
    "3.141592653589793238462643383279502884197169399375105820974944592307816406286"
    "208998628034825342117067982148086513282306647093844609550582231725359408128481"
    "117450284102701938521105559644622948954930381964428810975665933446128475648233"
    "786783165271201909145648566923460348610454326648213393607260249141273724587006"
    "606315588174881520920962829254091715364367892590360011330530548820466521384146"
    "951941511609433057270365759591953092186117381932611793105118548074462379962749"
    "567351885752724891227938183011949129833673362440656643086021394946395224737190"
)


def binary64_hex(value: float | int) -> str:
    return struct.pack(">d", float(value)).hex()


def _band(index: int) -> dict[str, int]:
    return {"band": index}


def _constant(value: float | int) -> dict[str, str]:
    return {"constant": binary64_hex(value)}


def canonical_spec(operation: str, operands: list[dict[str, Any]],
                   dtype: str | None = None) -> str:
    return json.dumps({"dtype": dtype, "op": operation, "operands": operands, "v": 1},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _encode(value: float | int | None) -> str:
    if value is None:
        return "NaN"
    number = float(value)
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "Infinity" if number > 0 else "-Infinity"
    return number.hex()


def _decode(value: str) -> float | None:
    if value == "NaN":
        return None
    if value == "Infinity":
        return math.inf
    if value == "-Infinity":
        return -math.inf
    return float.fromhex(value)


def _negative(value: float) -> bool:
    return math.copysign(1.0, value) < 0.0


def _round_fraction(value: Fraction, negative_zero: bool = False) -> float:
    if value == 0:
        return math.copysign(0.0, -1.0 if negative_zero else 1.0)
    try:
        result = float(value)
    except OverflowError:
        return math.nan
    return result if math.isfinite(result) else math.nan


def _decimal_float(value: Decimal) -> float:
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def _fraction(value: float) -> Fraction:
    return Fraction.from_float(value)


def _binary_fraction(operation: str, left: float, right: float) -> float:
    a, b = _fraction(left), _fraction(right)
    if operation == "add":
        value = a + b
        negative_zero = value == 0 and left == right == 0.0 and _negative(left) and _negative(right)
    elif operation == "subtract":
        value = a - b
        negative_zero = (value == 0 and left == right == 0.0
                         and _negative(left) and not _negative(right))
    elif operation == "multiply":
        value = a * b
        negative_zero = value == 0 and (_negative(left) != _negative(right))
    elif operation == "divide":
        if right == 0.0:
            # The local contract maps every zero divisor, including 0/0, to +0.
            return 0.0
        value = a / b
        negative_zero = value == 0 and (_negative(left) != _negative(right))
    elif operation == "mod":
        if right == 0.0:
            return math.nan
        quotient = abs(a / b)
        whole = quotient.numerator // quotient.denominator
        if (left < 0.0) != (right < 0.0):
            whole = -whole
        value = a - whole * b
        negative_zero = value == 0 and _negative(left)
    else:
        raise AssertionError(operation)
    return _round_fraction(value, negative_zero)


def _decimal_trig(operation: str, value: float) -> float:
    if value == 0.0:
        if operation == "cos":
            return 1.0
        return value
    with localcontext() as context:
        context.prec = 280
        x = Decimal.from_float(value)
        period = PI * 2
        quotient = (x / period).to_integral_value(rounding=ROUND_DOWN)
        x -= quotient * period
        if x > PI:
            x -= period
        elif x < -PI:
            x += period
        square = x * x
        sine = x
        cosine = Decimal(1)
        sine_term = x
        cosine_term = Decimal(1)
        index = 1
        while index < 700:
            sine_term *= -square / Decimal((2 * index) * (2 * index + 1))
            cosine_term *= -square / Decimal((2 * index - 1) * (2 * index))
            sine += sine_term
            cosine += cosine_term
            if abs(sine_term) < Decimal("1e-270") and abs(cosine_term) < Decimal("1e-270"):
                break
            index += 1
        result = {"sin": sine, "cos": cosine}.get(operation)
        if operation == "tan":
            if cosine == 0:
                return math.nan
            result = sine / cosine
        assert result is not None
        return _decimal_float(result)


def _power(left: float, right: float) -> float:
    if left == 0.0:
        if right == 0.0:
            return 1.0
        if right < 0.0:
            return math.nan
        negative_zero = _negative(left) and right.is_integer() and int(right) % 2 != 0
        return math.copysign(0.0, -1.0 if negative_zero else 1.0)
    if left < 0.0:
        if not right.is_integer():
            return math.nan
        exponent = int(right)
        if abs(exponent) > 10000:
            return math.nan if abs(left) > 1.0 and exponent > 0 else 0.0
        return _round_fraction(_fraction(left) ** exponent)
    with localcontext() as context:
        context.prec = 280
        try:
            result = (Decimal.from_float(left).ln() * Decimal.from_float(right)).exp()
        except Exception:
            return math.nan
        return _decimal_float(result)


def _transcendental(operation: str, value: float) -> float:
    if operation in {"sin", "cos", "tan"}:
        return _decimal_trig(operation, value)
    if operation == "sqrt" and value < 0.0:
        return math.nan
    if operation in {"log", "log10"} and value <= 0.0:
        return math.nan
    if operation == "sqrt" and value == 0.0:
        return value
    with localcontext() as context:
        context.prec = 280
        try:
            number = Decimal.from_float(value)
            if operation == "sqrt":
                result = number.sqrt()
            elif operation == "log":
                result = number.ln()
            elif operation == "log10":
                result = number.log10()
            elif operation == "exp":
                result = number.exp()
            else:
                raise AssertionError(operation)
        except Exception:
            return math.nan
        return _decimal_float(result)


def evaluate(operation: str, values: list[float]) -> float:
    left = values[0]
    if operation in {"add", "subtract", "multiply", "divide", "mod"}:
        return _binary_fraction(operation, left, values[1])
    if operation == "power":
        return _power(left, values[1])
    if operation == "min2":
        right = values[1]
        if left == right == 0.0:
            return -0.0 if _negative(left) or _negative(right) else 0.0
        return min(left, right)
    if operation == "max2":
        right = values[1]
        if left == right == 0.0:
            return 0.0 if not _negative(left) or not _negative(right) else -0.0
        return max(left, right)
    if operation == "and":
        return 1.0 if left != 0.0 and values[1] != 0.0 else 0.0
    if operation == "or":
        return 1.0 if left != 0.0 or values[1] != 0.0 else 0.0
    if operation == "absolute":
        return abs(left)
    if operation == "round":
        if abs(left) >= 1 << 52:
            return left
        return float(math.floor(left + 0.5))
    if operation == "floor":
        if left == 0.0:
            return left
        return float(math.floor(left))
    if operation == "ceil":
        if left == 0.0:
            return left
        result = float(math.ceil(left))
        return math.copysign(0.0, -1.0) if result == 0.0 and left < 0.0 else result
    if operation == "not":
        return 1.0 if left == 0.0 else 0.0
    return _transcendental(operation, left)


def reference(case: dict[str, Any]) -> list[float | None]:
    wire = json.loads(case["spec"])
    operands = wire["operands"]
    bands = [[_decode(value) for value in band] for band in case["bands"]]
    width = len(bands[0])
    if any(len(band) != width for band in bands):
        raise ValueError("fixture bands must have matching widths")
    result: list[float | None] = []
    for col in range(width):
        values: list[float] = []
        valid = True
        for operand in operands:
            if "band" in operand:
                value = bands[operand["band"]][col]
                if value is None:
                    valid = False
                    break
                values.append(value)
            else:
                values.append(struct.unpack(">d", bytes.fromhex(operand["constant"]))[0])
        if not valid:
            result.append(None)
            continue
        output = evaluate(wire["op"], values)
        result.append(None if math.isnan(output) else output)
    return result
