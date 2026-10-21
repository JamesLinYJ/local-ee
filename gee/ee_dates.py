"""Static UTC implementations of selected Earth Engine Date algorithms.

This module is deliberately separate from the expression translator so the
parent compiler can route date invocations here without growing its dispatch
function. It evaluates only already-decoded scalar arguments; it never parses
or executes user code.
"""
from __future__ import annotations

import math
from typing import Any

from .compat.earthengine.ir import UnsupportedEEError, fail
from .compat.earthengine.date_values import millis, utc_date


SUPPORTED_DATE_FUNCTIONS = frozenset({"Date.difference", "Date.getRelative", "Date.getFraction"})

# Candidate local policy only: Joda-Time's UTC Gregorian chronology uses these
# average lengths, but no first-party source located here links the Earth Engine
# Date.difference implementation to those exact constants. Keep a user-visible
# warning on these units until a Google computed-value comparison is available.
_AVERAGE_YEAR_MS = 31_556_952_000
_AVERAGE_MONTH_MS = 2_629_746_000
_AVERAGE_DURATION_WARNING = (
    "Date.difference year/month currently uses the Joda Gregorian average-duration "
    "constants (365.2425 days/year and one twelfth per month) as a local strategy. "
    "Earth Engine documentation says only 'average length'; direct Google numerical "
    "parity has not been verified."
)
_CALENDAR_FRACTION_WARNING = (
    "Date.getFraction year/month uses actual UTC calendar lengths (365/366 days "
    "per year and the actual number of days per month) as a local strategy. "
    "Exact Earth Engine numerical parity has not been verified."
)
_SUBMILLISECOND_DIFFERENCE_WARNING = (
    "Date.difference preserves fractional-millisecond inputs as a local strategy; "
    "Earth Engine sub-millisecond rounding behavior has not been verified."
)
_SUBMILLISECOND_CALENDAR_ERROR = (
    "sub-millisecond precision because Earth Engine rounding behavior has not been verified"
)
_ISO_WEEK_WARNING = (
    "Date week fields use ISO Monday-based boundaries as a local strategy. "
    "Earth Engine documents week units but direct Google boundary parity has "
    "not been verified."
)
_DURATION_MS = {
    "week": 7 * 86_400_000,
    "day": 86_400_000,
    "hour": 3_600_000,
    "minute": 60_000,
    "second": 1_000,
}
_DIFFERENCE_MS = {
    "year": _AVERAGE_YEAR_MS,
    "month": _AVERAGE_MONTH_MS,
    **_DURATION_MS,
}
_UNIT_ORDER = {name: index for index, name in enumerate(
    ("year", "month", "week", "day", "hour", "minute", "second")
)}




def _unit(value: Any, label: str, *, plural: bool = False) -> str:
    if not isinstance(value, str):
        fail(f"Date {label} must be a string")
    unit = value[:-1] if plural and value.endswith("s") else value
    if unit not in _UNIT_ORDER:
        fail(f"Unsupported Date {label}: {value}")
    return unit


def _date_for_calendar(value: Any, label: str):

    value_ms = _validated_millis(value, label, allow_submillisecond=False)
    try:
        return utc_date(value_ms)
    except UnsupportedEEError:
        raise
    except (OverflowError, ValueError):
        fail(f"Date {label} is outside the supported calendar range (years 1..9999)")


def _validated_millis(value: Any, label: str, *, allow_submillisecond: bool) -> float:
    """Convert a date input while keeping numeric failures in the EE error type."""
    try:
        value_ms = millis(value)
    except OverflowError:
        fail(f"Date {label} milliseconds exceed the supported numeric range")
    if not math.isfinite(value_ms):
        fail(f"Date {label} milliseconds must be finite")
    if not allow_submillisecond and not value_ms.is_integer():
        fail(f"Date {label} has unsupported {_SUBMILLISECOND_CALENDAR_ERROR}")
    return value_ms


def _elapsed_millis(date, start) -> int:
    """Exact integer millisecond difference between UTC datetimes."""
    days = (date.date() - start.date()).days
    millis_of_day = ((date.hour * 60 + date.minute) * 60 + date.second) * 1000
    millis_of_day += date.microsecond // 1000
    start_of_day = ((start.hour * 60 + start.minute) * 60 + start.second) * 1000
    start_of_day += start.microsecond // 1000
    return days * 86_400_000 + millis_of_day - start_of_day


def _start_of(date, unit: str):
    import datetime as dt

    if unit == "year":
        return date.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    if unit == "month":
        return date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if unit == "week":
        return (date - dt.timedelta(days=date.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0)
    if unit == "day":
        return date.replace(hour=0, minute=0, second=0, microsecond=0)
    if unit == "hour":
        return date.replace(minute=0, second=0, microsecond=0)
    if unit == "minute":
        return date.replace(second=0, microsecond=0)
    raise AssertionError(unit)


def _get_relative(date, unit: str, in_unit: str) -> int:
    """Return relative unit counts for documented, unambiguous UTC pairs.

    Calendar week/year uses ISO week numbering. Week/month is rejected because
    the public EE description does not define a week-of-month boundary rule.
    """
    if _UNIT_ORDER[unit] < _UNIT_ORDER[in_unit]:
        # Earth Engine documents zero when the requested unit is larger than
        # its containing unit; the reference also demonstrates year/month.
        return 0
    if unit == in_unit:
        fail("Date.getRelative requires unit to be smaller than inUnit")

    if in_unit == "year" and unit == "month":
        return date.month - 1
    if in_unit == "year" and unit == "week":
        # ISO weeks start Monday and week 1 has at least four days.
        return date.isocalendar().week - 1
    if in_unit == "year" and unit == "day":
        return date.timetuple().tm_yday - 1

    if in_unit == "month" and unit == "week":
        fail("Date.getRelative('week', 'month') is unsupported: EE week-of-month boundary semantics are not specified")

    start = _start_of(date, in_unit)
    duration = _DURATION_MS.get(unit)
    if duration is None:
        fail(f"Unsupported Date.getRelative pair: {unit} in {in_unit}")
    return _elapsed_millis(date, start) // duration


def _get_fraction(date, unit: str) -> float:
    """Return elapsed fraction within the containing UTC calendar unit."""
    import calendar

    millis_of_day = ((date.hour * 60 + date.minute) * 60 + date.second) * 1000
    millis_of_day += date.microsecond // 1000
    if unit == "year":
        elapsed = (date.timetuple().tm_yday - 1) * 86_400_000 + millis_of_day
        duration = (366 if calendar.isleap(date.year) else 365) * 86_400_000
    elif unit == "month":
        elapsed = (date.day - 1) * 86_400_000 + millis_of_day
        duration = calendar.monthrange(date.year, date.month)[1] * 86_400_000
    elif unit == "week":
        # ISO calendar weeks begin Monday. Use weekday arithmetic directly so
        # the first supported calendar dates do not underflow on subtraction.
        elapsed = date.weekday() * 86_400_000 + millis_of_day
        duration = 7 * 86_400_000
    elif unit == "day":
        elapsed, duration = millis_of_day, 86_400_000
    elif unit == "hour":
        elapsed = (date.minute * 60 + date.second) * 1000 + date.microsecond // 1000
        duration = 3_600_000
    elif unit == "minute":
        elapsed = date.second * 1000 + date.microsecond // 1000
        duration = 60_000
    elif unit == "second":
        elapsed, duration = date.microsecond // 1000, 1_000
    else:
        raise AssertionError(unit)
    return elapsed / duration


def invoke_date(translator, name: str, arguments: dict[str, Any]):
    """Evaluate one supported Date algorithm using decoded static arguments.

    ``translator`` supplies the existing ``allowed(args, names)`` validation
    helper. Dynamic/computed dates are not coerced; callers must first decode
    them to local scalar values.
    """
    if name not in SUPPORTED_DATE_FUNCTIONS:
        fail(f"Unsupported Earth Engine date algorithm: {name}")
    if not isinstance(arguments, dict):
        fail("Date arguments must be an object")

    if name == "Date.difference":
        translator.allowed(arguments, {"date", "start", "unit"})
        if not {"date", "start", "unit"}.issubset(arguments):
            fail("Date.difference requires date, start, and unit")
        unit = _unit(arguments["unit"], "difference unit", plural=True)
        if unit not in _DIFFERENCE_MS:
            fail(f"Unsupported Date.difference unit: {arguments['unit']}")
        if unit in {"year", "month"}:
            translator.warn(_AVERAGE_DURATION_WARNING)
        date_ms = _validated_millis(arguments["date"], "difference date", allow_submillisecond=True)
        start_ms = _validated_millis(arguments["start"], "difference start", allow_submillisecond=True)
        if not date_ms.is_integer() or not start_ms.is_integer():
            translator.warn(_SUBMILLISECOND_DIFFERENCE_WARNING)
        result = (date_ms - start_ms) / _DIFFERENCE_MS[unit]
        if not math.isfinite(result):
            fail("Date.difference result is not finite")
        return result

    if name == "Date.getFraction":
        translator.allowed(arguments, {"date", "unit", "timeZone"})
        if not {"date", "unit"}.issubset(arguments):
            fail("Date.getFraction requires date and unit")
        if arguments.get("timeZone") not in (None, "UTC"):
            fail("Date.getFraction currently supports UTC only")
        unit = _unit(arguments["unit"], "fraction unit", plural=True)
        if unit not in _DIFFERENCE_MS:
            fail(f"Unsupported Date.getFraction unit: {arguments['unit']}")
        if unit in {"year", "month"}:
            translator.warn(_CALENDAR_FRACTION_WARNING)
        if unit == "week":
            translator.warn(_ISO_WEEK_WARNING)
        date = _date_for_calendar(arguments["date"], "getFraction input")
        return _get_fraction(date, unit)

    translator.allowed(arguments, {"date", "unit", "inUnit", "timeZone"})
    if not {"date", "unit", "inUnit"}.issubset(arguments):
        fail("Date.getRelative requires date, unit, and inUnit")
    if arguments.get("timeZone") not in (None, "UTC"):
        fail("Date.getRelative currently supports UTC only")
    unit = _unit(arguments["unit"], "relative unit", plural=True)
    in_unit = _unit(arguments["inUnit"], "containing unit", plural=True)
    if in_unit not in {"year", "month", "week", "day", "hour", "minute"}:
        fail(f"Unsupported Date.getRelative containing unit: {arguments['inUnit']}")
    if unit == "week" or in_unit == "week":
        translator.warn(_ISO_WEEK_WARNING)
    date = _date_for_calendar(arguments["date"], "getRelative input")
    return _get_relative(date, unit, in_unit)
