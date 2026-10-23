"""Pinned Number.expression serialization and bounded finite scalar semantics."""
import math
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.number_expression import invoke_number_expression
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
_MISSING = object()


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def invoke(text, variables=_MISSING, *, translator=None):
    arguments = {"expression": text}
    if variables is not _MISSING:
        arguments["vars"] = variables
    return invoke_number_expression(
        translator or Translator([], {}, {}), "Number.expression", arguments,
    )


def sdk_value(ee, text, variables=_MISSING):
    number = (ee.Number.expression(text) if variables is _MISSING
              else ee.Number.expression(text, variables))
    encoded = ee.serializer.encode(number, for_cloud_api=False)
    result = compile_expression(encoded, [], {})
    assert result["kind"] == "value"
    return result["value"]


def test_official_sdk_serializes_expression_and_optional_vars(ee):
    assert ee.serializer.encode(
        ee.Number.expression("Math.PI"), for_cloud_api=False,
    ) == {
        "type": "Invocation", "arguments": {"expression": "Math.PI"},
        "functionName": "Number.expression",
    }
    encoded = ee.serializer.encode(
        ee.Number.expression("x + y", {"x": 5, "y": 10}), for_cloud_api=False,
    )
    assert encoded["type"] == "CompoundValue"
    invocation = encoded["scope"][-1][1]
    assert invocation["functionName"] == "Number.expression"
    assert invocation["arguments"]["expression"] == "x + y"
    assert "vars" in invocation["arguments"]
    assert sdk_value(ee, "x + y", {"x": 5, "y": 10}) == 15


@pytest.mark.parametrize(("text", "expected"), [
    ("10 + 3 * 4", 22), ("(10 + 3) * 4", 52),
    ("2 ** 3 ** 2", 512), ("-2 ** 2", -4), ("2 ** -2", 0.25),
    ("10 / 20", 0), ("10 * 1.0 / 20", 0.5),
    ("-5 / 2", -3), ("-12 % 5", -2), ("12 % -5", 2),
    ("10 / 0", 0), ("Math.PI", math.pi), ("Math.E", math.e),
    ("!(0)", 1), ("(2 > 1) && (3 <= 3)", 1),
    ("(2 < 1) || (3 == 3)", 1), ("(2 < 1) ^ (3 == 3)", 1),
    ("(2 < 1) ? 10 : (3 < 4 ? 20 : 30)", 20),
])
def test_bounded_expression_operators_precedence_and_constants(ee, text, expected):
    assert sdk_value(ee, text) == pytest.approx(expected)


def test_nested_dictionary_variables_and_documented_number_functions(ee):
    variables = {"x": 5, "y": 10, "vals": {"x": 2, "y": 3}}
    assert sdk_value(ee, "add(x, y) + vals.x * vals.y", variables) == 21
    assert sdk_value(ee, "subtract(add(x, y), 5)", variables) == 10
    assert sdk_value(ee, "sqrt(pow(3, 2) + pow(4, 2))", variables) == 5
    assert sdk_value(ee, "max(x, y) + clamp(12, 0, 10)", variables) == 20
    assert sdk_value(ee, "sin(asin(0.4))", variables) == pytest.approx(0.4)


def test_independent_numeric_controls_cover_exact_integer_and_fractional_paths():
    assert invoke("9007199254740992 - 1") == 2**53 - 1
    assert invoke("2 ** 53") == 2**53
    assert invoke("3 ** 33") == 3**33
    assert invoke("round(4503599627370497)") == 2**52 + 1
    assert invoke("round(9007199254740991)") == 2**53 - 1
    assert invoke("round(-4503599627370497.0)") == -(2**52 + 1)
    assert invoke("atan2(1, 1)") == pytest.approx(math.pi / 4)
    assert invoke("hypot(3, 4)") == 5
    assert invoke("1.25 % 0.5") == pytest.approx(0.25)
    assert invoke("unitScale(5, 1, 3)") == 2


def test_expression_short_circuits_values_but_prevalidates_every_branch():
    assert invoke("0 && (1 % 0)") == 0
    assert invoke("1 || sqrt(-1)") == 1
    assert invoke("1 ? 4 : (1 % 0)") == 4
    for expression in ("1 ? 4 : unknown", "1 ? 4 : ignoredFunction(1)",
                       "0 && missing", "1 ? 1 : add(1)"):
        with pytest.raises(UnsupportedEEError):
            invoke(expression)


@pytest.mark.parametrize("expression", [
    "", "x = 1", "[1, 2]", "'text'", '"text"', "b(0)",
    "x[0]", "Math.sqrt(4)", "Math.foo", "x.__class__", "1; 2",
    "1 << 2", "1 >>> 2", "this.x", "x(1)", "sqrt()", "add(1, 2, 3)",
    "unknown(1)", "__import__(1)",
])
def test_unsupported_syntax_access_strings_arrays_and_functions_reject(expression):
    with pytest.raises(UnsupportedEEError):
        invoke(expression, {"x": {"constructor": 1}})


@pytest.mark.parametrize("variables", [
    {"unused": "text"}, {"unused": [1, 2]}, {"unused": True},
    {"unused": None}, {"unused": float("nan")}, {"unused": float("inf")},
    {"unused": 2**53 + 1}, {"bad-key": 1}, None,
])
def test_all_vars_values_are_validated_even_when_unused(variables):
    if variables is None:
        # Null is the documented default vars value.
        assert invoke("2 + 3", variables) == 5
    else:
        with pytest.raises(UnsupportedEEError):
            invoke("2 + 3", variables)


def test_nested_dictionary_paths_are_plain_data_lookup_and_cycles_reject():
    assert invoke("group.value + 1", {"group": {"value": 4}}) == 5
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(UnsupportedEEError, match="cycle"):
        invoke("1", {"unused": cyclic})
    with pytest.raises(UnsupportedEEError, match="Unknown"):
        invoke("group.missing", {"group": {"value": 4}})


def test_variable_depth_and_key_lengths_are_preflighted():
    nested = 1
    for _ in range(34):
        nested = {"child": nested}
    with pytest.raises(UnsupportedEEError, match="nesting exceeds 32"):
        invoke("1", {"unused": nested})
    with pytest.raises(UnsupportedEEError, match="64 characters"):
        invoke("1", {"x" * 65: 1})


def test_variable_key_work_is_reserved_before_key_validation(monkeypatch):
    class UnexpectedKeyValidation:
        def fullmatch(self, _key):
            raise AssertionError("key regex ran before total key work was reserved")

    variables = {
        f"k{index:04d}" + "x" * 59: 1
        for index in range(800)
    }
    monkeypatch.setattr(
        "gee.compat.earthengine.number_expression_values._NAME",
        UnexpectedKeyValidation(),
    )
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke("1", variables)


@pytest.mark.parametrize("expression", [
    "9007199254740992 + 1", "1e308 * 2", "1e9999", "1 % 0",
    "3 ** 34", "(-1) ** 0.5", "0 ** -1", "sqrt(-1)", "log(0)",
])
def test_nonfinite_or_out_of_domain_results_reject(expression):
    with pytest.raises(UnsupportedEEError):
        invoke(expression)


def test_shared_work_budget_is_reserved_before_tree_evaluation(monkeypatch):
    translator = Translator([], {}, {})
    translator.steps = 49_999

    def should_not_parse(_parser):
        raise AssertionError("expression parsed before shared budget precharge")

    monkeypatch.setattr(
        "gee.compat.earthengine.number_expression_parser.NumberExpressionParser.parse",
        should_not_parse,
    )
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke("1 + 2", translator=translator)
    assert translator.steps == 49_999

    translator.steps = 0
    with pytest.raises(UnsupportedEEError, match="20000 characters"):
        invoke("1" * 20_001, translator=translator)
    assert translator.steps == 0


def test_token_and_expression_depth_limits_are_bounded():
    with pytest.raises(UnsupportedEEError, match="4000 tokens"):
        invoke(" + ".join(["1"] * 2_001))
    with pytest.raises(UnsupportedEEError, match="nesting exceeds 64"):
        invoke("(" * 65 + "1" + ")" * 65)
    with pytest.raises(UnsupportedEEError, match="nesting exceeds 64"):
        invoke(" + ".join(["1"] * 66))
