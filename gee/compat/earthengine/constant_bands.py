"""Bind pure constant image bands to a concrete local raster grid."""
from __future__ import annotations

import math
import struct
from dataclasses import replace

from gee.pixel_math_contract import PIXEL_MATH_ARITIES
from gee.float64_values_contract import _ceil as ceil_scalar, _floor as floor_scalar, _round as round_scalar

from .ir import Image, Pixel, Source, UnsupportedEEError, fail
from .static_values import scalar_power


_MAX_SAFE_INTEGER = 2**53
_BINARY = {
    "add": lambda x, y: x + y,
    "subtract": lambda x, y: x - y,
    "multiply": lambda x, y: x * y,
    "divide": lambda x, y: 0 if y == 0 else x / y,
    "power": scalar_power,
    "mod": lambda x, y: math.fmod(x, y),
    "eq": lambda x, y: x == y,
    "neq": lambda x, y: x != y,
    "lt": lambda x, y: x < y,
    "lte": lambda x, y: x <= y,
    "gt": lambda x, y: x > y,
    "gte": lambda x, y: x >= y,
    "and": lambda x, y: bool(x and y),
    "or": lambda x, y: bool(x or y),
    "min2": min,
    "max2": max,
}
_UNARY = {
    "not": lambda x: not x,
    "absolute": abs,
    "sqrt": math.sqrt,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "round": round_scalar,
    "floor": floor_scalar,
    "ceil": ceil_scalar,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
}
_CASTS = {"to_float", "to_double"}


def _children(value):
    """Yield direct pixel children, including children nested in arg tuples."""
    if isinstance(value, Pixel):
        yield value
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _children(item)


def _contains_pixel_math(value, seen=None):
    seen = set() if seen is None else seen
    if isinstance(value, Pixel):
        key = id(value)
        if key in seen:
            return False
        seen.add(key)
        if value.op.startswith("math_"):
            if value.op[5:] not in PIXEL_MATH_ARITIES:
                fail(f"Unsupported Image pixel math operation: {value.op[5:]}")
            return True
        return any(_contains_pixel_math(argument, seen) for argument in value.args)
    if isinstance(value, (tuple, list)):
        return any(_contains_pixel_math(argument, seen) for argument in value)
    return False


def _bind_pixel_math_constants(pixel, template, grid_source, footprint, absolute):
    """Materialize finite constant leaves while leaving math for the native tile."""
    if pixel.op == "constant" and len(pixel.args) == 1:
        value = _literal(pixel.args[0])
        if type(value) is bool:
            value = int(value)
        grid_constant = Pixel(
            "on_grid",
            (Pixel("constant", (value,)), template, grid_source, footprint, absolute),
        )
        # local_ee_constant_on_grid is Float64; the pixel-math contract consumes
        # Float32 operands, with the narrowing visible in this generated IR.
        return Pixel("to_float", (grid_constant,))

    def bind(value):
        if isinstance(value, Pixel):
            return _bind_pixel_math_constants(
                value, template, grid_source, footprint, absolute,
            )
        if isinstance(value, tuple):
            return tuple(bind(child) for child in value)
        if isinstance(value, list):
            return [bind(child) for child in value]
        return value

    return replace(pixel, args=tuple(bind(argument) for argument in pixel.args))


def bind_pixel_math_constants(
        pixel: Pixel, template: Pixel, grid_source, footprint=None,
        footprint_is_absolute=False) -> Pixel:
    """Bind a constant-only math expression to an existing finite image grid."""
    if not isinstance(pixel, Pixel) or not _contains_pixel_math(pixel):
        fail("Expected a deferred Image pixel math expression")
    if _has_raster(pixel):
        fail("Deferred Image pixel math expression already has a raster source")
    if (not isinstance(template, Pixel) or not isinstance(grid_source, Source)
            or not grid_source.ids):
        fail("Image pixel math constants require a finite local raster grid")
    return _bind_pixel_math_constants(
        pixel, template, grid_source, footprint, footprint_is_absolute,
    )


def _has_raster(pixel: Pixel, memo=None, active=None) -> bool:
    """Find band dependencies without revisiting shared subexpressions."""
    memo = {} if memo is None else memo
    active = set() if active is None else active
    key = id(pixel)
    cached = memo.get(key)
    if cached is not None and cached[0] is pixel:
        return cached[1]
    if key in active:
        fail("Cyclic pixel expression cannot be used as an addBands grid template")
    if pixel.op == "band":
        memo[key] = (pixel, True)
        return True
    active.add(key)
    result = any(_has_raster(child, memo, active) for child in _children(pixel.args))
    active.remove(key)
    memo[key] = (pixel, result)
    return result


def _literal(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            fail("Constant band integer literals above 2^53 are unsupported")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            fail("Constant bands cannot contain null or non-finite values")
        if value.is_integer() and abs(value) > _MAX_SAFE_INTEGER:
            fail("Constant band integer literals above 2^53 are unsupported")
        return value
    fail("Constant bands currently support finite numeric and boolean literals only")


def _checked(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE_INTEGER:
            fail("Constant band arithmetic exceeds the exact scalar range")
        return value
    if not isinstance(value, float) or not math.isfinite(value):
        fail("Constant band arithmetic must produce a finite scalar")
    if value.is_integer() and abs(value) > _MAX_SAFE_INTEGER:
        fail("Constant band arithmetic exceeds the exact scalar range")
    return value


def _evaluate(pixel: Pixel, memo=None, active=None):
    """Fold only the finite scalar operators supported by the pixel compiler."""
    memo = {} if memo is None else memo
    active = set() if active is None else active
    key = id(pixel)
    cached = memo.get(key)
    if cached is not None and cached[0] is pixel:
        return cached[1]
    if key in active:
        fail("Cyclic constant pixel expression is unsupported")
    active.add(key)
    if pixel.op == "constant" and len(pixel.args) == 1:
        value = _literal(pixel.args[0])
    else:
        values = []
        for argument in pixel.args:
            if isinstance(argument, Pixel):
                values.append(_evaluate(argument, memo, active))
            elif isinstance(argument, (tuple, list)):
                fail("Nested aggregate values are not supported in constant band arithmetic")
            else:
                values.append(argument)
        try:
            if pixel.op == "if" and len(values) == 3:
                value = values[1] if values[0] else values[2]
            elif pixel.op in _BINARY and len(values) == 2:
                value = _BINARY[pixel.op](*values)
            elif pixel.op in _UNARY and len(values) == 1:
                value = _UNARY[pixel.op](values[0])
            elif pixel.op in _CASTS and len(values) == 1:
                # Casts are part of a constant's value, not merely wrappers
                # around a value that can be rebound later. In particular,
                # Float32 must round at this boundary before an outer
                # arithmetic operation is evaluated.
                value = float(values[0])
                if pixel.op == "to_float":
                    value = struct.unpack("!f", struct.pack("!f", value))[0]
            else:
                if pixel.op == "clip":
                    fail("Cannot bind a clipped constant band; its source footprint must be preserved")
                fail(f"Cannot bind constant band expression with unsupported operation: {pixel.op}")
            value = _checked(value)
        except UnsupportedEEError:
            raise
        except (ArithmeticError, TypeError, ValueError, OverflowError):
            fail("Constant band arithmetic must produce a finite scalar")
    active.remove(key)
    memo[key] = (pixel, value)
    return value


def _bind_pixel(pixel: Pixel, destination: Image, template: Pixel, source: Image) -> Pixel:
    casts = []
    base = pixel
    while base.op in _CASTS and len(base.args) == 1 and isinstance(base.args[0], Pixel):
        casts.append(base)
        base = base.args[0]
    if _has_raster(base):
        return pixel
    if source.footprint is not None or source.footprint_is_absolute:
        fail("Cannot bind a constant band with an explicit source footprint")
    if _contains_pixel_math(base):
        bound = bind_pixel_math_constants(
            base, template, destination.source, destination.footprint,
            destination.footprint_is_absolute,
        )
    else:
        _evaluate(base)
        bound = Pixel(
            "on_grid",
            (base, template, destination.source, destination.footprint,
             destination.footprint_is_absolute),
            boolean=base.boolean,
        )
    for cast in reversed(casts):
        bound = Pixel(cast.op, (bound,), boolean=cast.boolean)
    return bound


def bind_source_bands(
        source: Image, destination: Image, translator=None) -> list[tuple[str, Pixel]]:
    """Bind unbound pure constants only when the destination has a real grid."""
    if destination.source is None:
        return list(source.bands)
    from .constant_mask_binding import (
        bind_masked_pixel, is_masked_constant_candidate,
    )

    memo = {}
    template = None
    binding_destination = destination
    context_checked = False

    def grid_destination():
        nonlocal binding_destination, context_checked
        if not context_checked:
            from .image_binding_context import binding_context

            binding_destination = binding_context(translator, destination)
            context_checked = True
        return binding_destination

    bound = []
    for name, pixel in source.bands:
        # A weighted constant needs two independently bound grid branches. Do
        # this before the generic raster-lineage check: a mask-only source must
        # not be mistaken for actual science lineage and borrowed as its grid.
        if is_masked_constant_candidate(pixel):
            masked = bind_masked_pixel(
                pixel, source, destination, translator, name,
                destination_factory=grid_destination,
            )
            if masked is None:
                fail("Internal masked constant binding shape changed")
            bound.append((name, masked))
            continue
        if _has_raster(pixel, memo):
            bound.append((name, pixel))
            continue
        if template is None:
            binding_destination = grid_destination()
            template = destination_template(binding_destination)
        if template is None:
            fail("Cannot bind a constant band without a finite local raster grid in dstImg")
        bound.append((name, _bind_pixel(pixel, binding_destination, template, source)))
    return bound


def destination_template(destination: Image, *, science_only: bool = False):
    """Return a real destination band DAG with its spatial/temporal shape intact."""
    if destination.source is None:
        return None
    if not destination.source.ids:
        return None
    if science_only:
        # Masked-constant binding precharges and depth-checks the complete
        # destination closure before asking for this narrower grid proof.
        from .constant_mask_binding import has_science_grid

    memo = {}
    for _, pixel in destination.bands:
        if not _has_raster(pixel, memo):
            continue
        if not science_only or has_science_grid(pixel):
            return pixel
    return None
