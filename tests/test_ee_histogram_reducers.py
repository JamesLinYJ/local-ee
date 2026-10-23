"""Independent controls for finite fixed-bin histogram reducer leaves."""
from fractions import Fraction
import math

import numpy as np
import pytest
import ee

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.histogram_reducers import (
    HISTOGRAM_REDUCER_NAMES,
    HistogramReducerLeaf,
    describe_histogram_reducer,
    make_histogram_reducer,
    reduce_histogram_reducer,
)
from gee.ee_translate import UnsupportedEEError


def _translator():
    return Translator([], {}, None)


def _one(translator, minimum=0.0, maximum=1.0, steps=4, cumulative=False):
    return make_histogram_reducer(translator, "Reducer.fixedHistogram", {
        "min": minimum, "max": maximum, "steps": steps,
        "cumulative": cumulative,
    })


def _two(translator, *, x=(0.0, 1.0, 2), y=(0.0, 1.0, 2)):
    return make_histogram_reducer(translator, "Reducer.fixed2DHistogram", {
        "xMin": x[0], "xMax": x[1], "xSteps": x[2],
        "yMin": y[0], "yMax": y[1], "ySteps": y[2],
    })


def _fraction_bin(value, minimum, maximum, steps):
    exact = Fraction(value) if type(value) is int else Fraction.from_float(value)
    low = Fraction.from_float(minimum)
    high = Fraction.from_float(maximum)
    if exact < low or exact >= high:
        return None
    return int((exact - low) * steps // (high - low))


def _counts(result):
    name, value = result[0]
    assert name == "histogram"
    assert type(value) is not list
    assert not value.data.flags.writeable
    return value.data


def test_names_signatures_and_descriptor_fields_are_closed():
    assert HISTOGRAM_REDUCER_NAMES == (
        "Reducer.fixedHistogram", "Reducer.fixed2DHistogram",
    )
    translator = _translator()
    leaf = _one(translator)
    assert describe_histogram_reducer(_translator(), leaf) == (1, ("histogram",))
    assert describe_histogram_reducer(_translator(), _two(_translator())) == (
        2, ("histogram", "xAxis", "yAxis"),
    )
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        make_histogram_reducer(_translator(), "Reducer.fixedHistogram", {
            "min": 0.0, "max": 1.0, "steps": 4, "unused": 1,
        })
    with pytest.raises(UnsupportedEEError, match="missing required"):
        make_histogram_reducer(_translator(), "Reducer.fixed2DHistogram", {})
    with pytest.raises(UnsupportedEEError, match="invalid types or arity"):
        describe_histogram_reducer(
            _translator(), HistogramReducerLeaf(
                "Reducer.fixedHistogram", (0,), (1.0,), (4,), False,
            ),
        )


def test_integer_valued_float_steps_canonicalize_before_shape_validation():
    one = _one(_translator(), steps=2.0)
    assert one.steps == (2,)
    assert type(one.steps[0]) is int
    assert _counts(reduce_histogram_reducer(
        _translator(), one, [[0.1], [0.9]],
    )).tolist() == [[0.0, 1.0], [0.5, 1.0]]

    two = _two(_translator(), x=(0.0, 1.0, 2.0), y=(0.0, 1.0, 1.0))
    assert two.steps == (2, 1)
    assert all(type(step) is int for step in two.steps)


def test_official_ee_serializer_preserves_float_number_for_integer_step():
    encoded = ee.serializer.encode(2.0)
    serialized_step = encoded["values"][encoded["result"]]["constantValue"]
    assert type(serialized_step) is float
    assert _one(_translator(), steps=serialized_step).steps == (2,)


@pytest.mark.parametrize(
    "bad", [True, False, 0, -1, 1.5, float("nan"), float("inf"),
            2**53 + 1, float(2**54), "2"],
)
def test_steps_reject_nonpositive_nonintegral_nonfinite_and_inexact_values(bad):
    with pytest.raises(UnsupportedEEError):
        _one(_translator(), steps=bad)


def test_optional_cumulative_omission_defaults_false_and_null_is_not_false():
    leaf = make_histogram_reducer(_translator(), "Reducer.fixedHistogram", {
        "min": 0.0, "max": 1.0, "steps": 2,
    })
    assert leaf.cumulative is False
    with pytest.raises(UnsupportedEEError, match="cumulative must be a boolean"):
        _one(_translator(), cumulative=None)


def test_fixed_histogram_edges_and_bins_match_fraction_reference():
    translator = _translator()
    leaf = _one(translator, minimum=-0.3, maximum=1.1, steps=7)
    values = [-0.3, -0.1, 0.0, 0.1, 0.4, 0.8, 1.099, 1.1, -1.0]
    result = _counts(reduce_histogram_reducer(
        translator, leaf, [[value] for value in values],
    ))
    expected = [0] * leaf.steps[0]
    for value in values:
        index = _fraction_bin(value, leaf.minimums[0], leaf.maximums[0], leaf.steps[0])
        if index is not None:
            expected[index] += 1
    assert result[:, 1].tolist() == expected
    assert result[:, 0].tolist() == [
        float(Fraction.from_float(leaf.minimums[0])
              + (Fraction.from_float(leaf.maximums[0])
                 - Fraction.from_float(leaf.minimums[0])) * i / leaf.steps[0])
        for i in range(leaf.steps[0])
    ]


def test_exact_boundary_goes_right_last_max_is_excluded_and_cumulative_works():
    leaf = _one(_translator(), steps=4, cumulative=True)
    below = math.nextafter(0.25, -math.inf)
    rows = [[below], [0.25], [0.5], [0.75], [1.0], [None]]
    values = _counts(reduce_histogram_reducer(_translator(), leaf, rows))
    assert values.tolist() == [[0.0, 1.0], [0.25, 2.0], [0.5, 3.0], [0.75, 4.0]]


def test_fixed_2d_histogram_counts_only_complete_in_range_pairs():
    translator = _translator()
    leaf = _two(translator, x=(-1.0, 1.0, 2), y=(0.0, 2.0, 2))
    outputs = reduce_histogram_reducer(translator, leaf, [
        [-1.0, 0.0], [-0.1, 0.1], [0.0, 0.1], [0.9, 1.9],
        [1.0, 1.0], [0.0, 2.0], [None, 1.0], [0.0, None],
    ])
    assert [name for name, _ in outputs] == ["histogram", "xAxis", "yAxis"]
    matrix, x_edges, y_edges = [value.data for _, value in outputs]
    assert matrix.tolist() == [[2, 0], [1, 1]]
    assert x_edges.tolist() == [-1.0, 0.0]
    assert y_edges.tolist() == [0.0, 1.0]
    assert all(not value.data.flags.writeable for _, value in outputs)


def test_2d_input_validates_every_nonnull_component_even_when_row_is_incomplete():
    with pytest.raises(UnsupportedEEError, match="finite numbers or null"):
        reduce_histogram_reducer(_translator(), _two(_translator()), [[None, math.inf]])
    with pytest.raises(UnsupportedEEError, match="exactly 2 scalar inputs"):
        reduce_histogram_reducer(_translator(), _two(_translator()), [[1.0]])


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), 2**53 + 1, "1", [1]])
def test_nonfinite_wrong_types_and_inexact_integers_reject(bad):
    with pytest.raises(UnsupportedEEError):
        reduce_histogram_reducer(_translator(), _one(_translator()), [[bad]])


def test_grid_rejects_collapsed_huge_and_subnormal_edges():
    with pytest.raises(UnsupportedEEError, match="grid is not representable"):
        _one(_translator(), float(2**53 - 1), float(2**53), 2)
    with pytest.raises(UnsupportedEEError, match="grid is not representable"):
        _one(_translator(), 0.0, math.ulp(0.0), 2)


def test_exact_large_and_small_values_are_valid_when_grid_is_representable():
    large = _one(_translator(), -1.7976931348623157e308,
                 1.7976931348623157e308, 2)
    assert _counts(reduce_histogram_reducer(
        _translator(), large, [[-1.0], [0.0], [1.0]],
    ))[:, 1].tolist() == [1.0, 2.0]
    small = _one(_translator(), 0.0, math.ulp(0.0), 1)
    assert _counts(reduce_histogram_reducer(
        _translator(), small, [[0.0], [math.ulp(0.0)]],
    ))[:, 1].tolist() == [1.0]


def test_empty_inputs_and_detached_readonly_outputs():
    leaf = _one(_translator(), steps=3)
    rows = [[0.2], [0.8]]
    result = _counts(reduce_histogram_reducer(_translator(), leaf, rows))
    rows[0][0] = 0.9
    assert result.tolist() == [[0.0, 1.0], [1 / 3, 0.0], [2 / 3, 1.0]]
    assert _counts(reduce_histogram_reducer(_translator(), leaf, [])).tolist() == [
        [0.0, 0.0], [1 / 3, 0.0], [2 / 3, 0.0],
    ]


def test_array_shape_and_shared_work_budgets_precede_kernel_allocation():
    with pytest.raises(UnsupportedEEError, match="10000-array-cell"):
        _one(_translator(), steps=5_001)
    translator = _translator()
    leaf = _one(translator, steps=10)
    translator.steps = 50_000 - (1 + len(leaf.name) + sum(leaf.steps)) - 1
    before = translator.steps
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reduce_histogram_reducer(translator, leaf, [])
    assert translator.steps == before + 1 + len(leaf.name) + sum(leaf.steps)


def test_row_limit_is_the_existing_one_thousand_limit():
    leaf = _one(_translator(), steps=1)
    with pytest.raises(UnsupportedEEError, match="at most 1000 input rows"):
        reduce_histogram_reducer(_translator(), leaf, [[0.5]] * 1_001)
