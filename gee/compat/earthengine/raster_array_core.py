"""Fixed-shape, single-band raster arrays carried beside the ordinary Image IR."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math
import numbers
from typing import Sequence

from .ir import Image, Pixel, const, fail


MAX_RASTER_ARRAY_RANK = 8
MAX_RASTER_ARRAY_AXIS = 64
MAX_RASTER_ARRAY_CELLS = 64


@dataclass(frozen=True)
class RasterArrayImage:
    """One array-valued band with a fixed shape and row-major scalar pixels."""

    image: Image
    shape: tuple[int, ...]
    cells: tuple[Pixel, ...]
    mask: Pixel
    name: str = "array"


def check_shape(shape: Sequence[int]) -> int:
    """Validate a fixed array shape and return its scalar element count.

    Rank zero is the single scalar shape ``()``. Every explicit axis is
    positive, at most 64, and the total number of cells is at most 64.
    """
    if not isinstance(shape, (tuple, list)):
        fail("Raster Array shape must be a tuple of fixed dimensions")
    if len(shape) > MAX_RASTER_ARRAY_RANK:
        fail("Raster Array rank exceeds 8")
    dimensions = []
    for dimension in shape:
        if (isinstance(dimension, bool) or not isinstance(dimension, numbers.Integral)
                or dimension <= 0 or dimension > MAX_RASTER_ARRAY_AXIS):
            fail("Raster Array axes must be positive integers no greater than 64")
        dimensions.append(int(dimension))
    count = math.prod(dimensions)
    if count > MAX_RASTER_ARRAY_CELLS:
        fail("Raster Array exceeds 64 cells")
    return count


def _valid_mask(pixel: Pixel) -> bool:
    return pixel.boolean or pixel.op == "constant" and pixel.args == (None,)


def combined_mask(*masks: Pixel) -> Pixel:
    """Return a validity conjunction while retaining any NoData condition."""
    for mask in masks:
        if not isinstance(mask, Pixel) or not _valid_mask(mask):
            fail("Raster Array masks must be boolean Pixels or NoData")
    if any(mask.op == "constant" and mask.args == (None,) for mask in masks):
        return const(None)
    result = const(True)
    for mask in masks:
        if mask is result:
            continue
        if mask.op == "constant" and mask.args == (True,):
            continue
        if result.op == "constant" and result.args == (True,):
            result = mask
            continue
        if (result.op == "constant" and mask.op == "constant"
                and result.args[0] is not None and mask.args[0] is not None):
            result = const(bool(result.args[0] and mask.args[0]))
            continue
        # Keep the expression when either operand can be NoData. In particular,
        # false AND NoData must not become a valid false mask.
        result = Pixel("and", (result, mask), True)
    return result


def _check_array(array: RasterArrayImage) -> int:
    if not isinstance(array, RasterArrayImage):
        fail("Expected a fixed-shape RasterArrayImage")
    count = check_shape(array.shape)
    if not isinstance(array.image, Image):
        fail("Raster Array metadata must come from an Image")
    if not isinstance(array.cells, tuple) or len(array.cells) != count:
        fail("Raster Array cells must be a row-major Pixel tuple matching its shape")
    if any(not isinstance(pixel, Pixel) for pixel in array.cells):
        fail("Raster Array cells must be Pixels")
    if not isinstance(array.mask, Pixel) or not _valid_mask(array.mask):
        fail("Raster Array mask must be a boolean Pixel or NoData")
    if not isinstance(array.name, str):
        fail("Raster Array band name must be a string")
    return count


def wrap_array_image(
    image: Image,
    shape: tuple[int, ...],
    cells: tuple[Pixel, ...],
    mask: Pixel,
    name: str = "array",
) -> RasterArrayImage:
    """Construct an array image after validating its fixed layout."""
    count = check_shape(shape)
    if not isinstance(image, Image):
        fail("Raster Array metadata must come from an Image")
    if not isinstance(cells, tuple) or len(cells) != count:
        fail("Raster Array cells must be a row-major Pixel tuple matching its shape")
    if any(not isinstance(pixel, Pixel) for pixel in cells):
        fail("Raster Array cells must be Pixels")
    if not isinstance(mask, Pixel) or not _valid_mask(mask):
        fail("Raster Array mask must be a boolean Pixel or NoData")
    if not isinstance(name, str):
        fail("Raster Array band name must be a string")
    return RasterArrayImage(image, tuple(int(size) for size in shape), cells, mask, name)


def masked_scalar(array: RasterArrayImage, pixel: Pixel, name: str | None = None) -> Image:
    """Turn a scalar pixel into an Image band under the array-wide mask."""
    _check_array(array)
    if not isinstance(pixel, Pixel):
        fail("Raster Array scalar output must be a Pixel")
    band_name = array.name if name is None else name
    if not isinstance(band_name, str):
        fail("Raster Array output band name must be a string")
    if array.mask.op == "constant" and array.mask.args == (True,):
        output = pixel
    else:
        output = Pixel("if", (array.mask, pixel, const(None)))
    return replace(array.image, bands=[(band_name, output)])


def flatten_image(array: RasterArrayImage, names: Sequence[str]) -> Image:
    """Expose row-major array cells as ordinary bands with the shared mask."""
    count = _check_array(array)
    if not isinstance(names, (tuple, list)) or len(names) != count:
        fail("Raster Array flatten names must provide one name per cell")
    if any(not isinstance(name, str) for name in names) or len(set(names)) != count:
        fail("Raster Array flatten names must be unique strings")
    bands = []
    for band_name, pixel in zip(names, array.cells):
        if array.mask.op == "constant" and array.mask.args == (True,):
            masked = pixel
        else:
            masked = Pixel("if", (array.mask, pixel, const(None)))
        bands.append((band_name, masked))
    return replace(array.image, bands=bands)
