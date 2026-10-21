"""Bounded static Number.format for explicit decimal/string printf forms."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import math
import re

from .ir import fail


_PATTERN = re.compile(
    r"(?P<prefix>[^%]*)%(?P<flags>[-+ 0,#(]*)(?P<width>[0-9]+)?"
    r"(?:\.(?P<precision>[0-9]+))?(?P<conversion>[sdf])(?P<suffix>[^%]*)"
)
MAX_FORMAT_SIZE = 10000
MAX_FIELD_SIZE = 1000


def format_number(translator, arguments):
    """Format finite scalars; reject unimplemented conversions/flags explicitly.

    Decimal output uses ROUND_HALF_UP on the scalar's shortest Python decimal
    spelling. This bounded local rounding policy has no Google comparison;
    scientific/hex/general formatting and grouping remain unsupported.
    """
    translator.allowed(arguments, {"number", "pattern"})
    number = arguments.get("number")
    if type(number) not in (int, float):
        fail("Number.format requires a finite static Number")
    try:
        finite = math.isfinite(number)
    except OverflowError:
        finite = False
    if not finite or type(number) is int and not -(2**63) <= number < 2**63:
        fail("Number.format requires a finite Number within the supported integer domain")
    pattern = arguments.get("pattern")
    pattern = "%s" if pattern is None else pattern
    if not isinstance(pattern, str) or len(pattern) > MAX_FORMAT_SIZE:
        fail("Number.format pattern must be a string of at most 10000 characters")
    match = _PATTERN.fullmatch(pattern)
    if match is None:
        fail("Number.format supports one bounded %s, %d or %f conversion")
    parts = match.groupdict()
    flags = parts["flags"]
    if len(set(flags)) != len(flags) or set(flags) - set("-+ 0"):
        fail("Unsupported or repeated Number.format flags")
    if "+" in flags and " " in flags or "-" in flags and "0" in flags:
        fail("Conflicting Number.format flags")
    # Bound digit counts before int() so malicious widths never allocate a
    # giant integer or rely on the interpreter's decimal conversion limit.
    for key in ("width", "precision"):
        if parts[key] is not None and len(parts[key]) > 4:
            fail("Number.format width/precision exceeds 1000")
    width = int(parts["width"]) if parts["width"] is not None else 0
    precision = int(parts["precision"]) if parts["precision"] is not None else None
    if width > MAX_FIELD_SIZE or precision is not None and precision > MAX_FIELD_SIZE:
        fail("Number.format width/precision exceeds 1000")
    if ("-" in flags or "0" in flags) and not width:
        fail("Number.format padding flags require a positive width")
    conversion = parts["conversion"]
    if conversion == "s":
        if set(flags) - {"-"}:
            fail("Unsupported Number.format string conversion flags")
        body = str(number)
        if type(number) is float and "e" in body.lower():
            fail("Number.format scientific string spelling is not verified")
        if precision is not None:
            body = body[:precision]
        sign = ""
    else:
        negative = number < 0 or type(number) is float and math.copysign(1, number) < 0
        sign = "-" if negative else "+" if "+" in flags else " " if " " in flags else ""
        if conversion == "d":
            if precision is not None:
                fail("Number.format %d does not accept precision")
            if int(number) != number or not -(2**63) <= number < 2**63:
                fail("Number.format %d currently requires an exact signed-64-bit integer")
            body = str(abs(int(number)))
            if int(number) == 0 and negative:
                sign = "+" if "+" in flags else " " if " " in flags else ""
        else:
            precision = 6 if precision is None else precision
            decimal = Decimal(str(number)).copy_abs()
            try:
                with localcontext() as context:
                    context.prec = max(64, decimal.adjusted() + precision + 4)
                    rounded = decimal.quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
                    body = format(rounded, f".{precision}f")
            except InvalidOperation:
                fail("Number.format decimal rounding exceeds the supported domain")
    text = sign + body
    if len(text) < width:
        padding = width - len(text)
        if "-" in flags:
            text += " " * padding
        elif "0" in flags:
            text = sign + "0" * padding + body
        else:
            text = " " * padding + text
    size = len(parts["prefix"]) + len(text) + len(parts["suffix"])
    if size > MAX_FORMAT_SIZE or translator.steps + size > 50000:
        fail("Number.format exceeds the compilation work/output budget")
    translator.steps += size
    return parts["prefix"] + text + parts["suffix"]
