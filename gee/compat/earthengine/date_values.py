"""UTC date decoding and the explicitly supported Joda format subset."""
from __future__ import annotations

import datetime as dt
import math
import re

from .ir import fail


def millis(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            fail("Date milliseconds must be finite")
        return float(value)
    if isinstance(value, dt.datetime):
        date = value
    elif isinstance(value, str):
        try:
            if re.fullmatch(r"\d{4}", value):
                value += "-01-01"
            elif re.fullmatch(r"\d{4}-\d{2}", value):
                value += "-01"
            date = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            fail(f"Unsupported date: {value}")
    else:
        fail("Date requires a string or UTC milliseconds")
    if date.tzinfo is None:
        date = date.replace(tzinfo=dt.timezone.utc)
    difference = date.astimezone(dt.timezone.utc) - dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    return (difference.days * 86400 + difference.seconds) * 1000 + difference.microseconds / 1000


def time_of(item):
    properties = item.get("properties", {})
    return millis(properties.get("system:time_start", properties.get("datetime")))


def utc_date(value):
    return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(milliseconds=millis(value))


def format_date(date, pattern):
    """Explicit small Joda-format subset; never treat unknown tokens as literals."""
    tokens = {
        "yyyy": f"{date.year:04}", "YYYY": f"{date.year:04}", "yy": f"{date.year % 100:02}",
        "MM": f"{date.month:02}", "M": str(date.month), "dd": f"{date.day:02}", "d": str(date.day),
        "HH": f"{date.hour:02}", "H": str(date.hour), "mm": f"{date.minute:02}", "m": str(date.minute),
        "ss": f"{date.second:02}", "s": str(date.second), "SSS": f"{date.microsecond // 1000:03}",
        "DDD": f"{date.timetuple().tm_yday:03}", "D": str(date.timetuple().tm_yday),
        "Z": "+0000", "ZZ": "+00:00", "ZZZ": "UTC",
    }
    if not isinstance(pattern, str) or len(pattern) > 200:
        fail("Date.format requires a pattern of at most 200 characters")
    out = []
    i = 0
    literal = False
    while i < len(pattern):
        char = pattern[i]
        if char == "'":
            if i + 1 < len(pattern) and pattern[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            literal = not literal
            i += 1
            continue
        if literal or not char.isalpha():
            out.append(char)
            i += 1
            continue
        end = i + 1
        while end < len(pattern) and pattern[end] == char:
            end += 1
        token = pattern[i:end]
        if token not in tokens:
            fail(f"Unsupported Date.format token: {token}")
        out.append(tokens[token])
        i = end
    if literal:
        fail("Unclosed Date.format literal")
    return "".join(out)
