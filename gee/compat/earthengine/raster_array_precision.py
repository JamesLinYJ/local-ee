"""Explicit per-cell precision boundaries for bounded raster-array algorithms."""
from __future__ import annotations

from .ir import Pixel, fail


def require_cast_cells(array, name: str, label: str = "array") -> str:
    """Return a uniform numeric cast; callers precharge their bounded cell scan.

    An outer cast declares the algorithm's precision. Nested casts remain in
    the expression and must still run, so Double never restores Float32 bits.
    This helper does not infer dtype from values or untyped array metadata.
    """
    dtype = None
    for pixel in array.cells:
        if (not isinstance(pixel, Pixel) or pixel.op not in {"to_float", "to_double"}
                or type(pixel.args) is not tuple or len(pixel.args) != 1
                or not isinstance(pixel.args[0], Pixel)
                or pixel.boolean):
            fail(f"{name} requires explicit top-level toFloat() or toDouble() for every {label} cell")
        if dtype is not None and dtype != pixel.op:
            fail(f"{name} requires one uniform explicit cast for every {label} cell")
        dtype = pixel.op
    if dtype is None:
        fail(f"{name} requires nonempty explicitly cast {label} cells")
    return dtype
