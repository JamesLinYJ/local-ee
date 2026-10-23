"""Bounded literal cast chains used by the raster matrix solver."""
from __future__ import annotations

import math
import struct

from .ir import Pixel, fail


_CASTS = {"to_float", "to_double"}
_MAX_LITERAL_NODES = 500
_MAX_EXACT_INTEGER = 2**53


def _constant_number(value, name):
    if type(value) not in (int, float):
        fail(f"{name} coefficients must be finite non-boolean numbers")
    if type(value) is int and abs(value) > _MAX_EXACT_INTEGER:
        fail(f"{name} coefficient integers must fit the exact Float64 domain")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        fail(f"{name} coefficients must fit the Float64 domain")
    if not math.isfinite(number):
        fail(f"{name} coefficients must be finite")
    return number


def _scan_cell(pixel, seen_nodes, name):
    if (not isinstance(pixel, Pixel) or pixel.op not in _CASTS
            or len(pixel.args) != 1 or not isinstance(pixel.args[0], Pixel)
            or pixel.boolean):
        fail(f"{name} coefficients require explicit top-level toFloat() or toDouble() casts")

    active = set()
    node = pixel
    new_nodes = 0
    while isinstance(node, Pixel) and node.op in _CASTS:
        identity = id(node)
        if identity in active:
            fail(f"{name} coefficients cannot contain cyclic Pixel expressions")
        if identity in seen_nodes:
            seen_nodes.update(active)
            if len(seen_nodes) > _MAX_LITERAL_NODES:
                fail(f"{name} constant coefficients exceed the static expression budget")
            return len(active)
        if len(node.args) != 1 or node.boolean:
            fail(f"{name} coefficients allow only unary numeric casts")
        if len(seen_nodes) + len(active) >= _MAX_LITERAL_NODES:
            fail(f"{name} constant coefficients exceed the static expression budget")
        active.add(identity)
        new_nodes += 1
        node = node.args[0]

    if not isinstance(node, Pixel) or node.op != "constant" or len(node.args) != 1:
        fail(f"{name} coefficients must be literal constants with optional casts")
    if node.boolean:
        fail(f"{name} coefficients must be finite non-boolean numbers")
    if id(node) not in seen_nodes:
        if len(seen_nodes) + len(active) >= _MAX_LITERAL_NODES:
            fail(f"{name} constant coefficients exceed the static expression budget")
        _constant_number(node.args[0], name)
        new_nodes += 1

    seen_nodes.update(active)
    seen_nodes.add(id(node))
    if len(seen_nodes) > _MAX_LITERAL_NODES:
        fail(f"{name} constant coefficients exceed the static expression budget")
    return new_nodes


def scan_literal_cells(cells, name):
    """Validate finite cast-only constants and count shared expression nodes."""
    seen_nodes = set()
    count = 0
    for pixel in cells:
        count += _scan_cell(pixel, seen_nodes, name)
    return count


def _float32(value, name):
    try:
        result = struct.unpack("!f", struct.pack("!f", value))[0]
    except (OverflowError, struct.error):
        fail(f"{name} coefficients overflow Float32")
    if not math.isfinite(result):
        fail(f"{name} coefficients overflow Float32")
    return result


def _literal_cell(pixel, name, memo):
    casts = []
    active = set()
    node = pixel
    cached = False
    number = None
    while isinstance(node, Pixel) and node.op in _CASTS:
        identity = id(node)
        if identity in active:
            fail(f"{name} coefficients cannot contain cyclic Pixel expressions")
        previous = memo.get(identity)
        if previous is not None and previous[0] is node:
            number = previous[1]
            cached = True
            break
        if len(node.args) != 1 or node.boolean:
            fail(f"{name} coefficients allow only unary numeric casts")
        active.add(identity)
        casts.append(node)
        node = node.args[0]

    if not cached:
        if (not isinstance(node, Pixel) or node.op != "constant"
                or len(node.args) != 1 or node.boolean):
            fail(f"{name} coefficients must be literal constants with optional casts")
        previous = memo.get(id(node))
        if previous is not None and previous[0] is node:
            number = previous[1]
        else:
            number = _constant_number(node.args[0], name)
            memo[id(node)] = (node, number)

    for cast in reversed(casts):
        number = (_float32(number, name) if cast.op == "to_float"
                  else _constant_number(number, name))
        memo[id(cast)] = (cast, number)
    return number


def literal_cells(cells, name):
    """Evaluate each validated cast chain once and return finite float values."""
    memo = {}
    return [_literal_cell(pixel, name, memo) for pixel in cells]
