from dataclasses import FrozenInstanceError
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import math

import pytest

from gee.compat.earthengine.circular_reducers import (
    CIRCULAR_REDUCER_NAMES,
    MAX_CIRCULAR_ROWS,
    CircularReducerLeaf,
    describe_circular_reducer,
    make_circular_reducer,
    reduce_circular_reducer,
)
from gee.compat.earthengine.ir import UnsupportedEEError


class Budget:
    def __init__(self, steps=0):
        self.steps = steps

    @staticmethod
    def allowed(arguments, names):
        if set(arguments) - names:
            raise UnsupportedEEError("Unexpected reducer argument")


_OUTPUTS = {
    "Reducer.circularMean": "circularMean",
    "Reducer.circularStddev": "circularStdDev",
    "Reducer.circularVariance": "circularVariance",
}


def make(name, budget=None, **arguments):
    return make_circular_reducer(budget or Budget(), name, arguments)


def reduce(name, values, budget=None):
    budget = budget or Budget()
    leaf = make_circular_reducer(budget, name, {})
    return dict(reduce_circular_reducer(
        budget, leaf, [[value] for value in values],
    ))[_OUTPUTS[name]]


def _decimal_pi(precision=520):
    """Gauss-Legendre pi for a trig oracle independent of libm."""
    with localcontext() as context:
        context.prec = precision
        a = Decimal(1)
        b = Decimal(1) / Decimal(2).sqrt()
        t = Decimal(1) / 4
        multiplier = Decimal(1)
        for _ in range(9):
            next_a = (a + b) / 2
            b = (a * b).sqrt()
            t -= multiplier * (a - next_a) ** 2
            a = next_a
            multiplier *= 2
        return +(a + b) ** 2 / (4 * t)


def _decimal_sin_cos(value, pi):
    with localcontext() as context:
        context.prec = 500
        angle = Decimal.from_float(float(value))
        tau = 2 * pi
        turns = (angle / tau).to_integral_value(rounding=ROUND_HALF_EVEN)
        reduced = angle - turns * tau
        if reduced > pi:
            reduced -= tau
        elif reduced < -pi:
            reduced += tau

        square = reduced * reduced
        sine_term = sine = reduced
        cosine_term = cosine = Decimal(1)
        for index in range(1, 200):
            sine_term *= -square / Decimal((2 * index) * (2 * index + 1))
            cosine_term *= -square / Decimal((2 * index - 1) * (2 * index))
            sine += sine_term
            cosine += cosine_term
            if abs(sine_term) < Decimal(1).scaleb(-490) and abs(cosine_term) < Decimal(1).scaleb(-490):
                break
        return +sine, +cosine


def decimal_reference(values):
    """High-precision resultant/direction from exact binary64 inputs."""
    pi = _decimal_pi()
    with localcontext() as context:
        context.prec = 480
        pairs = [_decimal_sin_cos(value, pi) for value in values]
        count = Decimal(len(pairs))
        sine = sum((item[0] for item in pairs), Decimal())
        cosine = sum((item[1] for item in pairs), Decimal())
        resultant = (sine * sine + cosine * cosine).sqrt() / count
        mean = math.atan2(float(sine), float(cosine))
        if mean >= math.pi:
            mean -= 2 * math.pi
        variance = Decimal(1) - resultant
        deviation = (-2 * resultant.ln()).sqrt() if resultant else None
        return mean, float(variance), None if deviation is None else float(deviation)


def angular_error(actual, expected):
    return abs(math.remainder(actual - expected, 2 * math.pi))


def test_closed_no_argument_leaves_and_canonical_labels():
    assert CIRCULAR_REDUCER_NAMES == set(_OUTPUTS)
    for name, output in _OUTPUTS.items():
        budget = Budget()
        leaf = make(name, budget=budget)
        assert leaf == CircularReducerLeaf(name)
        assert describe_circular_reducer(budget, leaf) == (1, (output,))
        with pytest.raises(FrozenInstanceError):
            leaf.name = "other"
    with pytest.raises(UnsupportedEEError):
        make("Reducer.circularMean", unexpected=1)
    with pytest.raises(UnsupportedEEError):
        make("Reducer.circularMean", budget=Budget(), foo=1)
    with pytest.raises(UnsupportedEEError):
        describe_circular_reducer(Budget(), CircularReducerLeaf("unknown"))


@pytest.mark.parametrize("name", sorted(CIRCULAR_REDUCER_NAMES))
def test_empty_and_all_null_have_explicit_undefined_results(name):
    assert reduce(name, []) is None
    assert reduce(name, [None, None]) is None


def test_mean_variance_and_standard_deviation_match_analytic_values():
    values = [-math.pi / 4, 0.0, math.pi / 4]
    resultant = (1.0 + math.sqrt(2.0)) / 3.0
    assert reduce("Reducer.circularMean", values) == pytest.approx(0.0, abs=1e-16)
    assert reduce("Reducer.circularVariance", values) == pytest.approx(
        1.0 - resultant, rel=2e-15,
    )
    assert reduce("Reducer.circularStddev", values) == pytest.approx(
        math.sqrt(-2.0 * math.log(resultant)), rel=2e-15,
    )


@pytest.mark.parametrize("values", [
    [1.0, 1.0 + 1e-12, 1.0 + 2e-12],
    [math.pi - 1e-8, -math.pi + 1e-8],
    [0.0, math.pi - 1e-8],
    [1e-200, 0.0],
])
def test_tiny_wrapped_and_near_antipodal_results_match_decimal(values):
    expected_mean, expected_variance, expected_sd = decimal_reference(values)
    actual_mean = reduce("Reducer.circularMean", values)
    actual_variance = reduce("Reducer.circularVariance", values)
    actual_sd = reduce("Reducer.circularStddev", values)
    assert actual_mean is not None
    assert angular_error(actual_mean, expected_mean) <= 2e-14
    assert actual_variance == pytest.approx(expected_variance, rel=3e-13, abs=1e-323)
    assert actual_sd == pytest.approx(expected_sd, rel=3e-13, abs=1e-323)


def test_antipodal_zero_resultant_has_defined_variance_but_undefined_direction_and_sd():
    values = [0.0, math.pi]
    assert reduce("Reducer.circularMean", values) is None
    assert reduce("Reducer.circularVariance", values) == 1.0
    assert reduce("Reducer.circularStddev", values) is None


def test_huge_finite_angles_use_trig_range_reduction_not_manual_modulo():
    values = [1e100, 1e100, -1e100, 0.25]
    expected_mean, expected_variance, expected_sd = decimal_reference(values)
    actual_mean = reduce("Reducer.circularMean", values)
    assert actual_mean is not None and math.isfinite(actual_mean)
    assert angular_error(actual_mean, expected_mean) <= 2e-15
    assert reduce("Reducer.circularVariance", values) == pytest.approx(
        expected_variance, rel=5e-14, abs=2e-16,
    )
    assert reduce("Reducer.circularStddev", values) == pytest.approx(
        expected_sd, rel=5e-14, abs=2e-15,
    )


@pytest.mark.parametrize("bad", [True, False, float("nan"), math.inf, -math.inf, "1", object()])
def test_rejects_bool_nonfinite_and_non_numeric_values(bad):
    with pytest.raises(UnsupportedEEError):
        reduce("Reducer.circularMean", [bad])


def test_rejects_inexact_integer_rows_and_malformed_or_oversized_inputs():
    with pytest.raises(UnsupportedEEError, match=r"exact ±2\^53"):
        reduce("Reducer.circularMean", [2**53 + 1])
    budget = Budget()
    leaf = make("Reducer.circularMean", budget=budget)
    with pytest.raises(UnsupportedEEError, match="exactly one input"):
        reduce_circular_reducer(budget, leaf, [[1.0, 2.0]])
    with pytest.raises(UnsupportedEEError, match="at most 1000"):
        reduce("Reducer.circularMean", [0.0] * (MAX_CIRCULAR_ROWS + 1))


def test_precharges_work_before_kernel_and_accepts_the_full_row_bound():
    budget = Budget(steps=49_900)
    leaf = make("Reducer.circularMean", budget=budget)
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reduce_circular_reducer(budget, leaf, [[0.0]])

    budget = Budget()
    leaf = make("Reducer.circularVariance", budget=budget)
    result = reduce_circular_reducer(budget, leaf, [[0.0]] * MAX_CIRCULAR_ROWS)
    assert result == [("circularVariance", 0.0)]
    assert budget.steps <= 50_000
