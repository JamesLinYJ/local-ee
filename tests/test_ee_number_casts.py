"""Pinned Earth Engine Number cast signatures and finite scalar semantics."""
import json
import math
from pathlib import Path

import pytest

from gee.compat.earthengine import number_casts
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Collection, Image, Source, UnsupportedEEError
from gee.compat.earthengine.static_values import invoke_static
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]

_INTEGER_CASTS = (
    ("Number.toByte", 0, 255, 0), ("Number.byte", 0, 255, 0),
    ("Number.toUint8", 0, 255, 0), ("Number.uint8", 0, 255, 0),
    ("Number.toInt8", -128, 127, -1), ("Number.int8", -128, 127, -1),
    ("Number.toInt16", -32768, 32767, -1), ("Number.int16", -32768, 32767, -1),
    ("Number.toShort", -32768, 32767, -1), ("Number.short", -32768, 32767, -1),
    ("Number.toInt32", -(2**31), 2**31 - 1, -1),
    ("Number.int32", -(2**31), 2**31 - 1, -1),
    ("Number.toUint16", 0, 65535, 0), ("Number.uint16", 0, 65535, 0),
    ("Number.toUint32", 0, 2**32 - 1, 0), ("Number.uint32", 0, 2**32 - 1, 0),
    ("Number.toInt64", -(2**63), 2**63 - 1, -1),
    ("Number.int64", -(2**63), 2**63 - 1, -1),
    ("Number.toLong", -(2**63), 2**63 - 1, -1),
    ("Number.long", -(2**63), 2**63 - 1, -1),
)
_SDK_METHODS = tuple(name.split(".", 1)[1] for name, *_ in _INTEGER_CASTS) + (
    "toFloat", "float", "toDouble", "double",
)


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


def invoke(name, value, *, translator=None):
    return number_casts.invoke_number_cast(
        translator or Translator([], {}, {}), name, {"input": value},
    )


def test_function_set_and_official_sdk_serialization_match_all_pinned_signatures(ee):
    document = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())
    signatures = {
        item["name"].removeprefix("algorithms/"): item
        for item in document["algorithms"]
        if item["name"].removeprefix("algorithms/") in number_casts.NUMBER_CAST_FUNCTIONS
    }
    assert number_casts.NUMBER_CAST_FUNCTIONS == frozenset(signatures)
    assert set(signatures) == {"Number." + method for method in _SDK_METHODS}

    for method in _SDK_METHODS:
        name = "Number." + method
        signature = signatures[name]
        assert signature["returnType"] == "Number"
        assert [arg["argumentName"] for arg in signature["arguments"]] == ["input"]
        expression = getattr(ee.Number(1.75), method)()
        encoded = ee.serializer.encode(expression, for_cloud_api=False)
        assert encoded == {
            "type": "Invocation", "arguments": {"input": 1.75}, "functionName": name,
        }
        expected = 1.75 if method in {"toFloat", "float", "toDouble", "double"} else 1
        assert compile_expression(encoded, [], {})["value"] == expected


@pytest.mark.parametrize(("name", "minimum", "maximum", "negative_fraction"), _INTEGER_CASTS)
def test_integer_casts_truncate_and_clamp_at_documented_type_edges(
    name, minimum, maximum, negative_fraction,
):
    if minimum < -(2**53) or maximum > 2**53:
        # Int64 saturation endpoints are outside the local exact Number domain.
        assert invoke(name, 1.9) == 1
        assert invoke(name, -1.9) == -1
        assert invoke(name, 2**53) == 2**53
        assert invoke(name, -(2**53)) == -(2**53)
        with pytest.raises(UnsupportedEEError, match="exact Float64 integer domain"):
            invoke(name, float(2**53 + 2))
        return
    assert invoke(name, 1.9) == 1
    assert invoke(name, -1.9) == negative_fraction
    assert invoke(name, minimum) == minimum
    assert invoke(name, maximum) == maximum
    # Fractions just beyond an edge still truncate to that edge.
    assert invoke(name, minimum - 0.75) == minimum
    assert invoke(name, maximum + 0.75) == maximum
    assert invoke(name, minimum - 1) == minimum
    assert invoke(name, maximum + 1) == maximum


def test_int64_family_stays_inside_the_repo_exact_integer_domain():
    for name in ("Number.toInt64", "Number.int64", "Number.toLong", "Number.long"):
        assert invoke(name, 2**53) == 2**53
        assert invoke(name, -(2**53)) == -(2**53)
        with pytest.raises(UnsupportedEEError, match="exact Float64 integer domain"):
            invoke(name, float(2**53 + 2))


def test_float32_uses_ieee_rounding_preserves_signed_underflow_and_rejects_overflow():
    for name in ("Number.toFloat", "Number.float"):
        assert invoke(name, 16777217) == 16777216.0
        # These are exact Float64 midpoints; ties round to an even Float32 significand.
        assert invoke(name, 1.0 + 2**-24) == 1.0
        assert invoke(name, 1.0 + 3 * 2**-24) == 1.0 + 2**-22
        underflow = invoke(name, -1e-100)
        assert underflow == 0.0 and math.copysign(1.0, underflow) == -1.0
        with pytest.raises(UnsupportedEEError, match="finite Float32"):
            invoke(name, 3.5e38)


def test_float64_aliases_preserve_float64_values_and_exact_boundary():
    for name in ("Number.toDouble", "Number.double"):
        assert invoke(name, 2**53) == float(2**53)
        assert invoke(name, 0.1) == 0.1
        assert invoke(name, 1e308) == 1e308
        value = invoke(name, -0.0)
        assert value == 0.0 and math.copysign(1.0, value) == -1.0


@pytest.mark.parametrize("value", [
    None, True, "1", [], {}, object(), float("nan"), float("inf"), float("-inf"),
    2**53 + 1, -(2**53 + 1), Image([], {}),
    Collection(Source("x", ("x",), ("x",)), Image([], {})),
])
def test_dynamic_non_numeric_nonfinite_and_inexact_integer_inputs_reject(value):
    with pytest.raises(UnsupportedEEError):
        invoke("Number.toInt16", value)


@pytest.mark.parametrize("arguments", [{}, {"left": 1}, {"input": 1, "extra": 2}])
def test_missing_and_extra_cast_arguments_reject(arguments):
    with pytest.raises(UnsupportedEEError):
        number_casts.invoke_number_cast(
            Translator([], {}, {}), "Number.toInt16", arguments,
        )


def test_budget_is_charged_before_conversion(monkeypatch):
    def should_not_run(*_arguments):
        raise AssertionError("cast conversion ran before shared-work preflight")

    translator = Translator([], {}, {})
    translator.steps = 50_000
    monkeypatch.setattr(number_casts, "_cast", should_not_run)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        number_casts.invoke_number_cast(translator, "Number.toFloat", {"input": 1.5})
    assert translator.steps == 50_000

    monkeypatch.undo()
    translator.steps = 49_999
    assert number_casts.invoke_number_cast(translator, "Number.toByte", {"input": 2}) == 2
    assert translator.steps == 50_000


def test_existing_to_int_and_int_keep_their_previous_static_behavior():
    for name in ("Number.toInt", "Number.int"):
        assert invoke_static(Translator([], {}, {}), name, {"input": -1.9}) == -1
        assert invoke_static(Translator([], {}, {}), name, {"input": 2**31 + 1}) == 2**31 + 1
