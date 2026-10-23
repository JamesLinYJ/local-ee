"""Independent Float64 references and fixtures for trusted native tile probes."""
from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction
import math


def _decimal(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


def _wire(value: float) -> str:
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    return repr(value)


def _reference(reducer: str, samples: list[float]) -> float:
    values = [Fraction.from_float(value) for value in samples if not math.isnan(value)]
    if not values:
        return math.nan
    if reducer == "product":
        if any(value == 0.0 for value in samples if not math.isnan(value)):
            negative = sum(math.copysign(1.0, value) < 0.0 for value in samples if not math.isnan(value)) % 2
            return math.copysign(0.0, -1.0 if negative else 1.0)
        exact = Fraction(1)
        for value in values:
            exact *= value
        return float(exact)
    if reducer == "min":
        return float(min(values))
    if reducer == "max":
        return float(max(values))

    denominator = len(values) - 1 if reducer in {"sampleVariance", "sd"} else len(values)
    if denominator <= 0:
        return math.nan
    mean = sum(values, Fraction(0)) / len(values)
    variance = sum(((value - mean) ** 2 for value in values), Fraction(0)) / denominator
    if reducer == "sd":
        with localcontext() as context:
            context.prec = 3000
            return float(_decimal(variance).sqrt())
    if reducer == "stdDev":
        with localcontext() as context:
            context.prec = 3000
            return float(_decimal(variance).sqrt())
    return float(variance)


def _case(reducer: str, inputs: list[list[float]], name: str) -> dict:
    pixel_count = len(inputs[0])
    expected = [
        _reference(reducer, [band[pixel] for band in inputs])
        for pixel in range(pixel_count)
    ]
    return {
        "name": name,
        "reducer": reducer,
        "inputs": [[_wire(value) for value in band] for band in inputs],
        "expected": [_wire(value) for value in expected],
        "max_ulps": 16,
        "check_zero_sign": reducer == "product",
    }


def make_fixture() -> dict:
    tiny = math.ulp(0.0)
    product_inputs = [
        [1e308, tiny, -0.0, -0.0, math.nan],
        [1e308, tiny, 2.0, 2.0, math.nan],
        [1e-308, 1e308, -3.0, math.nan, math.nan],
        [1e-308, 1e308, math.nan, math.nan, math.nan],
    ]
    dispersion_inputs = [
        [1e16 - 4, 0.0, -1e200, 7.0, math.nan, 1e-200, 1e308],
        [1e16 - 2, 1e-160, 1e200, math.nan, math.nan,
         math.nextafter(1e-200, math.inf), math.nextafter(1e308, math.inf)],
        [1e16, -1e-160, math.nan, math.nan, math.nan, math.nan, math.nan],
        [1e16 + 2, math.nan, math.nan, math.nan, math.nan, math.nan, math.nan],
        [1e16 + 4, math.nan, math.nan, math.nan, math.nan, math.nan, math.nan],
    ]
    min_max_inputs = [
        [float(2**24), -1e200, math.nan, math.nan],
        [float(2**24 + 1), 1e200, 5.0, math.nan],
    ]
    cases = [_case("product", product_inputs, "normalized product, signed zero, and masks")]
    cases.extend((
        _case("min", min_max_inputs, "Float64 minimum kernel control"),
        _case("max", min_max_inputs, "Float64 maximum kernel control"),
    ))
    for reducer in ("stdDev", "variance", "sampleVariance", "sd"):
        case_inputs = dispersion_inputs
        if reducer in {"variance", "sampleVariance"}:
            case_inputs = [
                [math.nan if pixel in {2, 6} else value for pixel, value in enumerate(band)]
                for band in dispersion_inputs
            ]
        elif reducer == "sd":
            case_inputs = [
                list(band) for band in dispersion_inputs
            ]
        cases.append(_case(reducer, case_inputs, f"{reducer} Float64 dispersion controls"))

    invalid_inputs = [math.inf, 1.0]
    missing_inputs = [math.nan, math.nan]
    return {
        "cases": cases,
        "rejects": [
            {"name": "product final overflow", "reducer": "product",
             "inputs": [[_wire(1e308)], [_wire(1e308)]]},
            {"name": "population variance final overflow", "reducer": "variance",
             "inputs": [[_wire(-1e200)], [_wire(1e200)]]},
            {"name": "large adjacent population variance final overflow", "reducer": "variance",
             "inputs": [[_wire(1e308)], [_wire(math.nextafter(1e308, math.inf))]]},
            {"name": "sample variance final overflow", "reducer": "sampleVariance",
             "inputs": [[_wire(-1e200)], [_wire(1e200)]]},
            {"name": "legacy sample sd final overflow", "reducer": "sd",
             "inputs": [[_wire(-float.fromhex("0x1.fffffffffffffp+1023"))],
                        [_wire(float.fromhex("0x1.fffffffffffffp+1023"))]]},
            {"name": "nonfinite input", "reducer": "product",
             "inputs": [[_wire(value)] for value in invalid_inputs]},
            {"name": "unknown reducer on all NoData", "reducer": "minMax",
             "inputs": [[_wire(value)] for value in missing_inputs]},
        ],
        "pixel_count": sum(len(case["expected"]) for case in cases),
        "reference_anchors": {
            "product_overflow_cancellation": _wire(_reference("product", [1e308, 1e308, 1e-308, 1e-308])),
            "product_underflow_cancellation": _wire(_reference("product", [tiny, tiny, 1e308, 1e308])),
            "large_offset_population_variance": _wire(_reference("variance", [1e16 - 4, 1e16 - 2, 1e16, 1e16 + 2, 1e16 + 4])),
            "extreme_population_stddev": _wire(_reference("stdDev", [-1e200, 1e200])),
            "large_adjacent_population_stddev": _wire(_reference(
                "stdDev", [1e308, math.nextafter(1e308, math.inf)])),
            "large_adjacent_legacy_sample_sd": _wire(_reference(
                "sd", [1e308, math.nextafter(1e308, math.inf)])),
            "tiny_adjacent_population_stddev": _wire(_reference(
                "stdDev", [1e-200, math.nextafter(1e-200, math.inf)])),
            "tiny_legacy_sample_sd": _wire(_reference("sd", [0.0, 1e-160, -1e-160])),
            "float64_adjacent_min": _wire(_reference("min", [float(2**24), float(2**24 + 1)])),
            "float64_adjacent_max": _wire(_reference("max", [float(2**24), float(2**24 + 1)])),
        },
    }


def assert_reference_anchors(fixture: dict) -> None:
    anchors = fixture["reference_anchors"]
    assert anchors["product_overflow_cancellation"] != "0.0"
    assert anchors["product_underflow_cancellation"] != "0.0"
    assert anchors["large_offset_population_variance"] == "8.0"
    assert anchors["extreme_population_stddev"] == "1e+200"
    assert anchors["large_adjacent_population_stddev"] == "9.9792015476736e+291"
    assert anchors["large_adjacent_legacy_sample_sd"] == "1.4112722170374585e+292"
    assert anchors["tiny_adjacent_population_stddev"] != "0.0"
    assert anchors["tiny_legacy_sample_sd"] != "0.0"
    assert anchors["float64_adjacent_min"] == "16777216.0"
    assert anchors["float64_adjacent_max"] == "16777217.0"
