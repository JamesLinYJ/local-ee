"""Bounded literal-design validation before any matrix solver allocation."""
import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, const
from gee.compat.earthengine.raster_array_core import wrap_array_image
from gee.compat.earthengine.raster_matrix_literals import scan_literal_cells
from gee.compat.earthengine.raster_matrix_solve import invoke_raster_matrix
from gee.ee_translate import UnsupportedEEError


def _direct_solve(left_cells, right_cells, left_shape=(1, 1), right_shape=(1, 1)):
    left = wrap_array_image(
        Image([], {}), left_shape, tuple(left_cells), const(True), "lhs",
    )
    right = wrap_array_image(
        Image([], {}), right_shape, tuple(right_cells), const(True), "rhs",
    )
    return invoke_raster_matrix(Translator([], {}, {}), "Image.matrixSolve", {
        "image1": left, "image2": right,
    })


@pytest.mark.parametrize("bad", [
    Pixel("to_double", (Pixel("constant", (float("inf"),)),)),
    Pixel("to_double", (Pixel("constant", (2**53 + 1,)),)),
    Pixel("to_double", (const(1.0), const(2.0))),
    Pixel("to_double", (const(1.0),), True),
])
def test_literal_design_rejects_nonfinite_out_of_domain_and_malformed_constants(bad):
    with pytest.raises(UnsupportedEEError):
        _direct_solve([bad], [Pixel("to_double", (const(1.0),))])


def test_literal_design_rejects_cycles_and_mixed_casts_within_one_array():
    cyclic = Pixel("to_double", (const(1.0),))
    object.__setattr__(cyclic, "args", (cyclic,))
    with pytest.raises(UnsupportedEEError, match="cyclic"):
        _direct_solve([cyclic], [Pixel("to_double", (const(1.0),))])

    left = [Pixel("to_float", (const(1.0),)),
            Pixel("to_double", (const(2.0),))]
    right = [Pixel("to_double", (const(1.0),)),
             Pixel("to_double", (const(2.0),))]
    with pytest.raises(UnsupportedEEError, match="one uniform explicit cast"):
        _direct_solve(left, right, (2, 1), (2, 1))


def test_literal_cast_scan_accepts_exact_budget_and_counts_shared_nodes_once():
    expression = const(1.0)
    for _ in range(499):
        expression = Pixel("to_double", (expression,))

    assert scan_literal_cells([expression, expression], "image1") == 500


@pytest.mark.parametrize("invalid", ["over_budget", "cycle", "malformed"])
def test_invalid_literal_graphs_reject_before_numpy_allocation(monkeypatch, invalid):
    def unexpected_lstsq(*_args, **_kwargs):
        raise AssertionError("invalid literal graph reached NumPy")

    monkeypatch.setattr(np.linalg, "lstsq", unexpected_lstsq)
    if invalid == "over_budget":
        expression = const(1.0)
        for _ in range(500):
            expression = Pixel("to_double", (expression,))
        expected_error = "static expression budget"
    elif invalid == "cycle":
        expression = Pixel("to_double", (const(1.0),))
        object.__setattr__(expression, "args", (expression,))
        expected_error = "cyclic"
    else:
        expression = Pixel("to_double", (const(1.0), const(2.0)))
        expected_error = "explicit top-level"

    with pytest.raises(UnsupportedEEError, match=expected_error):
        _direct_solve([expression], [Pixel("to_double", (const(1.0),))])
