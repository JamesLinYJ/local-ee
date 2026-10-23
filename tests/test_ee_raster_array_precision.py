"""Uniform explicit precision proof used by fixed raster-array consumers."""
from types import SimpleNamespace

import pytest

from gee.compat.earthengine.ir import Pixel, UnsupportedEEError, const
from gee.compat.earthengine.raster_array_precision import require_cast_cells


@pytest.mark.parametrize("dtype", ["to_float", "to_double"])
def test_explicit_cells_preserve_inner_rounding_and_input_ownership(dtype):
    inner = Pixel("to_float", (const(2**24 + 1),))
    cell = Pixel(dtype, (inner,))
    array = SimpleNamespace(cells=(cell, cell))
    assert require_cast_cells(array, "matrix") == dtype
    assert array.cells == (cell, cell)
    assert array.cells[0].args[0] is inner


@pytest.mark.parametrize("cell", [
    const(1),
    Pixel("to_double", (), False),
    Pixel("to_double", (const(1), const(2))),
    Pixel("to_double", (1,)),
    Pixel("to_double", (const(1),), True),
    Pixel("to_double", [const(1)]),
    Pixel("to_double", None),
    None,
])
def test_untyped_or_malformed_cells_fail_explicitly(cell):
    with pytest.raises(UnsupportedEEError, match="explicit top-level"):
        require_cast_cells(SimpleNamespace(cells=(cell,)), "matrix", "matrix")


def test_mixed_or_empty_cells_do_not_infer_a_dtype():
    mixed = SimpleNamespace(cells=(
        Pixel("to_float", (const(1),)), Pixel("to_double", (const(2),)),
    ))
    with pytest.raises(UnsupportedEEError, match="uniform explicit cast"):
        require_cast_cells(mixed, "prefix")
    with pytest.raises(UnsupportedEEError, match="nonempty"):
        require_cast_cells(SimpleNamespace(cells=()), "prefix")
