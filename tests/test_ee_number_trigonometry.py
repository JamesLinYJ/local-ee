"""Pinned scalar trigonometry and an independent rational-series reference."""
from fractions import Fraction
import math
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.static_values import invoke_static
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def compile_value(ee, expression):
    result = compile_expression(
        ee.serializer.encode(expression, for_cloud_api=False), [], {},
    )
    assert result["kind"] == "value"
    return result["value"]


def rational_series(value, cosine):
    """25 terms have truncation error below 4e-50 for |value|<=2."""
    x = Fraction(value)
    first_power = 0 if cosine else 1
    return float(sum(
        ((-1) ** index * x ** (2 * index + first_power)
         / math.factorial(2 * index + first_power) for index in range(25)),
        Fraction(0),
    ))


@pytest.mark.parametrize("value", [-2, -1.25, -1 / 3, 0, 1 / 3, 1.25, 2])
def test_sdk_sin_cos_match_an_independent_rational_series_in_radians(ee, value):
    actual = compile_value(ee, ee.List([ee.Number(value).sin(), ee.Number(value).cos()]))
    expected = [rational_series(value, False), rational_series(value, True)]
    np.testing.assert_allclose(actual, expected, atol=3e-16, rtol=3e-16)


def test_sdk_quadrants_and_signed_zero(ee):
    values = ee.List([0, math.pi / 2, math.pi, 3 * math.pi / 2, 2 * math.pi])
    pairs = values.map(lambda value: ee.List([ee.Number(value).sin(), ee.Number(value).cos()]))
    actual = compile_value(ee, pairs)
    np.testing.assert_allclose(actual, [[0, 1], [1, 0], [0, -1], [-1, 0], [0, 1]], atol=1e-15)
    sine, cosine = compile_value(ee, ee.List([ee.Number(-0.0).sin(), ee.Number(-0.0).cos()]))
    assert sine == 0 and math.copysign(1, sine) == -1
    assert cosine == 1


def test_list_callback_constructs_a_numeric_design_matrix(ee):
    rows = ee.List([0, math.pi / 2, math.pi]).map(
        lambda angle: ee.List([1, ee.Number(angle).cos(), ee.Number(angle).sin()])
    )
    actual = compile_value(ee, ee.Array(rows).matrixTranspose())
    np.testing.assert_allclose(actual, [[1, 1, 1], [1, 0, -1], [0, 1, 0]], atol=1e-15)


@pytest.mark.parametrize("operation", ["sin", "cos"])
@pytest.mark.parametrize("value", [None, True, "1", [], {}, float("nan"), float("inf"),
                                   float("-inf"), 2 ** 53 + 1, -(2 ** 53 + 1)])
def test_non_numeric_nonfinite_or_inexact_integer_inputs_reject(operation, value):
    with pytest.raises(UnsupportedEEError):
        invoke_static(Translator([], {}, {}), "Number." + operation, {"input": value})


@pytest.mark.parametrize("operation", ["sin", "cos"])
def test_signature_parameters_are_required_and_unknown_arguments_reject(ee, operation):
    for arguments in ({}, {"left": 1}, {"input": 1, "ignored": True}):
        with pytest.raises(UnsupportedEEError):
            compile_expression({"type": "Invocation", "functionName": "Number." + operation,
                                "arguments": arguments}, [], {})
    # The SDK emits the actual fixed signature's input argument.
    encoded = ee.serializer.encode(getattr(ee.Number(1), operation)(), for_cloud_api=False)
    nodes = [node for _, node in encoded["scope"]] if "scope" in encoded else [encoded]
    calls = [node for node in nodes
             if isinstance(node, dict) and node.get("functionName") == "Number." + operation]
    assert len(calls) == 1 and set(calls[0]["arguments"]) == {"input"}


@pytest.mark.parametrize("operation", ["sin", "cos"])
def test_work_budget_rejects_before_the_libm_call(monkeypatch, operation):
    def should_not_run(_value):
        raise AssertionError("libm ran before shared-work preflight")

    translator = Translator([], {}, {})
    translator.steps = 50_000
    monkeypatch.setattr(math, operation, should_not_run)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_static(translator, "Number." + operation, {"input": 1})
    assert translator.steps == 50_000
