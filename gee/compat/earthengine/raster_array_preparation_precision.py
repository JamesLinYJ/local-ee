"""Bounded final precision inspection for raster-array padding."""
from __future__ import annotations

from gee.integer_values_contract import BOOLEAN_OPERATIONS

from .array_core import charge_array
from .ir import Pixel, fail


_DOUBLE_OPERATIONS = {
    "unmask", "unmask_constant", "on_grid", "remap", "focal", "convolve",
    "neighborhood", "terrain", "distance", "unmix_component",
}
_FLOAT32_OPERATIONS = {
    "classify", "trained_classify", "smile_rf_classify", "fast_distance",
}


def _children(translator, pixel):
    if pixel.op == "where":
        arguments = pixel.args[1:]
    elif pixel.op == "reduce_bands":
        arguments = pixel.args[:1]
    elif pixel.op in {"clip", "preserve_mask"}:
        arguments = pixel.args[:1]
    elif pixel.boolean and pixel.op in BOOLEAN_OPERATIONS:
        arguments = ()
    else:
        arguments = pixel.args

    result = []
    if pixel.op == "reduce_bands" and arguments:
        source = arguments[0]
        if isinstance(source, Pixel):
            result.append(source)
        elif isinstance(source, (tuple, list)):
            charge_array(translator, len(source) + 1)
            result.extend(child for child in source if isinstance(child, Pixel))
    else:
        result.extend(argument for argument in arguments
                      if isinstance(argument, Pixel))
    charge_array(translator, len(result))
    return result


def _is_double(translator, root, memo, name):
    pending = [(root, False)]
    active = set()
    while pending:
        current, expanded = pending.pop()
        if not isinstance(current, Pixel):
            continue
        key = id(current)
        if key in memo:
            continue
        if expanded:
            active.remove(key)
            if current.op == "to_double":
                memo[key] = True
            elif current.op in {"to_float", "is_nodata"}:
                memo[key] = False
            elif current.op == "integer_values":
                memo[key] = not current.boolean
            elif current.op in _FLOAT32_OPERATIONS:
                memo[key] = False
            elif current.op in _DOUBLE_OPERATIONS:
                memo[key] = True
            else:
                memo[key] = any(
                    memo[id(child)] for child in _children(translator, current)
                )
            continue

        if key in active:
            fail(f"{name} received a cyclic pixel expression")
        charge_array(translator, 1 + len(current.args))
        if current.op == "to_double":
            memo[key] = True
            continue
        if current.op in {"to_float", "is_nodata"}:
            memo[key] = False
            continue
        if current.op == "integer_values":
            memo[key] = not current.boolean
            continue
        if current.op in _FLOAT32_OPERATIONS:
            memo[key] = False
            continue
        if current.op in _DOUBLE_OPERATIONS:
            memo[key] = True
            continue

        active.add(key)
        pending.append((current, True))
        for child in reversed(_children(translator, current)):
            if id(child) in active:
                fail(f"{name} received a cyclic pixel expression")
            if id(child) not in memo:
                pending.append((child, False))
    return memo[id(root)]


def raster_array_precision_flags(translator, arrays, name):
    """Return one final Double flag per array band after a bounded IR scan.

    Uncast local raster pixels follow the existing Float32 callback path. A
    nested toDouble stage remains Double, and a later toFloat stage resets it.
    Each array band must have one physical numeric precision across its cells.
    """
    memo = {}
    precisions = []
    for array in arrays:
        flags = [
            _is_double(translator, pixel, memo, name)
            for pixel in array.cells
        ]
        if flags and any(flag != flags[0] for flag in flags[1:]):
            fail(f"{name} requires one numeric precision across each array band")
        precisions.append(flags[0] if flags else False)
    return tuple(precisions)
