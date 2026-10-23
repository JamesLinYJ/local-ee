"""Focused contract and trusted-handler checks for Wave34 pixel math."""
from __future__ import annotations

from pathlib import Path

import pytest

from gee.pixel_math_contract import (
    PIXEL_MATH_ARITIES,
    PIXEL_MATH_OPERATIONS,
    pixel_math_arity,
    validate_pixel_math_arity,
    validate_pixel_math_operation,
)
from ee_sampling_bridge_helpers import _dry_cube, _metadata


def test_pixel_math_contract_is_closed_and_has_expected_arities():
    unary = {
        "asin", "acos", "atan", "sinh", "cosh", "tanh", "cbrt", "signum",
        "gamma", "digamma", "trigamma", "erf", "erfc", "erfInv", "erfcInv",
    }
    assert set(PIXEL_MATH_ARITIES) == unary | {"atan2"}
    assert PIXEL_MATH_OPERATIONS == tuple(PIXEL_MATH_ARITIES)
    assert {name for name, arity in PIXEL_MATH_ARITIES.items() if arity == 1} == unary
    assert {name for name, arity in PIXEL_MATH_ARITIES.items() if arity == 2} == {"atan2"}
    for operation, arity in PIXEL_MATH_ARITIES.items():
        assert validate_pixel_math_operation(operation) == operation
        assert pixel_math_arity(operation) == arity
        assert validate_pixel_math_arity(operation, arity) == arity


@pytest.mark.parametrize("operation", [None, 1, "atan_2", "Gamma", "", object()])
def test_pixel_math_contract_rejects_unknown_or_non_string_operations(operation):
    with pytest.raises(ValueError, match="supported operation names"):
        validate_pixel_math_operation(operation)


@pytest.mark.parametrize("arity", [True, 0, 2, "1", None])
def test_pixel_math_contract_rejects_mismatched_arity(arity):
    with pytest.raises(ValueError, match="requires 1 input band"):
        validate_pixel_math_arity("asin", arity)


@pytest.mark.parametrize(
    "operation,bands",
    [("asin", ("x",)), ("atan2", ("x", "y"))],
)
def test_pixel_math_dry_run_changes_only_band_schema(operation, bands):
    from engine.ee_pixel_math import local_ee_pixel_math

    cube, source, tracer = _dry_cube(bands=bands, temporal=True)
    result = local_ee_pixel_math({"data": cube, "operation": operation}, env=None)

    assert result.metadata.band_names == ["v"]
    assert result.metadata.has_temporal_dimension()
    assert result._traces == [source]
    assert result._data_tracer is tracer


def test_pixel_math_actual_cube_forwards_only_validated_operation(monkeypatch):
    from openeo_driver.datacube import DriverDataCube
    from engine import ee_process_adapters
    from engine.ee_pixel_math import local_ee_pixel_math

    cube = DriverDataCube(metadata=_metadata(("x", "y"), temporal=True))
    calls = []

    def apply(actual, process_id, arguments, metadata, *, target_type=None):
        calls.append((actual, process_id, arguments, metadata, target_type))
        return "native-result"

    monkeypatch.setattr(ee_process_adapters, "_apply_native", apply)
    result = local_ee_pixel_math({"data": cube, "operation": "atan2"}, env=None)

    assert result == "native-result"
    assert len(calls) == 1
    actual, process_id, arguments, metadata, target_type = calls[0]
    assert (actual, process_id, arguments, target_type) == (
        cube, "local_ee_pixel_math", {"operation": "atan2"}, None,
    )
    assert metadata.band_names == ["v"]
    assert metadata.has_temporal_dimension()


@pytest.mark.parametrize(
    "args,pattern",
    [
        ({"data": "cube", "operation": "asin", "extra": 1}, "accepts exactly"),
        ({"data": "cube", "operation": "unknown"}, "supported operation names"),
    ],
)
def test_pixel_math_rejects_bad_process_arguments_before_native_execution(args, pattern):
    from openeo_driver.datacube import DriverDataCube
    from engine.ee_pixel_math import local_ee_pixel_math

    args = dict(args)
    args["data"] = DriverDataCube(metadata=_metadata(("red",)))
    with pytest.raises(ValueError, match=pattern):
        local_ee_pixel_math(args, env=None)


@pytest.mark.parametrize("bands", [(), ("red",), ("x", "y")])
def test_pixel_math_unary_handler_rejects_incorrect_band_names_or_count(bands):
    from engine.ee_pixel_math import local_ee_pixel_math

    cube, _, _ = _dry_cube(bands=bands)
    with pytest.raises(ValueError, match="ordered input band\\(s\\): x"):
        local_ee_pixel_math({"data": cube, "operation": "asin"}, env=None)


@pytest.mark.parametrize("bands", [("red",), ("longitude", "latitude"), ("y", "x"), ("x", "z")])
def test_pixel_math_binary_handler_rejects_incorrect_or_reordered_band_names(bands):
    from engine.ee_pixel_math import local_ee_pixel_math

    cube, _, _ = _dry_cube(bands=bands)
    with pytest.raises(ValueError, match="ordered input band\\(s\\): x, y"):
        local_ee_pixel_math({"data": cube, "operation": "atan2"}, env=None)


def test_pixel_math_native_source_uses_locked_real_math_and_bounded_bridge():
    root = Path(__file__).parents[1]
    numeric = (root / "engine/ee_pixel_math_numeric.scala").read_text()
    adapter = (root / "engine/ee_pixel_math_adapter.scala").read_text()

    assert "org.apache.commons.math3.special.{Erf, Gamma}" in numeric
    assert "Gamma.gamma" in numeric and "Gamma.digamma" in numeric and "Gamma.trigamma" in numeric
    assert "boundedGamma(x.toDouble)" in numeric
    assert "boundedDigamma(x.toDouble)" in numeric and "boundedTrigamma(x.toDouble)" in numeric
    assert "isNonPositiveInteger" in numeric
    assert "value - java.lang.Math.floor(value)" in numeric
    assert "value > -0.5 && value < 0.5" in numeric
    assert "Erf.erfInv" in numeric and "Erf.erfcInv" in numeric
    assert "FloatConstantNoDataCellType" in numeric
    assert "Math.atan2(y.toDouble, x.toDouble)" in numeric
    assert "LocalEeClassifyReduceBridge.validate" in adapter
    assert "MaxPixelMathWork = 67108864L" in adapter
    assert 'Seq("x", "y")' in adapter
    assert "tilePixels <= MaxPixelMathWork" in adapter
    assert "LocalEePixelMathNumeric.applyTile(tile, operation)" in adapter
