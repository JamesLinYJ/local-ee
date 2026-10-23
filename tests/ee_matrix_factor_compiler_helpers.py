"""Factories shared by focused raster-factor compiler tests."""
from __future__ import annotations

import numpy as np

from gee.compat.earthengine.ir import Image, Pixel, const
from gee.compat.earthengine.raster_array_core import wrap_array_image


def array(matrix, *, cast="to_double", mask=None, source=None):
    rows, cols = matrix.shape
    if source is None:
        cells = tuple(Pixel(cast, (const(float(value)),)) for value in matrix.flat)
    else:
        cells = tuple(
            Pixel(cast, (Pixel("band", (source, source.names[index % len(source.names)])),))
            for index, _value in enumerate(matrix.flat)
        )
    return wrap_array_image(
        Image([], {"matrix_tag": "kept"}, source=source),
        (rows, cols), cells, const(True) if mask is None else mask, "input",
    )


def cell_values(array_image):
    return np.array(
        [cell.args[0].args[0] for cell in array_image.cells], dtype=float,
    ).reshape(array_image.shape)
