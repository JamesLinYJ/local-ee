"""Deterministic fixtures and independent expectations for Float64 tile tests."""
from __future__ import annotations

import json
import math
from typing import Any

from ee_float64_values_oracle import (
    MAX_FLOAT, MIN_SUBNORMAL, OPERATIONS, _band, _constant, _encode, canonical_spec, evaluate, reference,
)


def _case(name: str, operation: str, operands: list[dict[str, Any]],
          bands: list[list[float | int | None]], *, ulps: int = 0,
          input_type: str = "double") -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": name,
        "spec": canonical_spec(operation, operands),
        "input_type": input_type,
        "bands": [[_encode(value) for value in band] for band in bands],
        "tolerance_ulps": ulps,
    }
    row["expected"] = ["NaN" if value is None else _encode(value) for value in reference(row)]
    return row


def _binary_case(name: str, operation: str, left: list[float],
                 right: list[float], *, ulps: int = 0) -> dict[str, Any]:
    return _case(name, operation, [_band(0), _band(1)], [left, right], ulps=ulps)


def _unary_case(name: str, operation: str, values: list[float], *, ulps: int = 0,
                input_type: str = "double") -> dict[str, Any]:
    return _case(name, operation, [_band(0)], [values], ulps=ulps, input_type=input_type)


def _invalid_specs() -> list[str]:
    valid = canonical_spec("add", [_band(0), _band(1)])
    return [
        "", "{", "null", "[]", valid + " ", valid + " []",
        valid.replace("\"dtype\":null,", "\"extra\":0,\"dtype\":null,"),
        valid.replace("\"op\":\"add\"", "\"op\":\"unknown\""),
        canonical_spec("sin", [_band(0), _band(1)]),
        canonical_spec("add", [_band(0)]),
        canonical_spec("sqrt", [_band(0)], "int32"),
        canonical_spec("add", [{"constant": "7ff0000000000000"}, _band(0)]),
        canonical_spec("add", [{"constant": "7ff8000000000000"}, _band(0)]),
        canonical_spec("add", [{"constant": "ABCDEF0123456789"}, _band(0)]),
        canonical_spec("add", [{"constant": "000000000000000"}, _band(0)]),
        valid.replace("\"v\":1", "\"v\":1.0"),
        valid.replace("\"v\":1", "\"v\":2"),
        valid.replace("\"v\":1", "\"v\":true"),
        valid.replace("\"dtype\":null", "\"dtype\":null,\"dtype\":null"),
    ]


def _invalid_tile_cases() -> list[dict[str, Any]]:
    return [
        {
            "name": "source-positive-infinity-rejected",
            "spec": canonical_spec("add", [_band(0), _band(1)]),
            "input_type": "double",
            "bands": [["Infinity"], ["0x0.0p+0"]],
        },
        {
            "name": "source-negative-infinity-rejected",
            "spec": canonical_spec("add", [_band(0), _band(1)]),
            "input_type": "double",
            "bands": [["-Infinity"], ["0x0.0p+0"]],
        },
    ]


def _composites() -> dict[str, Any]:
    temperature = [-273.15, -40.0, 0.0, 21.5, 100.0, None]
    kelvin_spec = canonical_spec("add", [_band(0), _constant(273.15)])
    kelvin = [None if value is None else evaluate("add", [value, 273.15])
              for value in temperature]

    red = [0.2, 0.1, 0.6, -0.2, 1.0, 0.5, None, 0.3]
    nir = [0.6, 0.5, 0.2, 0.2, 1.0, -0.5, 0.9, None]
    ndvi_num = canonical_spec("subtract", [_band(1), _band(0)])
    ndvi_den = canonical_spec("add", [_band(1), _band(0)])
    ndvi_div = canonical_spec("divide", [_band(0), _band(1)])
    numerator: list[float | None] = []
    denominator: list[float | None] = []
    ndvi: list[float | None] = []
    for red_value, nir_value in zip(red, nir):
        if red_value is None or nir_value is None:
            numerator.append(None)
            denominator.append(None)
            ndvi.append(None)
        else:
            num = evaluate("subtract", [nir_value, red_value])
            den = evaluate("add", [nir_value, red_value])
            numerator.append(None if math.isnan(num) else num)
            denominator.append(None if math.isnan(den) else den)
            ratio = evaluate("divide", [num, den]) if not math.isnan(num) and not math.isnan(den) else math.nan
            ndvi.append(None if math.isnan(ratio) else ratio)

    qa = [0, 1, 2, 3, 7, 8, None]
    qa_mask_spec = canonical_spec("bit_and", [_band(0), _constant(3)])
    qa_arithmetic_spec = canonical_spec("add", [_band(0), _constant(0.25)])
    qa_masked = [None if value is None else float(int(value) & 3) for value in qa]
    qa_adjusted = [None if value is None else evaluate("add", [value, 0.25])
                   for value in qa_masked]

    def encoded(values: list[float | None]) -> list[str]:
        return ["NaN" if value is None else _encode(value) for value in values]

    return {
        "thermal_celsius_to_kelvin": {
            "raw_celsius": [_encode(value) for value in temperature],
            "spec": kelvin_spec,
            "expected_kelvin": encoded(kelvin),
        },
        "ndvi_float64": {
            "red": [_encode(value) for value in red],
            "nir": [_encode(value) for value in nir],
            "specs": {"numerator": ndvi_num, "denominator": ndvi_den, "divide": ndvi_div},
            "expected_numerator": encoded(numerator),
            "expected_denominator": encoded(denominator),
            "expected_ndvi": encoded(ndvi),
        },
        "qa_integer_result_arithmetic": {
            "raw_qa": [_encode(value) for value in qa],
            "integer_mask_spec": qa_mask_spec,
            "float_arithmetic_spec": qa_arithmetic_spec,
            "expected_masked": encoded(qa_masked),
            "expected_adjusted": encoded(qa_adjusted),
        },
    }


def make_fixture() -> dict[str, Any]:
    max_float = MAX_FLOAT
    minsub = MIN_SUBNORMAL
    two53 = float(1 << 53)
    next53 = math.nextafter(two53, math.inf)
    cases = [
        _binary_case("add-exact-cancellation-overflow-and-high-bits", "add",
                     [float((1 << 24) + 1), two53, next53, max_float, max_float,
                      minsub, -0.0, -max_float],
                     [0.0, 1.0, 0.0, max_float, -max_float, minsub, 0.0, max_float]),
        _binary_case("subtract-high-bits-signed-zero-and-overflow", "subtract",
                     [two53, next53, max_float, max_float, -0.0, -0.0, minsub],
                     [1.0, 0.0, -max_float, max_float, 0.0, -0.0, minsub]),
        _binary_case("multiply-overflow-underflow-and-signed-zero", "multiply",
                     [float((1 << 24) + 1), max_float, minsub, minsub, -0.0, -0.0, 1.5, -2.0],
                     [float((1 << 24) + 1), 2.0, 0.5, minsub, -3.0, 3.0, 2.0, 0.5]),
        _binary_case("divide-zero-policy-subnormal-and-overflow", "divide",
                     [1.0, 1.0, 0.0, -1.0, max_float, minsub, -0.0, two53],
                     [3.0, -0.0, 0.0, -0.0, minsub, 2.0, 3.0, 2.0]),
        _binary_case("power-integer-fractional-domain-and-extremes", "power",
                     [2.0, -2.0, -2.0, 1.0, 0.0, -0.0, 0.5, 10.0, 1.0001, 10.0],
                     [53.0, 3.0, 0.5, 1e308, 0.0, -3.0, 2.0, 308.0, 1e6, -308.0], ulps=4),
        _binary_case("mod-sign-zero-and-invalid-divisor", "mod",
                     [7.0, -7.0, 5.5, -5.5, minsub, -0.0, 7.0],
                     [3.0, 3.0, 2.0, -2.0, minsub, 3.0, 0.0]),
        _binary_case("minimum-signed-zero-and-extremes", "min2",
                     [-0.0, 0.0, minsub, -max_float, 2.0, max_float],
                     [0.0, -0.0, 0.0, max_float, 1.0, max_float]),
        _binary_case("maximum-signed-zero-and-extremes", "max2",
                     [-0.0, 0.0, minsub, -max_float, 2.0, max_float],
                     [0.0, -0.0, 0.0, max_float, 1.0, max_float]),
        _binary_case("and-subnormal-is-true", "and", [0.0, -0.0, minsub, -1.0, 1e-300],
                     [1.0, 1.0, 1.0, 2.0, 1.0]),
        _binary_case("or-subnormal-is-true", "or", [0.0, -0.0, minsub, 0.0, 1e-300],
                     [0.0, 0.0, 0.0, 1.0, 0.0]),
        _unary_case("absolute-negative-zero-and-high-bit", "absolute",
                    [-max_float, -0.0, minsub, -two53, -0.5, 0.0]),
        _unary_case("sqrt-domain-subnormal-and-maximum", "sqrt",
                    [-1.0, -0.0, minsub, 4.0, max_float], ulps=3),
        _unary_case("natural-log-domain-subnormal-and-maximum", "log",
                    [-1.0, -0.0, 0.0, minsub, 1.0, max_float], ulps=3),
        _unary_case("base-ten-log-domain-subnormal-and-maximum", "log10",
                    [-1.0, 0.0, minsub, 0.1, 10.0, max_float], ulps=4),
        _unary_case("exp-overflow-underflow-and-signed-zero", "exp",
                    [-1000.0, -745.0, -744.44, -0.0, 0.0, 1.0, 709.0, 709.78, 1000.0], ulps=4),
        _unary_case("round-ties-to-positive-infinity", "round",
                    [-2.5, -1.5, -0.5, -minsub, minsub, 0.5, 1.5, 2.5,
                     float((1 << 52) - 0.5), float(1 << 52), two53, float((1 << 24) + 1)]),
        _unary_case("floor-signed-zero-and-tiny-values", "floor",
                    [-0.0, -minsub, minsub, -1.2, 1.2, two53, max_float]),
        _unary_case("ceil-signed-zero-and-tiny-values", "ceil",
                    [-0.0, -minsub, minsub, -1.2, 1.2, two53, max_float]),
        _unary_case("sin-decimal-reference-large-negative", "sin",
                    [-1e12, -1234567.125, -20.0, -math.pi, -0.0, minsub,
                     0.3, 1.25, 20.0, 1e12], ulps=5),
        _unary_case("cos-decimal-reference-large-negative", "cos",
                    [-1e12, -1234567.125, -20.0, -math.pi, -0.0, minsub,
                     0.3, 1.25, 20.0, 1e12], ulps=5),
        _unary_case("tan-decimal-reference-large-negative", "tan",
                    [-1e12, -1234567.125, -20.0, -math.pi, -0.0, minsub,
                     0.3, 1.25, 20.0, 1e12], ulps=8),
        _unary_case("logical-not-subnormal-is-true", "not",
                    [0.0, -0.0, minsub, -minsub, -1.0, max_float]),
        _case("constant-multiply-precise-integer-source", "multiply",
              [_band(0), _constant(1.0)], [[float((1 << 24) + 1), -2147483648.0, 1.0]],
              input_type="int-sentinel-0"),
        _unary_case("integer-user-nodata-sentinel-preserves-int-min", "absolute",
                    [-2147483648.0, math.nan, 123.0], input_type="int-sentinel-0"),
        _unary_case("integer-constant-nodata-minimum-remains-masked", "absolute",
                    [math.nan, -123.0, 0.0], input_type="int-constant-nodata"),
    ]
    return {
        "schema": "local-ee-float64-values-synthetic/v1",
        "operations": list(OPERATIONS),
        "case_count": len(cases),
        "pixel_count": sum(len(row["expected"]) for row in cases),
        "cases": cases,
        "invalid_specs": _invalid_specs(),
        "invalid_tile_cases": _invalid_tile_cases(),
        "composites": _composites(),
    }
