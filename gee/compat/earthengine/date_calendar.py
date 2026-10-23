"""Finite UTC implementations for selected Earth Engine Date algorithms."""
from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal, InvalidOperation
import math
from typing import Any

from .date_calendar_parse import parse_joda_date
from .date_values import millis, utc_date
from .ir import fail, integer


SUPPORTED_DATE_CALENDAR_FUNCTIONS = frozenset({
    "Date.parse", "Date.update", "Date.getRange", "Date.unitRatio",
})

_DAY_MS = 86_400_000
_MAX_TRANSLATOR_WORK = 50_000
_MAX_DATE_TEXT = 200
_AVERAGE_YEAR_MS = 31_556_952_000
_AVERAGE_MONTH_MS = 2_629_746_000
_UNIT_MILLIS = {
    "year": _AVERAGE_YEAR_MS, "month": _AVERAGE_MONTH_MS,
    "week": 7 * _DAY_MS, "day": _DAY_MS, "hour": 3_600_000,
    "minute": 60_000, "second": 1_000,
}
_CALENDAR_UNITS = frozenset({"year", "month", "week", "day", "hour", "minute", "second"})
_WEEK_RANGE_WARNING = (
    "Date.getRange week uses ISO Monday-based boundaries as a local policy; "
    "Google week-boundary parity has not been verified."
)
_UPDATE_CLAMP_WARNING = (
    "Date.update clamps an inherited day to the last valid day after a year/month "
    "change as a local policy; Google rollover behavior has not been verified."
)
_UPDATE_FRACTION_WARNING = (
    "Date.update fractional seconds are converted to exact milliseconds as a local "
    "policy; direct Google numerical parity has not been verified."
)
_UNIT_RATIO_WARNING = (
    "Date.unitRatio year/month uses Joda ISO average-duration constants as a local "
    "policy; Google year/month numerical parity has not been verified."
)


def _charge_work(translator, amount: int, label: str) -> None:
    if (type(amount) is not int or amount < 0
            or translator.steps + amount > _MAX_TRANSLATOR_WORK):
        fail(f"{label} exceeds the 50000-step compilation work budget")
    translator.steps += amount


def _argument_shape(arguments: dict[str, Any]) -> None:
    """Bound the small object/key scan performed by allowed()."""
    if type(arguments) is not dict:
        fail("Date arguments must be an object")
    if len(arguments) > 10:
        fail("Date arguments exceed the bounded argument count")
    for key in arguments:
        if type(key) is not str or len(key) > 32:
            fail("Date argument names must be short strings")


def _text_size(value: Any, label: str) -> int:
    if type(value) is not str:
        fail(f"Date {label} must be a string")
    return len(value)


def _charge_calendar_input(translator, value: Any, label: str) -> None:
    if type(value) is str:
        size = _text_size(value, label)
        _charge_work(translator, min(size, _MAX_DATE_TEXT), f"Date {label}")
        if size > _MAX_DATE_TEXT:
            fail(f"Date {label} exceeds 200 characters")
    else:
        # Scalar milliseconds and datetime objects take a constant conversion
        # path; charge it explicitly before conversion or calendar arithmetic.
        _charge_work(translator, 1, f"Date {label}")


def _time_zone(arguments: dict[str, Any]):
    zone = arguments.get("timeZone")
    if zone is not None and (
        type(zone) is not str or len(zone) != 3 or zone != "UTC"
    ):
        fail("Date calendar operations currently support UTC only")


def _calendar_date(value: Any, label: str) -> tuple[float, dt.datetime]:
    try:
        value_ms = millis(value)
    except OverflowError:
        fail(f"Date {label} milliseconds exceed the supported numeric range")
    if not math.isfinite(value_ms):
        fail(f"Date {label} milliseconds must be finite")
    if not value_ms.is_integer():
        fail(f"Date {label} has unsupported sub-millisecond precision")
    try:
        return value_ms, utc_date(value_ms)
    except (OverflowError, ValueError):
        fail(f"Date {label} is outside the supported calendar range (years 1..9999)")


def _unit(value: Any, label: str) -> str:
    if type(value) is not str or len(value) > 6 or value not in _CALENDAR_UNITS:
        fail(f"Unsupported Date {label}")
    return value


def _calendar_integer(value: Any, label: str) -> int:
    try:
        return integer(value, label)
    except OverflowError:
        fail(f"{label} exceeds the supported integer range")


def _range(date: dt.datetime, unit: str) -> tuple[float, float]:
    if unit == "year":
        start = date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        length = (366 if calendar.isleap(date.year) else 365) * _DAY_MS
    elif unit == "month":
        start = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        length = calendar.monthrange(date.year, date.month)[1] * _DAY_MS
    elif unit == "week":
        midnight = date.replace(hour=0, minute=0, second=0, microsecond=0)
        start = midnight - dt.timedelta(days=date.weekday())
        length = 7 * _DAY_MS
    elif unit == "day":
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        length = _DAY_MS
    elif unit == "hour":
        start = date.replace(minute=0, second=0, microsecond=0)
        length = 3_600_000
    elif unit == "minute":
        start = date.replace(second=0, microsecond=0)
        length = 60_000
    else:
        start = date.replace(microsecond=0)
        length = 1_000
    start_ms = millis(start)
    # Add milliseconds directly so a range ending in year 10000 is representable
    # even though the local datetime decoder deliberately ends at year 9999.
    return start_ms, start_ms + length


def _updated_date(translator, date_value: Any, arguments: dict[str, Any]) -> float:
    _charge_calendar_input(translator, date_value, "update input")
    value_ms, date = _calendar_date(date_value, "update input")
    field_names = ("year", "month", "day", "hour", "minute")
    updates = {
        name: _calendar_integer(arguments[name], f"Date.update {name}")
        for name in field_names if arguments.get(name) is not None
    }
    second_value = arguments.get("second")
    second_ms = None
    if second_value is not None:
        if isinstance(second_value, bool) or not isinstance(second_value, (int, float)):
            fail("Date.update second must be a finite number")
        try:
            seconds = Decimal(str(second_value))
        except InvalidOperation:
            fail("Date.update second must be a finite number")
        if not seconds.is_finite() or seconds < 0 or seconds >= 60:
            fail("Date.update second must be in [0, 60)")
        scaled = seconds * 1000
        if scaled != scaled.to_integral_value():
            fail("Date.update second exceeds millisecond precision")
        if seconds != seconds.to_integral_value():
            translator.warn(_UPDATE_FRACTION_WARNING)
        second_ms = int(scaled)
    if not updates and second_ms is None:
        return value_ms

    year = updates.get("year", date.year)
    month = updates.get("month", date.month)
    if not 1 <= year <= 9999:
        fail("Date.update year must be in 1..9999")
    if not 1 <= month <= 12:
        fail("Date.update month must be in 1..12")
    day = updates.get("day", date.day)
    last_day = calendar.monthrange(year, month)[1]
    if not 1 <= day <= last_day:
        if "day" in updates or (year, month) == (date.year, date.month):
            fail("Date.update day is invalid for the selected month")
        day = last_day
        translator.warn(_UPDATE_CLAMP_WARNING)

    hour = updates.get("hour", date.hour)
    minute = updates.get("minute", date.minute)
    if not 0 <= hour <= 23:
        fail("Date.update hour must be in 0..23")
    if not 0 <= minute <= 59:
        fail("Date.update minute must be in 0..59")
    if second_ms is None:
        second, microsecond = date.second, date.microsecond
    else:
        second, millisecond = divmod(second_ms, 1000)
        microsecond = millisecond * 1000
    try:
        updated = date.replace(
            year=year, month=month, day=day, hour=hour, minute=minute,
            second=second, microsecond=microsecond,
        )
    except (OverflowError, ValueError):
        fail("Date.update fields are outside the supported calendar range")
    result = millis(updated)
    if not math.isfinite(result):
        fail("Date.update result is not finite")
    return result


def invoke_date_calendar(translator, name: str, arguments: dict[str, Any]):
    """Evaluate one finite Date algorithm from already-decoded scalar values.

    Date values are UTC epoch milliseconds and DateRange values are half-open
    ``(start_ms, end_ms)`` tuples, matching the existing value representation.
    """
    if type(name) is not str or name not in SUPPORTED_DATE_CALENDAR_FUNCTIONS:
        fail(f"Unsupported Earth Engine date calendar algorithm: {name}")
    # Charge even direct handler calls (the public Translator path also has
    # its ordinary graph-evaluation cost). This is deliberately before key
    # enumeration, text checks, regex compilation, or datetime conversion.
    _charge_work(translator, 1, "Date calendar operation")
    _argument_shape(arguments)

    if name == "Date.parse":
        translator.allowed(arguments, {"format", "date", "timeZone"})
        if not {"format", "date"}.issubset(arguments):
            fail("Date.parse requires format and date")
        format_size = _text_size(arguments["format"], "parse format")
        date_size = _text_size(arguments["date"], "parse input")
        _charge_work(
            translator,
            min(format_size, _MAX_DATE_TEXT) + min(date_size, _MAX_DATE_TEXT),
            "Date.parse",
        )
        if format_size > _MAX_DATE_TEXT:
            fail("Date.parse format exceeds 200 characters")
        if date_size > _MAX_DATE_TEXT:
            fail("Date.parse input exceeds 200 characters")
        _time_zone(arguments)
        return parse_joda_date(arguments["format"], arguments["date"], translator)

    if name == "Date.update":
        translator.allowed(arguments, {
            "date", "year", "month", "day", "hour", "minute", "second", "timeZone",
        })
        if "date" not in arguments:
            fail("Date.update requires date")
        _time_zone(arguments)
        return _updated_date(translator, arguments["date"], arguments)

    if name == "Date.getRange":
        translator.allowed(arguments, {"date", "unit", "timeZone"})
        if not {"date", "unit"}.issubset(arguments):
            fail("Date.getRange requires date and unit")
        _time_zone(arguments)
        unit = _unit(arguments["unit"], "getRange unit")
        _charge_calendar_input(translator, arguments["date"], "getRange input")
        _, date = _calendar_date(arguments["date"], "getRange input")
        if unit == "week":
            translator.warn(_WEEK_RANGE_WARNING)
        return _range(date, unit)

    translator.allowed(arguments, {"numerator", "denominator"})
    if not {"numerator", "denominator"}.issubset(arguments):
        fail("Date.unitRatio requires numerator and denominator")
    numerator = _unit(arguments["numerator"], "unitRatio numerator")
    denominator = _unit(arguments["denominator"], "unitRatio denominator")
    if numerator in {"year", "month"} or denominator in {"year", "month"}:
        if numerator != denominator:
            translator.warn(_UNIT_RATIO_WARNING)
    return _UNIT_MILLIS[numerator] / _UNIT_MILLIS[denominator]
