"""Offline SDK signatures and independent references for static special math."""
import math
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import MAX_ARRAY_WORK, StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.static_special_math import (
    STATIC_SPECIAL_MATH_FUNCTIONS,
    invoke_static_special_math,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
_EULER = 0.5772156649015328606
_METHODS = ("digamma", "trigamma", "erfInv", "erfcInv")


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


def _invoke(name, value, translator=None):
    return invoke_static_special_math(
        translator or Translator([], {}, None), name, {"input": value},
    )


def _sdk_call(ee, name, method):
    if name.startswith("Number."):
        encoded = ee.serializer.encode(
            getattr(ee.Number(0.5), method)(), for_cloud_api=False,
        )
        assert encoded["functionName"] == name
        return encoded, encoded
    encoded = ee.serializer.encode(
        getattr(ee.Array([0.5, 0.75]), method)(), for_cloud_api=False,
    )
    calls = [node for _, node in encoded["scope"]
             if isinstance(node, dict) and node.get("type") == "Invocation"
             and node.get("functionName") == name]
    assert len(calls) == 1
    return encoded, calls[0]


@pytest.mark.parametrize("method", _METHODS)
@pytest.mark.parametrize("kind", ("Number", "Array"))
def test_official_sdk_pins_and_serializes_all_eight_names(ee, method, kind):
    name = f"{kind}.{method}"
    assert name in STATIC_SPECIAL_MATH_FUNCTIONS
    signature = ee.ApiFunction.lookup(name).getSignature()
    assert signature["name"] == name
    assert [argument["name"] for argument in signature["args"]] == ["input"]
    encoded, call = _sdk_call(ee, name, method)
    assert call["functionName"] == name
    assert set(call["arguments"]) == {"input"}
    compiled = compile_expression(encoded, [], {})
    assert compiled["kind"] == "value"
    value = compiled["value"]
    if kind == "Number":
        assert math.isfinite(value)
    else:
        expected = _invoke(
            name, StaticArray(np.array([0.5, 0.75], dtype=np.float64)),
        )
        assert isinstance(value, list)
        np.testing.assert_array_equal(value, expected.to_value())


@pytest.mark.parametrize("operation", ("digamma", "trigamma"))
def test_gamma_derivatives_match_closed_forms_and_reflection_values(operation):
    if operation == "digamma":
        references = {
            1.0: -_EULER,
            0.5: -_EULER - 2.0 * math.log(2.0),
            -0.5: 2.0 - _EULER - 2.0 * math.log(2.0),
            2.0: 1.0 - _EULER,
        }
    else:
        references = {
            1.0: math.pi**2 / 6.0,
            0.5: math.pi**2 / 2.0,
            -0.5: math.pi**2 / 2.0 + 4.0,
            2.0: math.pi**2 / 6.0 - 1.0,
        }
    for value, expected in references.items():
        assert _invoke(f"Number.{operation}", value) == pytest.approx(
            expected, rel=2e-14, abs=2e-14,
        )

    array = _invoke(
        f"Array.{operation}", StaticArray(np.array(list(references))),
    )
    np.testing.assert_allclose(
        array.data, list(references.values()), rtol=2e-14, atol=2e-14,
    )
    assert array.data.dtype == np.float64
    assert not array.data.flags.writeable


def test_inverse_error_functions_match_known_values_and_resolve_extreme_tails():
    inverse_half = 0.4769362762044699
    assert _invoke("Number.erfInv", 0.5) == pytest.approx(
        inverse_half, rel=2e-15, abs=2e-15,
    )
    assert _invoke("Number.erfcInv", 0.5) == pytest.approx(
        inverse_half, rel=2e-15, abs=2e-15,
    )
    assert _invoke("Number.erfcInv", 1.5) == pytest.approx(
        -inverse_half, rel=2e-15, abs=2e-15,
    )

    near_one = math.nextafter(1.0, 0.0)
    erf_tail = _invoke("Number.erfInv", near_one)
    assert erf_tail == pytest.approx(5.8635847487551676, abs=2e-14)
    assert math.erf(erf_tail) == near_one

    smallest = math.nextafter(0.0, 1.0)
    erfc_tail = _invoke("Number.erfcInv", smallest)
    assert math.isfinite(erfc_tail) and 27.0 < erfc_tail < 28.0
    assert erfc_tail == pytest.approx(27.2132932108129488, abs=4e-15)

    near_two = math.nextafter(2.0, 0.0)
    negative_tail = _invoke("Number.erfcInv", near_two)
    assert negative_tail == pytest.approx(-5.8050186831934487, abs=5e-15)

    near_one = math.nextafter(1.0, 0.0)
    erfc_center = _invoke("Number.erfcInv", near_one)
    assert erfc_center == pytest.approx(
        math.sqrt(math.pi) * (1.0 - near_one) / 2.0, rel=2e-14,
    )
    assert math.erfc(erfc_center) == near_one


@pytest.mark.parametrize("value", [
    1e-100, -1e-100, 1e-300, -1e-300,
    math.nextafter(0.0, 1.0), math.nextafter(0.0, -1.0),
])
def test_erf_inverse_resolves_tiny_signed_inputs(value):
    result = _invoke("Number.erfInv", value)
    assert result == value * (math.sqrt(math.pi) / 2.0)
    assert math.erf(result) == pytest.approx(value, rel=1e-15, abs=0.0)


@pytest.mark.parametrize("name,value", [
    ("Number.digamma", 0.0), ("Number.digamma", -1.0),
    ("Number.trigamma", -2.0),
    ("Number.erfInv", -1.0), ("Number.erfInv", 1.0),
    ("Number.erfcInv", 0.0), ("Number.erfcInv", 2.0),
    ("Number.erfcInv", -0.1), ("Number.erfInv", 1.1),
])
def test_poles_and_inverse_endpoints_reject(name, value):
    with pytest.raises(UnsupportedEEError):
        _invoke(name, value)


@pytest.mark.parametrize("bad", [
    True, None, "0.5", [], {}, float("nan"), float("inf"),
    float("-inf"), 2**53 + 1, -(2**53 + 1),
])
def test_number_requires_a_finite_exact_static_float64_value(bad):
    with pytest.raises(UnsupportedEEError, match="static Number"):
        _invoke("Number.digamma", bad)


def test_static_array_preserves_shape_uses_float64_and_accepts_typed_empty():
    source = np.array([[0.5, 1.0], [-0.5, 2.0]], dtype=np.float32)
    value = StaticArray(source)
    result = _invoke("Array.digamma", value)
    assert result.data.shape == source.shape
    assert result.data.dtype == np.float64
    assert not np.shares_memory(result.data, source)
    assert not result.data.flags.writeable

    empty = StaticArray(np.empty((0, 3), dtype=np.float32))
    empty_result = _invoke("Array.erfcInv", empty)
    assert empty_result.data.shape == (0, 3)
    assert empty_result.data.dtype == np.float64
    assert not empty_result.data.flags.writeable


@pytest.mark.parametrize("array", [
    np.array([True]), np.array([float("nan")]), np.array([float("inf")]),
    np.array([2**53 + 1], dtype=np.uint64), np.array([1, 2], dtype=object),
])
def test_static_array_rejects_non_real_nonfinite_or_inexact_values(array):
    with pytest.raises(UnsupportedEEError):
        _invoke("Array.digamma", StaticArray(array))


def test_array_domain_errors_apply_to_every_cell():
    for name, values in (
        ("Array.digamma", [1.0, -1.0]),
        ("Array.trigamma", [1.0, 0.0]),
        ("Array.erfInv", [0.5, 1.0]),
        ("Array.erfcInv", [0.5, 0.0]),
    ):
        with pytest.raises(UnsupportedEEError):
            _invoke(name, StaticArray(np.asarray(values)))


def test_work_is_precharged_before_array_scans_or_output_allocation(monkeypatch):
    translator = Translator([], {}, None)
    large = StaticArray(np.full(1_563, np.nan))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("array was scanned or allocated before work preflight")

    monkeypatch.setattr(
        "gee.compat.earthengine.static_special_math._validate_array", forbidden,
    )
    monkeypatch.setattr(
        "gee.compat.earthengine.static_special_math.np.empty", forbidden,
    )
    with pytest.raises(UnsupportedEEError, match="work budget"):
        _invoke("Array.digamma", large, translator)
    assert translator.steps == 0

    at_limit = Translator([], {}, None)
    at_limit.steps = MAX_ARRAY_WORK - 33
    assert math.isfinite(_invoke("Number.trigamma", 1.0, at_limit))
    assert at_limit.steps == MAX_ARRAY_WORK


@pytest.mark.parametrize("value", [
    math.nextafter(1.0, 0.0), math.nextafter(1.0, 2.0),
    1.0 - 2**-40, 1.0 + 2**-40,
])
def test_erfc_inverse_tiny_roots_keep_relative_precision_in_official_sdk(ee, value):
    # From the inverse-function derivative at erfc(0)=1. The cubic correction
    # is <1e-24 relative on these exact binary distances, below Float64 error.
    expected = (1.0 - value) * math.sqrt(math.pi) / 2.0
    expression = ee.serializer.encode(ee.Number(value).erfcInv(), for_cloud_api=False)
    actual = compile_expression(expression, [], {})["value"]
    assert actual == pytest.approx(expected, rel=2e-15, abs=0.0)


def test_array_erfc_inverse_tiny_roots_preserve_both_signs():
    values = np.asarray([math.nextafter(1.0, 0.0), math.nextafter(1.0, 2.0)])
    actual = _invoke("Array.erfcInv", StaticArray(values))
    expected = (1.0 - values) * math.sqrt(math.pi) / 2.0
    np.testing.assert_allclose(actual.data, expected, rtol=2e-15, atol=0)
