"""Public size boundaries and fresh grid checks with cached scalar lineage."""
import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Pixel, Source, UnsupportedEEError
from gee.compat.earthengine.numeric_reducer_grid import require_common_grid
from gee.compat.earthengine.pixel_math_graph import _PixelFactsWalker
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_double_array_solve import (
    ee, local, _compile_value, _design, _response,
)


def test_maximum_solver_ir_dimensions_do_not_guarantee_public_export_fits(ee, local):
    # The direct algorithm admits8x4 and8x4 arrays, but its sixteen flattened
    # public outputs still have to pay for all raster compilation work.
    with OfflineGuard() as guard:
        x = np.linspace(-1, 1, 8)
        design = [[1, float(v), float(v*v), float(v*v*v)] for v in x]
        columns = ee.Image.constant(ee.Array([[1, 1, 1, 1]]))
        rhs = _response(ee, 8).matrixMultiply(columns).toDouble()
        result = _design(ee, design).matrixSolve(rhs).arrayFlatten([
            ["b0", "b1", "b2", "b3"], ["c0", "c1", "c2", "c3"],
        ])
        with pytest.raises(UnsupportedEEError, match="50000-step"):
            _compile_value(ee, result, local)
    assert guard.evidence()["attempt_count"] == 0


def test_cached_lineage_does_not_cache_mutable_projection_metadata():
    items = {"fixture": [{"id": name, "properties": {
        "proj:code": "EPSG:32649", "proj:transform": [1, 0, 0, 0, -1, 1],
    }} for name in ("a", "b")]}
    translator = Translator([], items, {})
    pixels = tuple(Pixel("band", (Source("fixture", (name,), ("red",)), "red"))
                   for name in ("a", "b"))
    for pixel in pixels:
        _PixelFactsWalker(translator).inspect(pixel)
    require_common_grid(translator, pixels)
    previous_work = translator.steps

    items["fixture"][1]["properties"]["proj:transform"][2] = 0.5
    with pytest.raises(UnsupportedEEError, match="grid"):
        require_common_grid(translator, pixels)
    assert translator.steps > previous_work

    items["fixture"][1]["properties"].pop("proj:transform")
    with pytest.raises(UnsupportedEEError, match="proj:transform"):
        require_common_grid(translator, pixels)
