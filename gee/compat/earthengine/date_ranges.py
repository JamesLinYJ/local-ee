"""Finite and explicitly unbounded static Earth Engine DateRange values.

Finite ranges retain the compiler's established ``(start_ms, end_ms)`` tuple
representation. The unbounded range has its own private typed value so that
infinity never leaks into the serialized or public JSON domains.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import math
from typing import Any

from .date_values import millis
from .ir import fail


DATE_RANGE_METHODS = frozenset({
    "DateRange.contains",
    "DateRange.end",
    "DateRange.intersection",
    "DateRange.intersects",
    "DateRange.isEmpty",
    "DateRange.isUnbounded",
    "DateRange.start",
    "DateRange.union",
    "DateRange.unbounded",
})

MAX_DATE_STRING_LENGTH = 200
MAX_DATE_RANGE_WORK = 50_000
MAX_EXACT_MILLIS = 2**53


@dataclass(frozen=True)
class UnboundedDateRange:
    """Internal marker for the range of all dates; never a public JSON value."""


UNBOUNDED_DATE_RANGE = UnboundedDateRange()


def is_date_range(value: Any) -> bool:
    """Return whether ``value`` uses one of the compiler's DateRange forms."""
    if isinstance(value, UnboundedDateRange):
        return True
    if not isinstance(value, tuple) or len(value) != 2:
        return False
    return all(_is_finite_millis(item) for item in value)


def validated_millis(translator, value, label="Date"):
    """Validate before Float64 conversion so nested Date calls cannot round integers."""
    _validate_date_input(value, label)
    _charge(translator, _date_work(value))
    result = millis(value)
    if not _is_finite_millis(result):
        fail(f"{label} must be finite and within ±2^53 milliseconds")
    return result


def invoke_date_range(translator, name: str, arguments: dict[str, Any]):
    """Evaluate one bounded DateRange constructor or static algebra method."""
    if name == "DateRange":
        translator.allowed(arguments, {"start", "end", "timeZone"})
        if "start" not in arguments:
            fail("DateRange requires start")
        if arguments.get("timeZone") not in (None, "UTC"):
            fail("Only UTC DateRange is supported")
        start_value = arguments["start"]
        end_value = arguments.get("end")
        _validate_date_input(start_value, "DateRange start")
        if end_value is not None:
            _validate_date_input(end_value, "DateRange end")
        _charge(translator, _date_work(start_value) + _date_work(end_value))
        start = millis(start_value)
        end = millis(end_value) if end_value is not None else start + 1
        if not _is_finite_millis(start) or not _is_finite_millis(end):
            fail("DateRange endpoints must be finite and within the exact millisecond domain")
        if end_value is None and end <= start:
            fail("DateRange default end must advance by one representable millisecond")
        return (start, end)

    if name not in DATE_RANGE_METHODS:
        fail(f"Unsupported Earth Engine DateRange algorithm: {name}")

    if name == "DateRange.unbounded":
        translator.allowed(arguments, set())
        _charge(translator, 1)
        return UNBOUNDED_DATE_RANGE

    if name in {"DateRange.start", "DateRange.end", "DateRange.isEmpty", "DateRange.isUnbounded"}:
        translator.allowed(arguments, {"dateRange"})
        if "dateRange" not in arguments:
            fail(f"{name} requires dateRange")
        value = _validated_range(arguments["dateRange"], "DateRange")
        _charge(translator, 1)
        if isinstance(value, UnboundedDateRange):
            if name in {"DateRange.start", "DateRange.end"}:
                endpoint = "start" if name.endswith("start") else "end"
                fail(f"DateRange.{endpoint} on an unbounded range is unsupported")
            return name.endswith("isUnbounded")
        start, end = value
        if name == "DateRange.start":
            return start
        if name == "DateRange.end":
            return end
        if name == "DateRange.isEmpty":
            return start >= end
        return False

    translator.allowed(arguments, {"dateRange", "other"})
    if "dateRange" not in arguments or "other" not in arguments:
        fail(f"{name} requires dateRange and other")
    left = _validated_range(arguments["dateRange"], "DateRange")
    right = _validated_other(
        arguments["other"], allow_date=name == "DateRange.contains",
    )
    _charge(translator, 1)

    if name == "DateRange.contains":
        if isinstance(left, UnboundedDateRange):
            return True
        left_start, left_end = left
        if isinstance(right, _DatePoint):
            return left_start < left_end and left_start <= right.value < left_end
        if isinstance(right, UnboundedDateRange):
            return False
        right_start, right_end = right
        if right_start >= right_end:
            return True
        return left_start < left_end and left_start <= right_start and right_end <= left_end

    if name == "DateRange.intersects":
        return _intersects(left, right)

    if name == "DateRange.intersection":
        if isinstance(left, UnboundedDateRange):
            return _intersection_with_unbounded(right)
        if isinstance(right, UnboundedDateRange):
            return left
        return _intersection(left, right)

    if name == "DateRange.union":
        if isinstance(left, UnboundedDateRange) or isinstance(right, UnboundedDateRange):
            return UNBOUNDED_DATE_RANGE
        return _union(left, right)

    fail(f"Unsupported Earth Engine DateRange algorithm: {name}")


@dataclass(frozen=True)
class _DatePoint:
    value: float


def _is_finite_millis(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if abs(value) > MAX_EXACT_MILLIS:
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _validate_date_input(value: Any, label: str) -> None:
    if isinstance(value, bool):
        fail(f"{label} must be a Date, string, or finite millisecond value")
    if isinstance(value, (int, float)):
        if not _is_finite_millis(value):
            fail(f"{label} must be finite and within ±2^53 milliseconds")
        return
    if isinstance(value, dt.datetime):
        return
    if isinstance(value, str):
        if len(value) > MAX_DATE_STRING_LENGTH:
            fail(f"{label} string exceeds {MAX_DATE_STRING_LENGTH} characters")
        return
    fail(f"{label} must be a Date, string, or finite millisecond value")


def _date_work(value: Any) -> int:
    return max(1, len(value)) if isinstance(value, str) else 1


def _charge(translator, amount: int) -> None:
    next_steps = translator.steps + amount
    if next_steps > MAX_DATE_RANGE_WORK:
        fail("Earth Engine graph exceeds compilation limits")
    translator.steps = next_steps


def _validated_range(value: Any, label: str):
    if isinstance(value, UnboundedDateRange):
        return value
    if not is_date_range(value):
        fail(f"{label} requires a finite DateRange or DateRange.unbounded()")
    return value


def _validated_other(value: Any, *, allow_date: bool):
    if isinstance(value, UnboundedDateRange):
        return value
    if is_date_range(value):
        return value
    if allow_date and _is_finite_millis(value):
        return _DatePoint(float(value))
    if allow_date:
        fail("DateRange.contains other must be a Date, finite millisecond value, or DateRange")
    fail("DateRange other must be a finite DateRange")


def _is_empty(value) -> bool:
    return not isinstance(value, UnboundedDateRange) and value[0] >= value[1]


def _intersects(left, right) -> bool:
    if isinstance(left, UnboundedDateRange):
        return isinstance(right, UnboundedDateRange) or not _is_empty(right)
    if _is_empty(left):
        return False
    if isinstance(right, UnboundedDateRange):
        return True
    return not _is_empty(right) and left[0] < right[1] and right[0] < left[1]


def _intersection_with_unbounded(value):
    if isinstance(value, UnboundedDateRange):
        return UNBOUNDED_DATE_RANGE
    return value


def _intersection(left, right):
    start = max(left[0], right[0])
    if _is_empty(left) or _is_empty(right):
        return (start, start)
    end = min(left[1], right[1])
    return (start, end) if start < end else (start, start)


def _union(left, right):
    left_empty, right_empty = _is_empty(left), _is_empty(right)
    if left_empty:
        return right if not right_empty else (left[0], left[0])
    if right_empty:
        return left
    return (min(left[0], right[0]), max(left[1], right[1]))
