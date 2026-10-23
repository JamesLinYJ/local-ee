"""Source-free matrix factor folding and explicit rejection controls."""
from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction
import math

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, UnsupportedEEError, const
from gee.compat.earthengine.raster_array_bands import RasterArrayBands
from gee.compat.earthengine.raster_array_core import RasterArrayImage, wrap_array_image
from gee.compat.earthengine.raster_matrix_decomposition import (
    invoke_raster_matrix_decomposition,
)
from gee.compat.earthengine.raster_matrix_factor_constants import (
    _exact_fraction_decimal,
    _fraction_to_float_once,
)
from ee_matrix_factor_compiler_helpers import array, cell_values


def test_valid_source_free_factors_fold_without_a_grid_and_keep_metadata():
    translator = Translator([], {}, {})
    positive = np.array([[4.0, 12.0], [12.0, 37.0]])
    chol = invoke_raster_matrix_decomposition(
        translator, "Image.matrixCholeskyDecomposition", {"image": array(positive)},
    )
    assert isinstance(chol, RasterArrayImage)
    assert chol.name == "L" and chol.image.source is None
    assert chol.image.props == {"matrix_tag": "kept"}
    np.testing.assert_array_equal(cell_values(chol), [[2.0, 0.0], [6.0, 1.0]])

    pivoted = np.array([[0.0, 2.0], [4.0, 5.0]])
    factors = invoke_raster_matrix_decomposition(
        translator, "Image.matrixLUDecomposition", {"image": array(pivoted)},
    )
    assert isinstance(factors, RasterArrayBands)
    assert [factor.name for factor in factors.arrays] == ["L", "U", "P"]
    assert factors.image.props == {"matrix_tag": "kept"}
    lower, upper, permutation = map(cell_values, factors.arrays)
    np.testing.assert_array_equal(permutation @ pivoted, lower @ upper)


def test_factor_validation_rejects_parameters_cast_masks_and_static_failures():
    translator = Translator([], {}, {})
    matrix = np.eye(2)
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_raster_matrix_decomposition(
            translator, "Image.matrixLUDecomposition",
            {"image": array(matrix), "ignored": True},
        )
    uncast = wrap_array_image(
        Image([], {}), (2, 2), tuple(const(float(value)) for value in matrix.flat), const(True),
    )
    with pytest.raises(UnsupportedEEError, match="explicit top-level"):
        invoke_raster_matrix_decomposition(
            translator, "Image.matrixCholeskyDecomposition", {"image": uncast},
        )
    with pytest.raises(UnsupportedEEError, match="masked source-free"):
        invoke_raster_matrix_decomposition(
            translator, "Image.matrixLUDecomposition",
            {"image": array(matrix, mask=const(False))},
        )
    with pytest.raises(UnsupportedEEError, match="exactly symmetric"):
        invoke_raster_matrix_decomposition(
            translator, "Image.matrixCholeskyDecomposition",
            {"image": array(np.array([[2.0, 1.0], [0.0, 2.0]]))},
        )
    with pytest.raises(UnsupportedEEError, match="positive computed"):
        invoke_raster_matrix_decomposition(
            translator, "Image.matrixCholeskyDecomposition",
            {"image": array(np.array([[1.0, 2.0], [2.0, 1.0]]))},
        )
    singular = (np.array([[1.0, 2.0], [2.0, 4.0]]),
                np.array([[3.0, 3.0], [1.0, 1.0]]))
    for value in singular:
        with pytest.raises(UnsupportedEEError, match="zero LU pivot"):
            invoke_raster_matrix_decomposition(
                translator, "Image.matrixLUDecomposition", {"image": array(value)},
            )

    near_singular = invoke_raster_matrix_decomposition(
        translator, "Image.matrixLUDecomposition",
        {"image": array(np.array([[3.0, 3.0], [1.0, 1.0 + 2**-52]]))},
    )
    assert cell_values(near_singular.arrays[1])[1, 1] > 0.0


def test_lu_rejects_nonfinite_float32_terminal_factor():
    maximum = float(np.finfo(np.float32).max)
    matrix = array(np.array([[1.0, maximum], [-1.0, maximum]]), cast="to_float")
    with pytest.raises(UnsupportedEEError, match="overflow Float32"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixLUDecomposition", {"image": matrix},
        )


def test_dyadic_residual_conversion_is_exact_before_precision50_sqrt():
    tiny = Fraction.from_float(math.ulp(0.0))
    actual = _exact_fraction_decimal(tiny, "factor")
    with localcontext() as context:
        context.prec = 800
        expected = Decimal(5**1074).scaleb(-1074)
    assert actual == expected


def test_lu_fraction_rounding_is_single_binary64_rounding_near_midpoint():
    just_above = Fraction(1) + Fraction(1, 2**53) + Fraction(1, 2**1100)
    expected = math.nextafter(1.0, 2.0)
    assert float(just_above) == expected
    assert _fraction_to_float_once(just_above, "factor") == expected
    with localcontext() as context:
        context.prec = 50
        double_rounded = float(Decimal(just_above.numerator)
                               / Decimal(just_above.denominator))
    assert double_rounded == 1.0
