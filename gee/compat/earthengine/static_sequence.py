"""Finite static List.sequence evaluation, without allocating unbounded ranges."""
from __future__ import annotations

import math

from .ir import fail


MAX_SEQUENCE_VALUES = 10000


def _number(value, label):
    if type(value) not in (int, float):
        fail(f"List.sequence {label} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        fail(f"List.sequence {label} must be a finite number")
    return value


def sequence(arguments):
    """Apply count precedence and retain both endpoints of a count-based range.

    With an end and count, the count determines the spacing and step is ignored.
    Without an end, count is the number of output elements separated by step.
    As with other computed lists, at most 10000 elements may materialize.

    Step ranges use Float64 start + index * step and a strict directional end
    bound, with no tolerance or endpoint clamping. Thus 0:.1:.3 omits the
    computed .30000000000000004; Google endpoint rounding is not verified.
    """
    if "start" not in arguments:
        fail("List.sequence requires start")
    start = _number(arguments["start"], "start")
    end = arguments.get("end")
    if end is not None:
        end = _number(end, "end")
    step = arguments.get("step")
    step = 1 if step is None else _number(step, "step")
    count = arguments.get("count")
    if count is not None:
        count = _number(count, "count")
        if int(count) != count or count < 0:
            fail("List.sequence count must be a non-negative integer")
        if count > MAX_SEQUENCE_VALUES:
            fail("List.sequence exceeds 10000 values")
        count = int(count)
        if count == 0:
            return []
        if end is None:
            _number(start + (count - 1) * step, "generated output")
            values = [start + index * step for index in range(count)]
        elif count == 1:
            values = [start]
        else:
            # A convex interpolation avoids overflowing end - start for finite,
            # opposite-sign endpoints. Assign endpoints exactly after rounding.
            values = [start * (1 - index / (count - 1)) + end * (index / (count - 1))
                      for index in range(count)]
            values[0], values[-1] = start, end
    else:
        if end is None:
            fail("List.sequence requires end or count")
        if step == 0:
            fail("List.sequence step must be nonzero without count")
        try:
            span = (end - start) / step
        except OverflowError:
            fail("List.sequence span exceeds finite numeric range")
        if not math.isfinite(span):
            fail("List.sequence span exceeds finite numeric range")
        if span < 0:
            return []
        length = math.floor(span) + 1
        # Division may round an index upward. Check the actual generated value
        # instead of broadening the caller's endpoint by even one Float64 ULP.
        if length > MAX_SEQUENCE_VALUES + 1:
            fail("List.sequence exceeds 10000 values")
        within_end = (lambda value: value <= end) if step > 0 else (lambda value: value >= end)
        while length and not within_end(start + (length - 1) * step):
            length -= 1
        if length > MAX_SEQUENCE_VALUES:
            fail("List.sequence exceeds 10000 values")
        values = [start + index * step for index in range(length)]
    for value in values:
        _number(value, "generated output")
    return values
