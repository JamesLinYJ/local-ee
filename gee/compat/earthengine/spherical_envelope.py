"""Strict value object and decoder for the S2 envelope ABI record."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .ir import fail


@dataclass(frozen=True, slots=True)
class Envelope:
    empty: bool
    full_longitude: bool
    wrapped: bool
    west: float
    south: float
    east: float
    north: float


def decode_envelope(values):
    """Decode and validate [version, flags, west, south, east, north]."""
    try:
        record_length = len(values)
    except (TypeError, AttributeError):
        fail("S2 returned a malformed envelope record")
    if record_length != 8:
        fail("S2 returned a malformed envelope record")
    numbers = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            fail("S2 returned a non-numeric envelope value")
        try:
            number = float(value)
            valid = math.isfinite(number)
        except (TypeError, ValueError, OverflowError):
            valid = False
            number = 0.0
        if not valid:
            fail("S2 returned a non-finite envelope value")
        numbers.append(number)

    version, empty_flag, full_flag, wrapped_flag = numbers[:4]
    if version != 1 or any(flag not in (0.0, 1.0)
                           for flag in (empty_flag, full_flag, wrapped_flag)):
        fail("S2 returned an unsupported envelope record")
    empty, full_longitude, wrapped = (bool(empty_flag), bool(full_flag),
                                       bool(wrapped_flag))
    west, south, east, north = numbers[4:]
    if full_longitude and wrapped:
        fail("S2 returned conflicting longitude envelope flags")
    if empty:
        if full_longitude or wrapped or any(value != 0.0 for value in numbers[4:]):
            fail("S2 returned a malformed empty envelope")
        return Envelope(True, False, False, 0.0, 0.0, 0.0, 0.0)

    if (west < -180.0 or west > 180.0 or east < -180.0 or east > 180.0
            or south < -90.0 or north > 90.0 or south > north):
        fail("S2 returned out-of-range envelope coordinates")
    if full_longitude:
        if west != -180.0 or east != 180.0:
            fail("S2 returned malformed full-longitude bounds")
    else:
        if west == -180.0 and east == 180.0:
            fail("S2 returned a full longitude interval without its flag")
        if south == -90.0 or north == 90.0:
            fail("S2 returned a pole-touching envelope without full longitude")
        if wrapped != (west > east):
            fail("S2 returned inconsistent wrapped-longitude bounds")
    return Envelope(empty, full_longitude, wrapped, west, south, east, north)
