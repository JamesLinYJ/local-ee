"""Static values, constructors, dates and inline geometry operations."""
from __future__ import annotations

import calendar
import datetime as dt
import re

from .date_values import format_date, millis, utc_date
from .ir import Region, fail, integer
from .string_values import construct_string


VALUE_HANDLERS = frozenset({
    "Date", "DateRange", "Date.millis", "Date.advance", "Date.fromYMD", "Date.get", "Date.format",
    "Projection", "Projection.crs", "Feature", "Collection", "FeatureCollection",
    "Number", "String", "List", "Dictionary",
})


def handles_value(name):
    return (
        name in VALUE_HANDLERS
        or name.startswith("GeometryConstructors.")
        or name.startswith(("Number.", "String.", "List.", "Dictionary."))
    )


def invoke_value(translator, name, arguments):
    a = arguments
    if name == "Date":
        translator.allowed(a, {"value", "timeZone"})
        if a.get("timeZone") not in (None, "UTC"):
            fail("Only UTC Date is supported")
        return millis(a["value"])
    if name == "Projection":
        translator.allowed(a, {"crs", "transform", "transformWkt"})
        if a.get("transform") is not None or a.get("transformWkt") is not None:
            fail("Projection transforms are unsupported")
        crs = a["crs"]
        if not isinstance(crs, str) or not re.fullmatch(r"EPSG:\d+", crs):
            fail("Projection requires an EPSG code")
        return crs
    if name == "Projection.crs":
        translator.allowed(a, {"projection"})
        return a["projection"]
    if name == "DateRange":
        translator.allowed(a, {"start", "end", "timeZone"})
        if a.get("timeZone") not in (None, "UTC"):
            fail("Only UTC DateRange is supported")
        start = millis(a["start"])
        return start, millis(a["end"]) if a.get("end") is not None else start + 1
    if name == "Date.millis":
        return a["date"]
    if name == "Date.advance":
        translator.allowed(a, {"date", "delta", "unit", "timeZone"})
        if a.get("timeZone") not in (None, "UTC"):
            fail("Only UTC dates are supported")
        factors = {
            "millisecond": 1, "second": 1000, "minute": 60000,
            "hour": 3600000, "day": 86400000, "week": 604800000,
        }
        unit = a["unit"].removesuffix("s")
        if unit in {"month", "year"}:
            delta = integer(a["delta"], "Calendar Date.advance delta")
            date = utc_date(a["date"])
            month_index = date.year * 12 + date.month - 1 + delta * (12 if unit == "year" else 1)
            year, month = divmod(month_index, 12)
            month += 1
            if not 1 <= year <= 9999:
                fail("Date.advance year is outside 1..9999")
            day = min(date.day, calendar.monthrange(year, month)[1])
            return millis(date.replace(year=year, month=month, day=day))
        if unit not in factors:
            fail("Unsupported Date.advance unit")
        return a["date"] + a["delta"] * factors[unit]
    if name in {"Date.fromYMD", "Date.get", "Date.format"}:
        allowed = (
            {"year", "month", "day", "timeZone"}
            if name.endswith("fromYMD")
            else {"date", "unit", "timeZone"}
            if name.endswith("get")
            else {"date", "format", "timeZone"}
        )
        translator.allowed(a, allowed)
        if a.get("timeZone") not in (None, "UTC"):
            fail("Only UTC dates are supported")
        if name.endswith("fromYMD"):
            parts = (integer(a[key], "Date " + key) for key in ("year", "month", "day"))
            return millis(dt.datetime(*parts, tzinfo=dt.timezone.utc))
        date = utc_date(a["date"])
        if name.endswith("get"):
            fields = {
                "year": date.year, "month": date.month, "day": date.day,
                "hour": date.hour, "minute": date.minute, "second": date.second,
            }
            if a["unit"] not in fields:
                fail("Unsupported Date.get unit")
            return fields[a["unit"]]
        return format_date(date, a.get("format") or "yyyy-MM-dd'T'HH:mm:ss.SSSZZ")
    if name == "Feature":
        translator.allowed(a, {"geometry", "metadata"})
        if isinstance(a.get("metadata"), Region):
            if a.get("geometry") is not None:
                fail("A reduceRegion Feature export wrapper currently requires null geometry")
            return a["metadata"]
        return {"type": "Feature", "geometry": a.get("geometry"), "properties": a.get("metadata", {})}
    if name in {"Collection", "FeatureCollection"}:
        translator.allowed(a, {"features"})
        features = a.get("features")
        if not isinstance(features, list):
            fail("FeatureCollection requires an inline feature list")
        if len(features) == 1 and isinstance(features[0], Region):
            return features[0]
        if not all(isinstance(feature, dict) and feature.get("type") == "Feature" for feature in features):
            fail("Only static Features or one reduceRegion Feature can be exported as a FeatureCollection")
        return {"type": "FeatureCollection", "features": features}
    if name.startswith("GeometryConstructors."):
        from .geometry_values import construct_geometry

        return construct_geometry(translator, name.split(".", 1)[1], a)
    if name == "String":
        translator.allowed(a, {"input"})
        return construct_string(translator, a)
    if name in {"Number", "List", "Dictionary"}:
        translator.allowed(a, {"input", "value", "values", "dictionary"})
        if len(a) != 1:
            fail(f"{name} requires exactly one static constructor value")
        return a.get("input", a.get("value", a.get("values", a.get("dictionary"))))
    if name.startswith(("Number.", "String.", "List.", "Dictionary.")):
        return translator.static(name, a)
    fail(f"Unsupported Earth Engine algorithm: {name}")
