"""Bounded numeric remapping wire shared by the pure compiler and engine."""
from __future__ import annotations

import math

from .sampling_spec import _parse, encode_spec


MAX_ENTRIES = 256
FIELDS = {'version', 'from', 'to', 'default'}


def _number(value):
    try:
        valid = (type(value) in (int, float) and math.isfinite(value)
                 and (type(value) is not int or abs(value) <= 2**53))
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('Remap values must be finite numbers; integer magnitude must be <=2^53')
    return value


def _check(spec):
    if (type(spec) is not dict or set(spec) != FIELDS
            or type(spec['version']) is not int or spec['version'] != 1):
        raise ValueError('Remap specification requires exactly version1/from/to/default')
    source, target = spec['from'], spec['to']
    if (type(source) is not list or type(target) is not list
            or len(source) != len(target) or len(source) > MAX_ENTRIES):
        raise ValueError('Remap from/to must be equal-length lists of 0..256 scalar values')
    for value in [*source, *target]:
        _number(value)
    if len(set(source)) != len(source):
        raise ValueError('Remap from keys must be numerically unique, including signed zero')
    if spec['default'] is not None:
        _number(spec['default'])
    return spec


def prepare_remap_spec(from_values, to_values, default=None):
    spec = _check({'version': 1, 'from': from_values, 'to': to_values, 'default': default})
    return encode_spec(spec)


def decode_remap_spec(text):
    return _check(_parse(text))
