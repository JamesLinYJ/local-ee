"""Independent Float32 mathematical references for the pixel-math probe."""
from __future__ import annotations

import math
import struct


OPERATION_ARITIES = {
    "asin": 1,
    "acos": 1,
    "atan": 1,
    "atan2": 2,
    "sinh": 1,
    "cosh": 1,
    "tanh": 1,
    "cbrt": 1,
    "signum": 1,
    "gamma": 1,
    "digamma": 1,
    "trigamma": 1,
    "erf": 1,
    "erfc": 1,
    "erfInv": 1,
    "erfcInv": 1,
}

_F32_MAX = struct.unpack("!f", bytes.fromhex("7f7fffff"))[0]
_F32_MIN_SUBNORMAL = struct.unpack("!f", bytes.fromhex("00000001"))[0]
_EULER = 0.5772156649015328606
_ZETA = {
    2: math.pi**2 / 6.0,
    3: 1.2020569031595942854,
    4: math.pi**4 / 90.0,
    5: 1.0369277551433699263,
    6: math.pi**6 / 945.0,
    7: 1.0083492773819228268,
    8: math.pi**8 / 9450.0,
    9: 1.0020083928260822144,
    10: math.pi**10 / 93555.0,
    11: 1.0004941886041194646,
    12: 1.0002460865533080483,
}
def _f32(value: float) -> float:
    return struct.unpack("!f", struct.pack("!f", value))[0]


def _wire_float(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if value == math.inf:
        return "Infinity"
    if value == -math.inf:
        return "-Infinity"
    return value.hex()


def _positive_digamma(value: float) -> float:
    if value < 0.125:
        result = -_EULER - 1.0 / value
        power = value
        sign = 1.0
        for order in range(2, 13):
            result += sign * _ZETA[order] * power
            power *= value
            sign = -sign
        return result

    shifted = value
    result = 0.0
    while shifted < 8.0:
        result -= 1.0 / shifted
        shifted += 1.0
    inverse = 1.0 / shifted
    inverse2 = inverse * inverse
    tail = -inverse2 * (
        1.0 / 12.0
        - inverse2 * (
            1.0 / 120.0
            - inverse2 * (
                1.0 / 252.0
                - inverse2 * (
                    1.0 / 240.0
                    - inverse2 * (1.0 / 132.0 - inverse2 * 691.0 / 32760.0)
                )
            )
        )
    )
    return result + math.log(shifted) - 0.5 * inverse + tail


def _digamma(value: float) -> float:
    if value == 0.0 or (value < 0.0 and value.is_integer()):
        return math.nan
    if value > 0.0:
        return _positive_digamma(value)
    return _positive_digamma(1.0 - value) - math.pi / math.tan(math.pi * value)


def _positive_trigamma(value: float) -> float:
    if value < 0.125:
        if value < 1e-20:
            return math.inf
        result = 1.0 / (value * value) + _ZETA[2]
        power = value
        sign = -1.0
        for order in range(3, 13):
            result += sign * (order - 1) * _ZETA[order] * power
            power *= value
            sign = -sign
        return result

    shifted = value
    result = 0.0
    while shifted < 8.0:
        result += 1.0 / (shifted * shifted)
        shifted += 1.0
    inverse = 1.0 / shifted
    inverse2 = inverse * inverse
    tail = (
        inverse
        + 0.5 * inverse2
        + inverse * inverse2 / 6.0
        - inverse * inverse2**2 / 30.0
        + inverse * inverse2**3 / 42.0
        - inverse * inverse2**4 / 30.0
        + 5.0 * inverse * inverse2**5 / 66.0
        - 691.0 * inverse * inverse2**6 / 2730.0
    )
    return result + tail


def _trigamma(value: float) -> float:
    if value == 0.0 or (value < 0.0 and value.is_integer()):
        return math.nan
    if value > 0.0:
        return _positive_trigamma(value)
    sine = math.sin(math.pi * value)
    return (math.pi / sine) ** 2 - _positive_trigamma(1.0 - value)


def _erf_inverse(value: float) -> float:
    if value == 0.0:
        return value
    if abs(value) > 1.0:
        return math.nan
    if abs(value) == 1.0:
        return math.copysign(math.inf, value)
    sign = math.copysign(1.0, value)
    target = abs(value)
    low, high = 0.0, 6.0
    for _ in range(120):
        middle = (low + high) / 2.0
        if math.erf(middle) < target:
            low = middle
        else:
            high = middle
    return sign * ((low + high) / 2.0)


def _erfc_inverse(value: float) -> float:
    if value < 0.0 or value > 2.0:
        return math.nan
    if value == 0.0:
        return math.inf
    if value == 2.0:
        return -math.inf
    if value == 1.0:
        return 0.0
    low, high = -6.0, 6.0
    for _ in range(120):
        middle = (low + high) / 2.0
        if math.erfc(middle) > value:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def _evaluate(operation: str, values: tuple[float, ...]) -> float:
    x = values[0]
    if operation == "asin":
        return math.asin(x)
    if operation == "acos":
        return math.acos(x)
    if operation == "atan":
        return math.atan(x)
    if operation == "atan2":
        return math.atan2(values[1], x)
    if operation == "sinh":
        return math.sinh(x)
    if operation == "cosh":
        return math.cosh(x)
    if operation == "tanh":
        return math.tanh(x)
    if operation == "cbrt":
        return math.cbrt(x)
    if operation == "signum":
        if x == 0.0:
            return math.copysign(0.0, x)
        return math.copysign(1.0, x)
    if operation == "gamma":
        return math.gamma(x)
    if operation == "digamma":
        return _digamma(x)
    if operation == "trigamma":
        return _trigamma(x)
    if operation == "erf":
        return math.erf(x)
    if operation == "erfc":
        return math.erfc(x)
    if operation == "erfInv":
        return _erf_inverse(x)
    if operation == "erfcInv":
        return _erfc_inverse(x)
    raise ValueError(f"unknown reference operation: {operation}")


def _expected_float32(operation: str, values: tuple[float, ...]) -> float:
    if any(math.isnan(value) for value in values):
        return math.nan
    try:
        result = _evaluate(operation, values)
    except (OverflowError, ValueError, ZeroDivisionError):
        return math.nan
    if not math.isfinite(result) or abs(result) > _F32_MAX:
        return math.nan
    try:
        rounded = _f32(result)
    except OverflowError:
        return math.nan
    return rounded if math.isfinite(rounded) else math.nan


def _case(operation: str, bands: list[list[float]]) -> dict:
    if len(bands) != OPERATION_ARITIES[operation]:
        raise ValueError(f"{operation} needs {OPERATION_ARITIES[operation]} input bands")
    pixel_count = len(bands[0])
    if not pixel_count or any(len(band) != pixel_count for band in bands):
        raise ValueError(f"{operation} inputs must have the same positive pixel count")

    expected = []
    for pixel in range(pixel_count):
        operands = tuple(_f32(band[pixel]) for band in bands)
        expected.append(_wire_float(_expected_float32(operation, operands)))
    return {
        "operation": operation,
        "inputs": [[_wire_float(value) for value in band] for band in bands],
        "expected": expected,
        "max_ulps": 4,
    }


def make_fixture() -> dict:
    largest = _F32_MAX
    smallest = _F32_MIN_SUBNORMAL
    inputs = {
        "asin": [[-1.0, -0.5, -0.0, 0.0, 0.5, 1.0, 1.25, math.nan]],
        "acos": [[-1.0, -0.5, 0.0, 0.5, 1.0, 1.25, math.nan]],
        "atan": [[-largest, -1.0, -0.5, -0.0, 0.0, 0.5, 1.0, largest, math.nan]],
        "atan2": [
            [1.0, -1.0, -1.0, 1.0, 0.0, -0.0, 0.0, -0.0,
             0.5, -0.5, largest, -largest, 1.0, math.nan],
            [1.0, 1.0, -1.0, -1.0, 0.0, 0.0, -0.0, -0.0,
             -0.5, 0.5, largest, largest, math.nan, 1.0],
        ],
        "sinh": [[-largest, -10.0, -2.0, -0.0, 0.0, smallest, 0.5, 2.0, 10.0, largest]],
        "cosh": [[-largest, -10.0, -2.0, -0.0, 0.0, smallest, 0.5, 2.0, 10.0, largest]],
        "tanh": [[-largest, -10.0, -2.0, -0.0, 0.0, smallest, 0.5, 2.0, 10.0, largest]],
        "cbrt": [[-largest, -27.0, -8.0, -smallest, -0.0, 0.0,
                  smallest, 1.0, 8.0, 27.0, largest, math.nan]],
        "signum": [[-largest, -1.0, -smallest, -0.0, 0.0, smallest, 1.0, largest, math.nan]],
        "gamma": [[-largest, -0.5, 0.5, 1.0, 2.0, 5.0, 10.0, 35.0, 36.0,
                   -1.0, 0.0, -smallest, smallest, math.nan]],
        "digamma": [[-largest, -1.5, -0.5, 0.5, 1.0, 2.5, 8.0, 0.0, -1.0,
                     -smallest, smallest, largest, math.nan]],
        "trigamma": [[-largest, -1.5, -0.5, 0.5, 1.0, 2.5, 8.0, 0.0, -1.0,
                      -smallest, smallest, largest, math.nan]],
        "erf": [[-largest, -3.0, -1.0, -0.0, 0.0, 0.5, 1.0, 3.0, largest, math.nan]],
        "erfc": [[-largest, -10.0, -3.0, -1.0, 0.0, 0.5, 1.0, 3.0, 10.0, largest, math.nan]],
        "erfInv": [[-1.0, -0.999, -0.5, -0.0, 0.0, 0.5, 0.999, 1.0, 1.25,
                    math.erf(-0.5), math.erf(0.5), math.erf(1.0), math.nan]],
        "erfcInv": [[0.0, 0.001, 0.2, 0.5, 1.0, 1.5, 1.999, 2.0, 2.25,
                     math.erfc(-1.0), math.erfc(-0.5), math.erfc(0.5), math.nan]],
    }
    cases = [_case(operation, bands) for operation, bands in inputs.items()]
    return {
        "operations": OPERATION_ARITIES,
        "cases": cases,
        "pixel_count": sum(len(case["expected"]) for case in cases),
    }


def assert_reference_anchors() -> None:
    assert math.gamma(5.0) == 24.0
    assert math.isclose(_digamma(1.0), -_EULER, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(_digamma(-0.5), 2.0 - _EULER - 2.0 * math.log(2.0),
                        rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(_trigamma(1.0), math.pi**2 / 6.0, rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(_trigamma(-0.5), math.pi**2 / 2.0 + 4.0,
                        rel_tol=0.0, abs_tol=1e-12)
    assert math.isclose(math.erf(1.0), 0.8427007929497149, rel_tol=0.0, abs_tol=2e-16)
    assert _erf_inverse(0.0) == 0.0
    assert _erfc_inverse(1.0) == 0.0
    assert math.isclose(_erf_inverse(math.erf(0.5)), 0.5, rel_tol=0.0, abs_tol=1e-14)
    assert math.isclose(_erfc_inverse(math.erfc(-0.5)), -0.5, rel_tol=0.0, abs_tol=1e-14)
