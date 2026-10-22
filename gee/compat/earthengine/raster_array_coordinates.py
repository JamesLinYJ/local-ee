"""Static scalar coordinate decoding for raster array layout operations."""
from __future__ import annotations

import math
import struct

from .array_core import charge_array
from .ir import Image, Pixel, UnsupportedEEError, fail
from .static_values import scalar_power


def _integer(value, label, minimum=None):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or isinstance(value, float) and not math.isfinite(value)
            or int(value) != value):
        fail(f"{label} must be an integer")
    result = int(value)
    if minimum is not None and result < minimum:
        fail(f"{label} must be >= {minimum}")
    return result


def _pixel_nodes(pixel, nodes, active):
    key = id(pixel)
    if key in active:
        fail("Array slice coordinate contains a cyclic Pixel expression")
    if key in nodes:
        return
    if len(nodes) >= 500:
        fail("Array slice coordinate exceeds the static image expression budget")
    active.add(key)
    nodes[key] = pixel
    for operand in pixel.args:
        if isinstance(operand, Pixel):
            _pixel_nodes(operand, nodes, active)
    active.remove(key)


def _evaluate_constant_pixel(pixel, values):
    key = id(pixel)
    if key in values:
        return values[key]
    try:
        if pixel.op == "constant":
            value = pixel.args[0]
        else:
            unary_ops = {
                "absolute": abs,
                "sqrt": math.sqrt,
                "log": math.log,
                "log10": math.log10,
                "exp": math.exp,
                "round": lambda x: math.floor(x + .5),
                "floor": math.floor,
                "ceil": math.ceil,
                "sin": math.sin,
                "cos": math.cos,
                "tan": math.tan,
                "to_double": float,
            }
            if pixel.op == "to_float":
                number = _evaluate_constant_pixel(pixel.args[0], values)
                value = struct.unpack("!f", struct.pack("!f", number))[0]
            elif pixel.op in unary_ops:
                value = unary_ops[pixel.op](_evaluate_constant_pixel(pixel.args[0], values))
            elif pixel.op in {"add", "subtract", "multiply", "divide", "power", "mod", "min2", "max2"}:
                left = _evaluate_constant_pixel(pixel.args[0], values)
                right = _evaluate_constant_pixel(pixel.args[1], values)
                if pixel.op == "add": value = left + right
                elif pixel.op == "subtract": value = left - right
                elif pixel.op == "multiply": value = left * right
                elif pixel.op == "divide": value = left / right if right else 0
                elif pixel.op == "power": value = scalar_power(left, right)
                elif pixel.op == "mod": value = math.fmod(left, right)
                elif pixel.op == "min2": value = min(left, right)
                else: value = max(left, right)
            else:
                fail("Array slice coordinates require a pure constant scalar image")
    except UnsupportedEEError:
        raise
    except (ArithmeticError, TypeError, ValueError):
        fail("Raster array coordinates must be finite numeric scalars")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("Raster array coordinates must be finite numeric scalars")
    if isinstance(value, float) and not math.isfinite(value):
        fail("Array slice coordinates must be finite numeric scalars")
    values[key] = value
    return value


def constant_pixel_integer(translator, pixel, label, minimum=None):
    """Evaluate one bounded pure-constant Pixel as an integer coordinate."""
    if not isinstance(pixel, Pixel):
        fail(f"{label} must be a pure constant scalar image")
    nodes = {}
    _pixel_nodes(pixel, nodes, set())
    charge_array(translator, len(nodes))
    value = _evaluate_constant_pixel(pixel, {})
    return _integer(value, label, minimum)


def constant_image_integer(translator, value, label):
    """Read an integer from a static number or a pure one-band Image."""
    if isinstance(value, Image):
        if len(value.bands) != 1:
            fail(f"{label} image must contain exactly one scalar band")
        return constant_pixel_integer(translator, value.bands[0][1], label)
    return _integer(value, label)
