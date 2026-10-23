"""Precharged scalar and reducer dispatch for aggregate statistics."""
from __future__ import annotations

import math

from .aggregate_statistics_numeric import (
    numeric_dispersion,
    numeric_mean,
    numeric_sum,
    numeric_sum_squares,
    numeric_variances,
)
from .ir import fail


MAX_WORK = 50_000
MAX_PUBLIC_BYTES = 1_000_000
MAX_EXACT_INTEGER = 2**53
_NUMERIC = frozenset({
    "AggregateFeatureCollection.mean",
    "AggregateFeatureCollection.product",
    "AggregateFeatureCollection.sum",
    "AggregateFeatureCollection.sample_sd",
    "AggregateFeatureCollection.sample_var",
    "AggregateFeatureCollection.total_sd",
    "AggregateFeatureCollection.total_var",
    "AggregateFeatureCollection.stats",
})


def charge(translator, work, label="FeatureCollection aggregate"):
    if (type(work) is not int or work < 0 or work > MAX_WORK
            or translator.steps + work > MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps += work


def _json_string_size(value):
    """Measure json.dumps(..., ensure_ascii=True) string size without copying."""
    size = len(value) + 2
    for character in value:
        code = ord(character)
        if character in {'"', "\\", "\b", "\f", "\n", "\r", "\t"}:
            size += 1
        elif code < 32 or code >= 127:
            size += 5 if code <= 0xffff else 11
    return size


def _public_scalar_size(value):
    if value is None:
        return 4
    if type(value) is bool:
        return 4 if value else 5
    if type(value) is str:
        return _json_string_size(value)
    if type(value) is int:
        bits = value.bit_length()
        return max(1, math.ceil(bits * math.log10(2))) + (1 if value < 0 else 0)
    if type(value) is float:
        if not math.isfinite(value):
            fail("Aggregate output must be finite")
        return 24
    fail("Aggregate output must be a scalar JSON value")


def result_scalar(translator, value, label):
    if type(value) is str:
        charge(translator, len(value), label)
    elif type(value) is int:
        charge(translator, max(1, value.bit_length()), label)
    size = _public_scalar_size(value)
    if size > MAX_PUBLIC_BYTES:
        fail(f"{label} output exceeds the 1 MB public JSON limit")
    charge(translator, size, label)
    return value


def _scalar(value, method):
    if value is None:
        return None
    if type(value) is str or type(value) is bool:
        return value
    if type(value) is int:
        if abs(value) > MAX_EXACT_INTEGER:
            fail(f"{method} integer properties must be within the exact ±2^53 range")
        return value
    if type(value) is float:
        if not math.isfinite(value):
            fail(f"{method} properties must be finite")
        return value
    fail(f"{method} supports only scalar string, boolean, or numeric properties")


def _numeric_values(values, method):
    numbers = []
    for value in values:
        if value is None:
            continue
        value = _scalar(value, method)
        if type(value) not in (int, float):
            fail(f"{method} requires homogeneous numeric properties or null/missing values")
        numbers.append(value)
    return numbers


def _ordered_values(translator, values, method):
    present = []
    for value in values:
        if value is not None:
            present.append(_scalar(value, method))
    if not present:
        return present
    if all(type(value) in (int, float) for value in present):
        return present
    if not all(type(value) is str for value in present):
        fail(f"{method} requires all non-null properties to be numeric or all strings")
    for value in present:
        # Reserve comparison/string handling before min/max scan the text.
        charge(translator, len(value), method)
    return present


def _count_distinct(translator, values):
    distinct = set()
    for value in values:
        charge(translator, 8, "aggregate_count_distinct")
        if value is None:
            continue
        value = _scalar(value, "aggregate_count_distinct")
        if type(value) is str:
            charge(translator, len(value), "aggregate_count_distinct string hash")
            identity = ("string", value)
        elif type(value) is bool:
            identity = ("boolean", value)
        elif type(value) in (int, float):
            identity = ("number", float(value))
        else:
            fail("aggregate_count_distinct supports only scalar strings, booleans, and numbers")
        distinct.add(identity)
    return len(distinct)


def _stats_result(translator, numbers, row_count):
    mean = numeric_mean(numbers) if numbers else None
    total_var, sample_var, total_sd, sample_sd = numeric_variances(numbers)
    total = numeric_sum(numbers) if numbers else 0.0
    sum_sq = numeric_sum_squares(numbers) if numbers else 0.0
    fields = (
        ("max", max(numbers) if numbers else None),
        ("mean", mean),
        ("min", min(numbers) if numbers else None),
        ("sample_sd", sample_sd),
        ("sample_var", sample_var),
        ("sum", total),
        ("sum_sq", sum_sq),
        ("total_count", row_count),
        ("total_sd", total_sd),
        ("total_var", total_var),
        ("valid_count", len(numbers)),
        ("weight_sum", len(numbers)),
        ("weighted_sum", total),
    )
    output_size = 2 + 2 * (len(fields) - 1)
    for key, value in fields:
        charge(translator, len(key), "aggregate_stats key size scan")
        if type(value) is int:
            charge(translator, max(1, value.bit_length()), "aggregate_stats integer size scan")
        output_size += _json_string_size(key) + 1 + _public_scalar_size(value)
    if output_size > MAX_PUBLIC_BYTES:
        fail("aggregate_stats output exceeds the 1 MB public JSON limit")
    charge(translator, output_size, "aggregate_stats output")
    return dict(fields)


def aggregate_statistics_value(translator, name, values, row_count):
    """Apply one requested aggregate after the bounded metadata scan."""
    if name == "AggregateFeatureCollection.first":
        charge(translator, 1, name)
        value = _scalar(values[0] if values else None, "aggregate_first")
        return result_scalar(translator, value, "aggregate_first")
    if name == "AggregateFeatureCollection.count":
        charge(translator, len(values), name)
        return result_scalar(translator, sum(value is not None for value in values), name)
    if name == "AggregateFeatureCollection.count_distinct":
        return result_scalar(translator, _count_distinct(translator, values), name)
    if name == "AggregateFeatureCollection.histogram":
        from .aggregate_statistics_histogram import aggregate_histogram

        return aggregate_histogram(translator, values)
    if name in {"AggregateFeatureCollection.min", "AggregateFeatureCollection.max"}:
        charge(translator, 8 * len(values), name)
        ordered = _ordered_values(translator, values, name)
        is_min = name.endswith(".min")
        result = (min(ordered) if is_min else max(ordered)) if ordered else None
        return result_scalar(translator, result, name)
    if name in _NUMERIC:
        # This reserve covers row filtering/copying, validation and the
        # selected numeric kernel. It precedes all work-array construction.
        charge(translator, 12 * row_count + 16, name)
        numbers = _numeric_values(values, name)
        if name == "AggregateFeatureCollection.sum":
            result = numeric_sum(numbers) if numbers else 0.0
        elif name == "AggregateFeatureCollection.product":
            result = 1.0
            for number in numbers:
                result *= float(number)
                if not math.isfinite(result):
                    fail("Aggregate product is outside the finite numeric range")
        elif name == "AggregateFeatureCollection.stats":
            return _stats_result(translator, numbers, row_count)
        elif name == "AggregateFeatureCollection.mean":
            result = numeric_mean(numbers)
        else:
            sample = name in {
                "AggregateFeatureCollection.sample_var",
                "AggregateFeatureCollection.sample_sd",
            }
            standard_deviation = name in {
                "AggregateFeatureCollection.sample_sd",
                "AggregateFeatureCollection.total_sd",
            }
            result = numeric_dispersion(
                numbers, sample=sample, standard_deviation=standard_deviation,
            )
        return result_scalar(translator, result, name)
    fail(f"Unsupported aggregate statistic: {name}")
