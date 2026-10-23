"""Finite Array statistics, field-axis layouts, ownership and budgets."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import StaticArray, wrap_array
from gee.compat.earthengine.array_numeric_reductions import _product
from gee.compat.earthengine.array_reductions import invoke_reduction
from gee.compat.earthengine.composed_reducers import invoke_composed_reducer
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.finite_reducer_leaves import invoke_finite_reducer
from gee.compat.earthengine.ir import Reducer, UnsupportedEEError
from gee.compat.earthengine.numeric_reducer_plan import numeric_outputs
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression


def translator():
    return Translator([], {}, None)


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=(Path(__file__).resolve().parents[1]
                         / "vendor/earthengine-js/algorithms.json"),
    )


def sdk_output(ee, value):
    encoded = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(encoded, [], {})["value"]


def reducer(name, active=None):
    if name in {"product", "stdDev", "variance", "sampleVariance", "minMax"}:
        active = active or translator()
        return invoke_finite_reducer(active, f"Reducer.{name}", {})
    return Reducer(name)


def reduce(array, reducer, axes, field_axis=None, active=None):
    active = active or translator()
    arguments = {"array": array, "reducer": reducer, "axes": axes}
    if field_axis is not None:
        arguments["fieldAxis"] = field_axis
    result = invoke_reduction(active, "Array.reduce", arguments)
    return result.data, active


def test_existing_and_new_statistics_keep_the_expected_population_policies():
    values = wrap_array([[1, 3], [5, 7]])
    expected = {
        "sum": [[6, 10]],
        "mean": [[3.0, 5.0]],
        "min": [[1, 3]],
        "max": [[5, 7]],
        "count": [[2, 2]],
        "first": [[1, 3]],
        "last": [[5, 7]],
        "median": [[3.0, 5.0]],
        "sd": [[math.sqrt(8), math.sqrt(8)]],
        "stdDev": [[2.0, 2.0]],
        "variance": [[4.0, 4.0]],
        "sampleVariance": [[8.0, 8.0]],
        "product": [[5, 21]],
    }
    for operation, reference in expected.items():
        actual, _ = reduce(values, reducer(operation), [0])
        np.testing.assert_allclose(actual, reference, rtol=2e-15, atol=0)


def test_minmax_expands_fields_and_composed_shared_outputs_can_be_renamed():
    array = wrap_array([[1], [4], [2]])
    actual, _ = reduce(array, reducer("minMax"), [0], field_axis=1)
    assert actual.tolist() == [[1, 4]]

    active = translator()
    combined = invoke_composed_reducer(active, "Reducer.combine", {
        "reducer1": Reducer("min"), "reducer2": Reducer("max"),
        "sharedInputs": True,
    })
    renamed = invoke_composed_reducer(active, "Reducer.setOutputs", {
        "reducer": combined, "outputs": ["low", "high"],
    })
    outputs = numeric_outputs(active, renamed)
    assert outputs == (("low", "min"), ("high", "max"))
    result, _ = reduce(array, renamed, [0], field_axis=1, active=active)
    assert result.tolist() == [[1, 4]]


def test_official_python_sdk_serializes_multioutput_field_axis(ee):
    minimum_and_maximum = ee.Reducer.min().combine(
        ee.Reducer.max(), sharedInputs=True,
    ).setOutputs(["low", "high"])
    result = ee.Array([[1], [4], [2]]).reduce(
        minimum_and_maximum, [0], fieldAxis=1,
    )
    assert sdk_output(ee, result) == [[1, 4]]


def test_field_axis_position_and_axis_order_preserve_other_dimensions():
    source = np.arange(1, 13, dtype=np.int64).reshape(2, 1, 3, 2)
    # This non-contiguous view exercises grouping after a transpose.
    source = source[:, :, :, ::-1]
    array = StaticArray(source)
    forward, _ = reduce(array, Reducer("minMax"), [3, 0], field_axis=1)
    reverse, _ = reduce(array, Reducer("minMax"), [0, 3], field_axis=1)
    assert forward.shape == (1, 2, 3, 1)
    assert np.array_equal(forward, reverse)
    expected = np.empty((1, 2, 3, 1), dtype=np.int64)
    for column in range(3):
        values = [source[row, 0, column, edge] for row in range(2) for edge in range(2)]
        expected[0, 0, column, 0] = min(values)
        expected[0, 1, column, 0] = max(values)
    assert np.array_equal(forward, expected)


def test_explicit_single_output_field_axis_is_valid_when_shape_matches():
    array = wrap_array([[[1, 5]], [[3, 7]]])
    result, _ = reduce(array, Reducer("mean"), [0], field_axis=1)
    assert result.tolist() == [[[2.0, 6.0]]]


def test_large_offset_dispersion_and_sd_do_not_compute_an_overflowing_variance():
    near = wrap_array([2**52, 2**52 + 1, 2**52 + 2])
    population, _ = reduce(near, reducer("variance"), [0])
    assert population[()] == pytest.approx(2 / 3)

    extremes = wrap_array([-1e308, 1e308])
    sd, _ = reduce(extremes, reducer("stdDev"), [0])
    assert sd[()] == pytest.approx(1e308, rel=3e-16)
    for operation in ("variance", "sampleVariance"):
        with pytest.raises(UnsupportedEEError, match="finite Float64"):
            reduce(extremes, reducer(operation), [0])

    for origin in (1e308, 1e-300):
        adjacent = math.nextafter(origin, math.inf)
        expected = (adjacent - origin) / 2
        actual, _ = reduce(
            wrap_array([origin, adjacent]), reducer("stdDev"), [0],
        )
        assert actual[()] == expected


def test_products_preserve_cancellation_tiny_values_and_exact_integer_domain():
    result, _ = reduce(
        wrap_array([1e308, 1e308, 1e-308]), reducer("product"), [0],
    )
    assert result[()] == pytest.approx(1e308, rel=2e-15)
    tiny, _ = reduce(
        wrap_array([1e-200, 1e-200, 1e200, 1e200]), reducer("product"), [0],
    )
    assert tiny[()] == pytest.approx(1.0)
    with pytest.raises(UnsupportedEEError, match="exact Float64"):
        reduce(wrap_array([2**52, 4]), reducer("product"), [0])

    boundary, _ = reduce(wrap_array([2**52, 2]), reducer("product"), [0])
    assert boundary[()] == 2**53


def test_integer_product_scans_zero_and_rejects_before_later_factors():
    factors_with_zero = np.full(8_000, 2**53, dtype=np.int64)
    factors_with_zero[-1] = 0
    cancelled, _ = reduce(
        StaticArray(factors_with_zero), reducer("product"), [0],
    )
    assert cancelled[()] == 0

    class StopsAfterOverflow:
        def __init__(self):
            self.passes = 0

        def __iter__(self):
            self.passes += 1
            if self.passes == 1:
                yield 2**52
                yield 4
                return
            yield 2**52
            yield 4
            raise AssertionError("integer product read factors after overflow")

    with pytest.raises(UnsupportedEEError, match="exact Float64"):
        _product(StopsAfterOverflow(), integer_input=True)


def test_sample_singletons_and_invalid_field_layouts_reject_explicitly():
    singleton = wrap_array([[1], [2]])
    for operation in ("sd", "sampleVariance"):
        with pytest.raises(UnsupportedEEError, match="at least two"):
            reduce(singleton, reducer(operation), [1])

    with pytest.raises(UnsupportedEEError, match="requires fieldAxis"):
        reduce(singleton, reducer("minMax"), [0])
    with pytest.raises(UnsupportedEEError, match="length must equal"):
        reduce(wrap_array([[1, 2], [3, 4]]), Reducer("minMax"), [0], field_axis=1)
    with pytest.raises(UnsupportedEEError, match="cannot also be"):
        reduce(singleton, Reducer("mean"), [0, 1], field_axis=1)
    with pytest.raises(UnsupportedEEError, match="fieldAxis"):
        reduce(singleton, Reducer("mean"), [0], field_axis=True)


def test_reducer_arguments_work_budget_and_result_ownership_are_checked(monkeypatch):
    array = wrap_array([[1, 2], [3, 4]])
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_reduction(translator(), "Array.reduce", {
            "array": array, "reducer": Reducer("mean"), "axes": [0],
            "ignored": 1,
        })

    active = translator()
    large = wrap_array(np.ones((100, 100), dtype=np.float64))
    called = False

    def grouping_must_not_start(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("group allocation began before its work charge")

    monkeypatch.setattr(
        "gee.compat.earthengine.array_numeric_reductions._gather_groups",
        grouping_must_not_start,
    )
    active.steps = 30_000
    with pytest.raises(UnsupportedEEError, match="work budget"):
        reduce(large, Reducer("mean"), [0], active=active)
    assert not called
    monkeypatch.undo()

    result, _ = reduce(array, Reducer("sum"), [0])
    assert not result.flags.writeable
    assert not np.shares_memory(result, array.data)


def test_axes_and_rank_limits_are_preflighted():
    array = wrap_array([[1, 2], [3, 4]])
    for axes in ([], [0, 0], [-1], [2], [True], [0.5]):
        with pytest.raises(UnsupportedEEError):
            reduce(array, Reducer("sum"), axes)

    oversized = StaticArray(np.ones((100, 101), dtype=np.float64))
    with pytest.raises(UnsupportedEEError, match="10000-cell"):
        reduce(oversized, Reducer("sum"), [0])

    expanded = wrap_array(np.ones((1, 1, 6_000), dtype=np.float64))
    with pytest.raises(UnsupportedEEError, match="result exceeds 10000 cells"):
        reduce(expanded, reducer("minMax"), [0], field_axis=1)
