"""Independent finite controls for skew and excess-kurtosis reducers."""
from decimal import Decimal, localcontext
import math

import pytest

import gee.compat.earthengine.moment_reducers as moment_reducers
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.moment_reducers import (
    MOMENT_REDUCER_NAMES,
    MomentReducerLeaf,
    describe_moment_reducer,
    make_moment_reducer,
    reduce_moment_reducer,
)


class Budget:
    def __init__(self, steps=0):
        self.steps = steps

    @staticmethod
    def allowed(arguments, names):
        unknown = set(arguments) - names
        if unknown:
            raise UnsupportedEEError(f"Unsupported algorithm arguments: {sorted(unknown)}")


def make(name, **arguments):
    return make_moment_reducer(Budget(), name, arguments)


def reduce(name, values, *, budget=None):
    translator = budget or Budget()
    leaf = make_moment_reducer(translator, name, {})
    return reduce_moment_reducer(translator, leaf, [[value] for value in values])


def decimal_reference(values, order):
    """Independent high-precision population central-moment definition."""
    with localcontext() as context:
        context.prec = 180
        numbers = [Decimal.from_float(float(value)) for value in values]
        mean = sum(numbers) / len(numbers)
        centered = [value - mean for value in numbers]
        second = sum(value * value for value in centered) / len(numbers)
        if second == 0:
            return None
        if order == 3:
            third = sum(value**3 for value in centered) / len(numbers)
            return float(third / (second * second.sqrt()))
        fourth = sum(value**4 for value in centered) / len(numbers)
        return float(fourth / (second * second) - Decimal(3))


def test_canonical_names_arity_and_pinned_output_names():
    assert MOMENT_REDUCER_NAMES == {"Reducer.skew", "Reducer.kurtosis"}
    assert describe_moment_reducer(Budget(), make("Reducer.skew")) == (1, ("skew",))
    assert describe_moment_reducer(Budget(), make("Reducer.kurtosis")) == (
        1, ("kurtosis",),
    )


@pytest.mark.parametrize("name,arguments", [
    ("Reducer.skew", {"numInputs": 1}),
    ("Reducer.kurtosis", {"unweighted": True}),
    ("Reducer.mean", {}),
    (1, {}),
    ("Reducer.skew", {1: "not a name"}),
])
def test_constructor_rejects_unknown_names_and_arguments(name, arguments):
    with pytest.raises(UnsupportedEEError):
        make_moment_reducer(Budget(), name, arguments)


@pytest.mark.parametrize("name", ["Reducer.mean", "Reducer.skew ", None])
def test_descriptor_rejects_mutated_or_fabricated_canonical_fields(name):
    leaf = make("Reducer.skew")
    object.__setattr__(leaf, "name", name)
    with pytest.raises(UnsupportedEEError):
        describe_moment_reducer(Budget(), leaf)


def test_descriptor_requires_the_exact_closed_leaf_type():
    class DerivedMomentLeaf(MomentReducerLeaf):
        pass

    with pytest.raises(UnsupportedEEError):
        describe_moment_reducer(Budget(), DerivedMomentLeaf("Reducer.skew"))
    with pytest.raises(UnsupportedEEError):
        describe_moment_reducer(Budget(), object())


@pytest.mark.parametrize("name,order", [
    ("Reducer.skew", 3),
    ("Reducer.kurtosis", 4),
])
@pytest.mark.parametrize("values", [
    [0.0, 0.0, 0.0, 1.0],
    [-5.0, -1.0, 0.0, 2.0, 9.0, 20.0],
])
def test_values_match_independent_decimal_population_moments(name, order, values):
    actual = dict(reduce(name, values))["skew" if order == 3 else "kurtosis"]
    assert actual == pytest.approx(decimal_reference(values, order), rel=2e-14, abs=2e-14)


@pytest.mark.parametrize("values", [
    [2**52 + offset for offset in (0, 1, 2, 4, 7, 11, 13)],
    [1e308, -1e308, 8e307, -3e307, 0.0],
    [math.ulp(0.0) * factor for factor in (1, 2, 3, 7, 12, 15)],
])
@pytest.mark.parametrize("name,order,output", [
    ("Reducer.skew", 3, "skew"),
    ("Reducer.kurtosis", 4, "kurtosis"),
])
def test_offset_extreme_and_subnormal_values_match_decimal(name, order, output, values):
    actual = dict(reduce(name, values))[output]
    expected = decimal_reference(values, order)
    assert actual == pytest.approx(expected, rel=4e-14, abs=4e-14)


def test_empty_constant_and_singleton_samples_are_undefined():
    for name, output in (("Reducer.skew", "skew"), ("Reducer.kurtosis", "kurtosis")):
        assert dict(reduce(name, [])) == {output: None}
        assert dict(reduce(name, [None, None])) == {output: None}
        assert dict(reduce(name, [8.0])) == {output: None}
        assert dict(reduce(name, [4.0, 4.0, 4.0])) == {output: None}


@pytest.mark.parametrize("values", [
    [True, 2], [float("nan")], [float("inf")], ["3"], [2**53 + 1],
])
def test_nonfinite_boolean_text_and_inexact_integer_inputs_fail(values):
    with pytest.raises(UnsupportedEEError):
        reduce("Reducer.skew", values)


def test_incomplete_rows_skip_but_every_nonnull_field_is_validated():
    translator = Budget()
    leaf = make_moment_reducer(translator, "Reducer.skew", {})
    assert dict(reduce_moment_reducer(
        translator, leaf, [[0.0], [None], [1.0], [2.0], [4.0]],
    ))["skew"] == pytest.approx(decimal_reference([0, 1, 2, 4], 3))
    for invalid in (True, object()):
        with pytest.raises(UnsupportedEEError):
            reduce_moment_reducer(Budget(), leaf, [[None], [invalid]])
    with pytest.raises(UnsupportedEEError, match="exactly one input"):
        reduce_moment_reducer(Budget(), leaf, [[1.0, 2.0]])


def test_one_thousand_rows_fit_unchanged_work_cap_and_inputs_are_read_only():
    values = [float((index % 19) - 9) + (index % 3) / 8 for index in range(1_000)]
    rows = [[value] for value in values]
    before = [row[:] for row in rows]
    budget = Budget()
    leaf = make_moment_reducer(budget, "Reducer.kurtosis", {})
    first = reduce_moment_reducer(budget, leaf, rows)
    second = reduce_moment_reducer(Budget(), leaf, rows)
    expected = decimal_reference(values, 4)
    assert dict(first)["kurtosis"] == pytest.approx(expected, rel=2e-13, abs=2e-13)
    assert budget.steps < 50_000
    assert first is not second
    first.append(("caller-owned", None))
    assert len(second) == 1
    assert rows == before


def test_row_cap_and_negative_or_exhausted_budgets_fail_closed(monkeypatch):
    with pytest.raises(UnsupportedEEError, match="1000"):
        reduce("Reducer.skew", [1.0] * 1_001)

    negative = Budget(-1)
    with pytest.raises(UnsupportedEEError, match="nonnegative"):
        describe_moment_reducer(negative, MomentReducerLeaf("Reducer.skew"))
    assert negative.steps == -1

    exhausted = Budget(49_950)
    with pytest.raises(UnsupportedEEError, match="50000"):
        reduce_moment_reducer(
            exhausted, MomentReducerLeaf("Reducer.skew"), [[0.0], [1.0]],
        )
    assert exhausted.steps == 49_968  # only the validated leaf description was charged

    called = False

    def should_not_run(values, order):
        nonlocal called
        called = True
        return 0.0

    monkeypatch.setattr(moment_reducers, "standardized_moment", should_not_run)
    near_limit = Budget(49_900)
    with pytest.raises(UnsupportedEEError, match="50000"):
        reduce_moment_reducer(
            near_limit, MomentReducerLeaf("Reducer.skew"), [[0.0]],
        )
    assert not called
    assert near_limit.steps == 49_918  # reservation failed before scanning or running the kernel
