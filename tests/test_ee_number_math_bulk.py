"""Pinned scalar Number operators with independent finite references."""
import math
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.number_math import invoke_number_math
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


def sdk_value(ee, name, arguments):
    expression = ee.ApiFunction.apply_(name, arguments)
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    assert encoded["functionName"] == name
    assert encoded["arguments"] == arguments
    result = compile_expression(encoded, [], {})
    assert result["kind"] == "value"
    return result["value"]


@pytest.mark.parametrize(("name", "arguments", "expected"), [
    ("Number.tan", {"input": math.pi / 4}, 1.0),
    ("Number.asin", {"input": 0.5}, math.pi / 6),
    ("Number.acos", {"input": 0.5}, math.pi / 3),
    ("Number.atan", {"input": 1.0}, math.pi / 4),
    ("Number.sinh", {"input": 0.75}, (math.exp(0.75) - math.exp(-0.75)) / 2),
    ("Number.cosh", {"input": 0.75}, (math.exp(0.75) + math.exp(-0.75)) / 2),
    ("Number.tanh", {"input": 0.75}, math.tanh(0.75)),
    ("Number.log", {"input": 8.0}, math.log(8.0)),
    ("Number.log10", {"input": 1000.0}, 3.0),
    ("Number.exp", {"input": 0.0}, 1.0),
    ("Number.cbrt", {"input": -27.0}, -3.0),
    ("Number.signum", {"input": -0.0}, 0.0),
    ("Number.signum", {"input": -3.0}, -1.0),
    ("Number.erf", {"input": 1.0}, 0.8427007929497149),
    ("Number.erfc", {"input": 1.0}, 0.15729920705028513),
    ("Number.gamma", {"input": 0.5}, math.sqrt(math.pi)),
    ("Number.gamma", {"input": 5.0}, 24.0),
    ("Number.not", {"input": 0.0}, 1.0),
    ("Number.not", {"input": -2.0}, 0.0),
    ("Number.min", {"left": 4.0, "right": -2.0}, -2.0),
    ("Number.max", {"left": 4.0, "right": -2.0}, 4.0),
    ("Number.first", {"left": 4.0, "right": -2.0}, 4.0),
    ("Number.firstNonZero", {"left": 0.0, "right": -2.0}, -2.0),
    ("Number.first_nonzero", {"left": 0.0, "right": 7.0}, 7.0),
    ("Number.and", {"left": -1.0, "right": 2.0}, 1.0),
    ("Number.and", {"left": 0.0, "right": 2.0}, 0.0),
    ("Number.or", {"left": 0.0, "right": -2.0}, 1.0),
    ("Number.or", {"left": 0.0, "right": 0.0}, 0.0),
    ("Number.clamp", {"number": -4.0, "min": -2.0, "max": 3.0}, -2.0),
    ("Number.clamp", {"number": 4.0, "min": -2.0, "max": 3.0}, 3.0),
    ("Number.unitScale", {"number": 5.0, "min": 1.0, "max": 3.0}, 2.0),
    ("Number.unitScale", {"number": 9.0, "min": 4.0, "max": 4.0}, 0.0),
])
def test_pinned_sdk_number_operators_have_finite_static_results(ee, name, arguments, expected):
    actual = sdk_value(ee, name, arguments)
    assert actual == pytest.approx(expected, rel=3e-15, abs=3e-15)


def test_independent_composition_identities(ee):
    values = ee.List([
        ee.Number(0.4).asin().sin(),
        ee.Number(0.4).acos().cos(),
        ee.Number(1.7).log().exp(),
        ee.Number(3).log10(),
        ee.Number(0.7).sinh().divide(ee.Number(0.7).cosh()),
        ee.Number(1).erf().add(ee.Number(1).erfc()),
        ee.Number(-0.5).gamma(),
    ])
    actual = compile_expression(ee.serializer.encode(values, for_cloud_api=False), [], {})["value"]
    assert actual[:5] == pytest.approx([0.4, 0.4, 1.7, math.log10(3), math.tanh(0.7)], rel=2e-14)
    assert actual[5] == pytest.approx(1.0, abs=2e-16)
    assert actual[6] == pytest.approx(-2 * math.sqrt(math.pi), rel=2e-15)


@pytest.mark.parametrize(("name", "arguments"), [
    ("Number.asin", {"input": 1.0001}),
    ("Number.acos", {"input": -1.0001}),
    ("Number.log", {"input": 0.0}),
    ("Number.log10", {"input": -1.0}),
    ("Number.exp", {"input": 1000.0}),
    ("Number.sinh", {"input": 1000.0}),
    ("Number.cosh", {"input": 1000.0}),
    ("Number.gamma", {"input": 0.0}),
    ("Number.gamma", {"input": -2.0}),
    ("Number.unitScale", {"number": 1e308, "min": 0.0, "max": 5e-324}),
    ("Number.clamp", {"number": 1.0, "min": 2.0, "max": 1.0}),
])
def test_invalid_domains_and_nonfinite_results_reject(name, arguments):
    with pytest.raises(UnsupportedEEError):
        invoke_number_math(Translator([], {}, {}), name, arguments)


@pytest.mark.parametrize("bad", [None, True, "1", [], {}, float("nan"), float("inf"),
                                  float("-inf"), 2**53 + 1, -(2**53 + 1)])
def test_all_operands_must_be_finite_exact_static_numbers(bad):
    for name, arguments in (
        ("Number.sin", {"input": bad}),
        ("Number.first", {"left": 1, "right": bad}),
        ("Number.firstNonZero", {"left": 1, "right": bad}),
        ("Number.and", {"left": 0, "right": bad}),
        ("Number.clamp", {"number": 0, "min": 0, "max": bad}),
    ):
        with pytest.raises(UnsupportedEEError):
            invoke_number_math(Translator([], {}, {}), name, arguments)


def test_required_arguments_unknown_arguments_and_ignored_operands_are_checked():
    translator = Translator([], {}, {})
    for name, arguments in (
        ("Number.tan", {}),
        ("Number.min", {"left": 1}),
        ("Number.clamp", {"number": 1, "min": 0}),
        ("Number.exp", {"input": 1, "ignored": 0}),
        ("Number.first", {"left": 1, "right": object()}),
        ("Number.firstNonZero", {"left": 1, "right": object()}),
        ("Number.and", {"left": 0, "right": object()}),
    ):
        with pytest.raises(UnsupportedEEError):
            invoke_number_math(translator, name, arguments)


def test_exact_integer_boundary_and_overflow_safe_unit_scale():
    translator = Translator([], {}, {})
    assert invoke_number_math(translator, "Number.first", {"left": 2**53, "right": -2**53}) == float(2**53)
    assert invoke_number_math(translator, "Number.unitScale", {
        "number": 0.0, "min": -1e308, "max": 1e308,
    }) == 0.5


def test_work_budget_is_precharged_before_scalar_computation(monkeypatch):
    def should_not_run(_value):
        raise AssertionError("math kernel ran before shared-work preflight")

    translator = Translator([], {}, {})
    translator.steps = 50_000
    monkeypatch.setattr(math, "gamma", should_not_run)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_number_math(translator, "Number.gamma", {"input": 1.0})
    assert translator.steps == 50_000

    # Check all operands before budget accounting, even when first ignores right.
    with pytest.raises(UnsupportedEEError, match="finite static numeric"):
        invoke_number_math(translator, "Number.first", {"left": 1, "right": object()})
