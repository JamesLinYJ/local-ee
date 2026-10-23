"""Bounded UTC parser for the Joda pattern subset used by Date.format."""
from __future__ import annotations

import calendar
import datetime as dt
import re

from .date_values import millis
from .ir import fail


_TOKENS = {
    "yyyy": "year", "YYYY": "year", "yy": "year2",
    "MM": "month", "M": "month", "dd": "day", "d": "day",
    "HH": "hour", "H": "hour", "mm": "minute", "m": "minute",
    "ss": "second", "s": "second", "SSS": "millis",
    "DDD": "dayofyear", "D": "dayofyear",
    "Z": "zone_basic", "ZZ": "zone_colon", "ZZZ": "zone_id",
}
_FIELD_TOKENS = {
    "year": "year", "year2": "year", "month": "month", "day": "day",
    "hour": "hour", "minute": "minute", "second": "second",
    "millis": "millis", "dayofyear": "dayofyear",
}


def _pattern_parts(pattern: str):
    if not isinstance(pattern, str) or not pattern or len(pattern) > 200:
        fail("Date.parse format must be a non-empty pattern of at most 200 characters")
    parts = []
    literal = []
    quoted = False
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == "'":
            if i + 1 < len(pattern) and pattern[i + 1] == "'":
                literal.append("'")
                i += 2
                continue
            if literal:
                parts.append(("".join(literal), "literal"))
                literal.clear()
            quoted = not quoted
            i += 1
            continue
        if quoted or not char.isalpha():
            literal.append(char)
            i += 1
            continue
        if literal:
            parts.append(("".join(literal), "literal"))
            literal.clear()
        end = i + 1
        while end < len(pattern) and pattern[end] == char:
            end += 1
        token = pattern[i:end]
        if token not in _TOKENS:
            fail(f"Unsupported Date.parse token: {token}")
        parts.append((token, _TOKENS[token]))
        i = end
    if quoted:
        fail("Unclosed Date.parse format literal")
    if literal:
        parts.append(("".join(literal), "literal"))

    fields = [_FIELD_TOKENS[meaning] for _, meaning in parts if meaning in _FIELD_TOKENS]
    if len(fields) != len(set(fields)):
        fail("Date.parse format repeats a calendar field")
    return parts


def _adjacent_numeric(parts, index):
    for neighbor in (index - 1, index + 1):
        if 0 <= neighbor < len(parts) and parts[neighbor][1] in _FIELD_TOKENS:
            return True
    return False


def _numeric_width(token, meaning):
    if meaning == "year":
        return 4
    if meaning == "year2":
        return 2
    if meaning == "millis":
        return 3
    if meaning == "dayofyear":
        return 3
    if meaning in {"month", "day", "hour", "minute", "second"}:
        # Single and doubled tokens both accept the practical calendar width
        # when separated from other fields (for example MM may parse 2).
        return 2
    return None


def _adjacent_width(token, meaning):
    """Return a fixed width only when adjacency makes a token unambiguous."""
    if meaning in {"year", "year2", "millis"}:
        return _numeric_width(token, meaning)
    if meaning == "dayofyear":
        return 3 if token == "DDD" else None
    widths = {
        "MM": 2, "dd": 2, "HH": 2, "mm": 2, "ss": 2,
    }
    return widths.get(token)


def _compile_pattern(parts):
    chunks = []
    captures = []
    for i, (token, meaning) in enumerate(parts):
        if meaning == "literal":
            chunks.append(re.escape(token))
            continue
        if meaning.startswith("zone_"):
            zone = {"zone_basic": r"\+0000", "zone_colon": r"\+00:00", "zone_id": "UTC"}[meaning]
            chunks.append(f"({zone})")
            captures.append((i, meaning))
            continue
        width = _numeric_width(token, meaning)
        if _adjacent_numeric(parts, i):
            fixed_width = _adjacent_width(token, meaning)
            if fixed_width is None:
                fail(f"Date.parse token {token} is ambiguous beside another numeric field")
            digits = f"[0-9]{{{fixed_width}}}"
        elif meaning == "millis":
            digits = r"[0-9]{3}"
        elif meaning == "year2":
            digits = r"[0-9]{2}"
        else:
            if width is None:
                fail(f"Date.parse token {token} has no supported numeric width")
            digits = f"[0-9]{{1,{width}}}"
        chunks.append(f"({digits})")
        captures.append((i, meaning))
    return re.compile("".join(chunks)), captures


def parse_joda_date(pattern: str, value: str, translator=None) -> float:
    """Parse a full value using supported numeric Joda tokens and UTC only.

    The grammar intentionally excludes locale text, week-year tokens, and
    non-UTC zone IDs. It is bounded to 200 characters in both inputs.
    """
    if not isinstance(value, str) or len(value) > 200:
        fail("Date.parse date must be a string of at most 200 characters")
    parts = _pattern_parts(pattern)
    meanings = {meaning for _, meaning in parts}
    if "year2" in meanings and translator is not None:
        translator.warn(
            "Date.parse yy uses a fixed 1950..2049 pivot for deterministic local parsing; "
            "Google's Joda pivot parity has not been verified."
        )
    if any(token == "YYYY" for token, _ in parts) and translator is not None:
        translator.warn(
            "Date.parse YYYY is treated as a calendar year to match the local Date.format "
            "subset; Joda week/year-era edge semantics are not supported."
        )
    regex, captures = _compile_pattern(parts)
    match = regex.fullmatch(value)
    if match is None:
        fail("Date.parse input does not match the supported UTC pattern")

    parsed = {}
    for group, (_, meaning) in enumerate(captures, 1):
        text = match.group(group)
        if meaning.startswith("zone_"):
            continue
        parsed[meaning] = int(text)

    has_dayofyear = "dayofyear" in parsed
    if has_dayofyear and ("month" in parsed or "day" in parsed):
        fail("Date.parse cannot mix day-of-year with month/day fields")
    year = parsed.get("year")
    if "year2" in parsed:
        # A fixed 1950..2049 pivot keeps the offline result reproducible.
        year = 2000 + parsed["year2"]
        if year > 2049:
            year -= 100
    if year is None:
        year = 2000 if has_dayofyear or "month" in parsed or "day" in parsed else 1970
    if not 1 <= year <= 9999:
        fail("Date.parse year is outside the supported range (1..9999)")

    second = parsed.get("second", 0)
    if not 0 <= second <= 59:
        fail("Date.parse second must be in 0..59")
    try:
        if has_dayofyear:
            ordinal = parsed["dayofyear"]
            days_in_year = 366 if calendar.isleap(year) else 365
            if not 1 <= ordinal <= days_in_year:
                fail("Date.parse day-of-year is invalid for the calendar year")
            date = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=ordinal - 1)
        else:
            date = dt.datetime(
                year, parsed.get("month", 1), parsed.get("day", 1),
                tzinfo=dt.timezone.utc,
            )
        date = date.replace(
            hour=parsed.get("hour", 0), minute=parsed.get("minute", 0),
            second=second, microsecond=parsed.get("millis", 0) * 1000,
        )
    except (OverflowError, ValueError) as error:
        fail(f"Date.parse contains an invalid calendar date or time: {error}")
    return millis(date)
