"""Independent finite controls for Earth Engine correlation and trend reducers."""
import math
from decimal import Decimal, localcontext

import pytest

import gee.compat.earthengine.correlation_reducers as correlation_reducers
from gee.compat.earthengine.correlation_statistics import pearson_two_sided_p_value
from gee.compat.earthengine.correlation_reducers import (
    CORRELATION_REDUCER_NAMES,
    CorrelationReducerLeaf,
    describe_correlation_reducer,
    make_correlation_reducer,
    reduce_correlation_reducer,
)
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.trend_statistics import _from_float, _median


class Budget:
    def __init__(self, steps=0):
        self.steps = steps

    @staticmethod
    def allowed(arguments, names):
        unknown = set(arguments) - names
        if unknown:
            raise UnsupportedEEError(f"Unsupported algorithm arguments: {sorted(unknown)}")


def make(name, **arguments):
    return make_correlation_reducer(Budget(), name, arguments)


def reduce(name, records, **arguments):
    budget = Budget()
    leaf = make_correlation_reducer(budget, name, arguments)
    return dict(reduce_correlation_reducer(budget, leaf, records))


def decimal_pearson(x, y):
    """Independent high-precision centered Pearson reference."""
    with localcontext() as context:
        context.prec = 120
        dx = [Decimal.from_float(float(value)) for value in x]
        dy = [Decimal.from_float(float(value)) for value in y]
        mean_x = sum(dx) / len(dx)
        mean_y = sum(dy) / len(dy)
        centered_x = [value - mean_x for value in dx]
        centered_y = [value - mean_y for value in dy]
        covariance = sum(a * b for a, b in zip(centered_x, centered_y))
        sum_xx = sum(value * value for value in centered_x)
        sum_yy = sum(value * value for value in centered_y)
        return float(covariance / (sum_xx * sum_yy).sqrt())


def even_df_p_value_reference(correlation, count):
    """Independent Decimal beta integral for even t degrees of freedom."""
    assert count >= 4 and count % 2 == 0
    degrees_half = (count - 2) // 2
    with localcontext() as context:
        context.prec = 120
        magnitude = Decimal.from_float(abs(correlation))
        delta = Decimal(1) - magnitude * magnitude
        power = delta ** degrees_half
        coefficient = Decimal(1)
        integral = power / degrees_half
        cutoff = Decimal(1).scaleb(-110)
        for index in range(1, 2_000):
            coefficient *= Decimal(2 * index - 1) / Decimal(2 * index)
            power *= delta
            term = coefficient * power / Decimal(degrees_half + index)
            integral += term
            if term == 0 or term < integral * cutoff:
                break
        beta = (Decimal(4) ** degrees_half
                / (Decimal(degrees_half) * math.comb(2 * degrees_half, degrees_half)))
        return float(integral / beta)


def small_correlation_even_df_reference(correlation, count):
    """Independent finite Decimal expansion of I_(r^2)(1/2, df/2)."""
    assert count >= 6 and count % 2 == 0
    degrees_half = (count - 2) // 2
    with localcontext() as context:
        context.prec = 120
        magnitude = Decimal.from_float(abs(correlation))
        integral = Decimal(0)
        for index in range(degrees_half):
            coefficient = (-1) ** index * math.comb(degrees_half - 1, index)
            integral += (
                Decimal(coefficient) * magnitude ** (2 * index + 1)
                / Decimal(2 * index + 1)
            )
        beta = (Decimal(4) ** degrees_half
                / (Decimal(degrees_half) * math.comb(2 * degrees_half, degrees_half)))
        return float(Decimal(1) - 2 * integral / beta)


def test_canonical_names_arities_and_local_output_names():
    assert CORRELATION_REDUCER_NAMES == {
        "Reducer.pearsonsCorrelation",
        "Reducer.spearmansCorrelation",
        "Reducer.kendallsCorrelation",
        "Reducer.sensSlope",
    }
    assert describe_correlation_reducer(
        Budget(), make("Reducer.pearsonsCorrelation"),
    ) == (2, ("correlation", "p-value"))
    assert describe_correlation_reducer(
        Budget(), make("Reducer.spearmansCorrelation"),
    ) == (2, ("correlation",))
    assert describe_correlation_reducer(
        Budget(), make("Reducer.kendallsCorrelation"),
    ) == (1, ("tau",))
    assert describe_correlation_reducer(
        Budget(), make("Reducer.kendallsCorrelation", numInputs=2),
    ) == (2, ("tau",))
    assert describe_correlation_reducer(
        Budget(), make("Reducer.sensSlope"),
    ) == (2, ("slope", "offset"))


@pytest.mark.parametrize("name,arguments", [
    ("Reducer.pearsonsCorrelation", {"unexpected": 1}),
    ("Reducer.spearmansCorrelation", {"numInputs": 2}),
    ("Reducer.kendallsCorrelation", {"numInputs": True}),
    ("Reducer.kendallsCorrelation", {"numInputs": 0}),
    ("Reducer.kendallsCorrelation", {"numInputs": 3}),
    ("Reducer.sensSlope", {"unweighted": True}),
])
def test_constructor_rejects_noncanonical_arguments(name, arguments):
    with pytest.raises(UnsupportedEEError):
        make_correlation_reducer(Budget(), name, arguments)


@pytest.mark.parametrize("field,value", [
    ("name", "Reducer.linearFit"),
    ("name", "Reducer.sensSlope "),
    ("num_inputs", True),
    ("num_inputs", 3),
])
def test_descriptor_revalidates_mutated_frozen_fields(field, value):
    leaf = make("Reducer.kendallsCorrelation")
    object.__setattr__(leaf, field, value)
    with pytest.raises(UnsupportedEEError):
        describe_correlation_reducer(Budget(), leaf)


def test_pearson_coefficient_and_two_sided_p_value_match_closed_reference():
    # For n=4 and r=0.5, df=2 gives the exact two-sided p-value 1-|r|=0.5.
    rows = [[0, 0], [1, 1], [1, 2], [2, 1]]
    result = reduce("Reducer.pearsonsCorrelation", rows)
    assert result["correlation"] == pytest.approx(0.5, abs=1e-15)
    assert result["p-value"] == pytest.approx(0.5, abs=1e-14)


def test_pearson_n3_and_n4_p_values_match_closed_student_t_forms():
    # With df=1, t is Cauchy and p=2*acos(|r|)/pi. For df=2,
    # p=1-|r|. Both cases use r=0.5.
    n3 = reduce("Reducer.pearsonsCorrelation", [[0, 0], [1, 2], [2, 1]])
    assert n3["correlation"] == pytest.approx(0.5, abs=1e-15)
    assert n3["p-value"] == pytest.approx(2 / 3, abs=1e-14)
    assert pearson_two_sided_p_value(-0.5, 4) == pytest.approx(0.5, abs=1e-14)
    near_one = math.nextafter(1.0, 0.0)
    assert pearson_two_sided_p_value(near_one, 3) == pytest.approx(
        2 * math.acos(near_one) / math.pi, rel=2e-14,
    )
    assert pearson_two_sided_p_value(-near_one, 4) == pytest.approx(
        1 - near_one, abs=1e-16,
    )
    for tiny_correlation in (1e-4, 1e-8, 1e-9, 1e-16):
        assert pearson_two_sided_p_value(tiny_correlation, 3) == pytest.approx(
            2 * math.acos(tiny_correlation) / math.pi, abs=1e-16,
        )
        assert pearson_two_sided_p_value(-tiny_correlation, 4) == 1 - tiny_correlation


@pytest.mark.parametrize("count,correlation", [
    (10, 0.75),
    (10, 0.999999),
    (10, math.nextafter(1.0, 0.0)),
    (100, 0.9),
    (100, 0.999),
    (100, 0.999999),
])
def test_pearson_p_values_match_independent_decimal_beta_integrals(count, correlation):
    expected = even_df_p_value_reference(correlation, count)
    actual = pearson_two_sided_p_value(correlation, count)
    negative = pearson_two_sided_p_value(-correlation, count)
    assert expected > 0.0
    assert actual == pytest.approx(expected, rel=3e-12, abs=0.0)
    assert negative == pytest.approx(actual, rel=1e-14, abs=0.0)


@pytest.mark.parametrize("count,correlation", [
    (10, 1e-4),
    (10, 1e-8),
    (10, 1e-9),
    (100, 1e-4),
    (100, 1e-8),
    (100, 1e-9),
])
def test_small_correlation_p_values_match_independent_decimal_tail(count, correlation):
    expected = small_correlation_even_df_reference(correlation, count)
    actual = pearson_two_sided_p_value(correlation, count)
    negative = pearson_two_sided_p_value(-correlation, count)
    assert actual == pytest.approx(expected, abs=2 * math.ulp(expected))
    assert negative == actual


def test_spearman_uses_average_ranks_for_tied_values():
    # Average ranks are [1, 2.5, 2.5, 4] and [2, 4, 1, 3]. Their Pearson
    # correlation is 1/sqrt(10), an independent hand-computed reference.
    result = reduce(
        "Reducer.spearmansCorrelation",
        [[1, 2], [2, 4], [2, 1], [4, 3]],
    )
    assert result["correlation"] == pytest.approx(1 / math.sqrt(10), abs=1e-15)


def test_kendall_tau_b_counts_concordance_discordance_and_one_sided_ties():
    rows = [[1, 2], [1, 1], [2, 3], [3, 2]]
    # Three concordant, one discordant, one x-only tie and one y-only tie.
    # tau-b = (3-1)/sqrt((6-1)(6-1)) = 0.4.
    assert reduce("Reducer.kendallsCorrelation", rows, numInputs=2)["tau"] == pytest.approx(0.4)

    # The one-input form assigns increasing sequence x values after complete
    # case filtering. Five concordant pairs and one tied y pair give 5/sqrt(30).
    result = reduce("Reducer.kendallsCorrelation", [[1], [2], [2], [4]])
    assert result["tau"] == pytest.approx(5 / math.sqrt(30), abs=1e-15)


def test_sen_slope_uses_median_pair_slopes_and_median_point_intercept():
    result = reduce(
        "Reducer.sensSlope",
        [[0, 0], [1, 1], [2, 2], [3, 10]],
    )
    assert result["slope"] == pytest.approx(13 / 6, abs=1e-15)
    assert result["offset"] == pytest.approx(-7 / 12, abs=1e-15)


def test_large_offsets_and_subnormal_values_remain_stable():
    base = 1e300
    step = math.ulp(base)
    x = [base + index * step for index in range(4)]
    y = [-base + index * math.ulp(-base) for index in range(4)]
    result = reduce("Reducer.pearsonsCorrelation", list(map(list, zip(x, y))))
    assert result["correlation"] == pytest.approx(1.0, abs=1e-15)
    assert result["correlation"] == pytest.approx(decimal_pearson(x, y), abs=1e-15)

    # Scaling by the largest absolute value leaves a common offset near 0.5;
    # anchor-relative centering must retain these one-unit increments.
    offset = float(2**52)
    offset_x = [offset + index for index in range(8)]
    offset_y = [offset + value for value in [0, 1, 4, 3, 2, 7, 5, 9]]
    offset_result = reduce(
        "Reducer.pearsonsCorrelation", list(map(list, zip(offset_x, offset_y))),
    )["correlation"]
    assert offset_result == pytest.approx(
        decimal_pearson(offset_x, offset_y), abs=1e-15,
    )

    tiny = math.ulp(0.0)
    values = [tiny * index for index in range(1, 7)]
    tiny_y = [tiny * value for value in [6, 4, 5, 1, 3, 2]]
    tiny_result = reduce(
        "Reducer.pearsonsCorrelation", list(map(list, zip(values, tiny_y))),
    )
    assert tiny_result["correlation"] == pytest.approx(
        decimal_pearson(values, tiny_y), abs=1e-15,
    )

    strong_negative_y = [10, 7, 8, 4, 5, 0]
    strong_negative = reduce(
        "Reducer.pearsonsCorrelation",
        list(map(list, zip(range(6), strong_negative_y))),
    )["correlation"]
    assert strong_negative < -0.9
    assert strong_negative == pytest.approx(
        decimal_pearson(list(range(6)), strong_negative_y), rel=1e-14,
    )

    huge_trend = reduce(
        "Reducer.sensSlope",
        [[base + i * step, -base + i * math.ulp(-base)] for i in range(3)],
    )
    assert huge_trend["slope"] == pytest.approx(1.0, abs=1e-15)
    assert huge_trend["offset"] == pytest.approx(-2e300, rel=1e-15)

    tiny_trend = reduce("Reducer.sensSlope", [[0, 0], [tiny, tiny], [2 * tiny, 2 * tiny]])
    assert tiny_trend == {"slope": 1.0, "offset": 0.0}


def test_scaled_medians_order_negative_zero_and_positive_subnormals():
    tiny = math.ulp(0.0)
    assert _median([_from_float(tiny), (0.0, 0), _from_float(-tiny)]) == (0.0, 0)
    # The pair slopes are -tiny, zero, and +tiny; their median is exactly zero.
    result = reduce("Reducer.sensSlope", [[0, 0], [1, tiny], [2, 0]])
    assert result == {"slope": 0.0, "offset": 0.0}


def test_incomplete_rows_skip_but_every_nonnull_value_is_validated():
    rows = [[0, 0], [None, 100], [1, 2], [2, None], [3, 6]]
    assert reduce("Reducer.pearsonsCorrelation", rows)["correlation"] == pytest.approx(1.0)

    with pytest.raises(UnsupportedEEError, match="finite exact numbers or null"):
        reduce("Reducer.pearsonsCorrelation", [[None, object()]])
    with pytest.raises(UnsupportedEEError, match="finite exact numbers or null"):
        reduce("Reducer.pearsonsCorrelation", [[None, True]])
    with pytest.raises(UnsupportedEEError, match=r"±2\^53"):
        reduce("Reducer.sensSlope", [[None, 2**53 + 1]])


def test_undefined_and_empty_result_policies_are_explicit_nulls():
    assert reduce("Reducer.pearsonsCorrelation", []) == {
        "correlation": None, "p-value": None,
    }
    two_pairs = reduce("Reducer.pearsonsCorrelation", [[0, 0], [1, 1]])
    assert two_pairs == {"correlation": 1.0, "p-value": None}
    assert reduce("Reducer.pearsonsCorrelation", [[1, 0], [1, 1], [1, 2]]) == {
        "correlation": None, "p-value": None,
    }
    assert reduce("Reducer.kendallsCorrelation", [[1], [1], [1]]) == {"tau": None}
    assert reduce("Reducer.sensSlope", [[2, 1], [2, 3], [2, 5]]) == {
        "slope": None, "offset": None,
    }


def test_rows_and_quadratic_work_are_bounded_before_kernel_loops():
    leaf = make("Reducer.kendallsCorrelation", numInputs=2)
    translator = Budget()
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reduce_correlation_reducer(translator, leaf, [[i, i] for i in range(200)])
    assert translator.steps < 50_000
    with pytest.raises(UnsupportedEEError, match="at most 1000"):
        reduce_correlation_reducer(Budget(), leaf, [[i, i] for i in range(1_001)])


def test_maximum_linear_row_count_fits_the_shared_work_budget():
    rows = [[index, (index * 7) % 19] for index in range(1_000)]
    for name in ("Reducer.pearsonsCorrelation", "Reducer.spearmansCorrelation"):
        translator = Budget()
        leaf = make_correlation_reducer(translator, name, {})
        result = reduce_correlation_reducer(translator, leaf, rows)
        assert result
        assert translator.steps <= 50_000


@pytest.mark.parametrize(
    "name,initial_steps,records,kernels",
    [
        ("Reducer.pearsonsCorrelation", 48_400, [[0, 0], [1, 1], [2, 3], [3, 2]],
         ("pearson_correlation", "pearson_two_sided_p_value")),
        ("Reducer.spearmansCorrelation", 49_900, [[0, 0], [1, 1], [2, 3], [3, 2]],
         ("spearman_correlation",)),
        ("Reducer.kendallsCorrelation", 49_900, [[0], [1], [2], [3]],
         ("kendall_tau_b",)),
        ("Reducer.sensSlope", 49_850, [[i, i * i] for i in range(4)],
         ("sens_slope",)),
    ],
)
def test_all_kernel_work_is_reserved_before_kernel_execution(
    monkeypatch, name, initial_steps, records, kernels,
):
    for kernel in kernels:
        monkeypatch.setattr(
            correlation_reducers, kernel,
            lambda *args, _kernel=kernel: pytest.fail(
                f"{_kernel} ran before its work reservation"
            ),
        )
    translator = Budget(initial_steps)
    leaf = make(name)
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reduce_correlation_reducer(translator, leaf, records)
    assert translator.steps < 50_000


def test_noncanonical_leaf_type_is_rejected():
    with pytest.raises(UnsupportedEEError, match="invalid type"):
        describe_correlation_reducer(Budget(), object())
