"""Untrusted scalar powers must stay bounded before raster materialization."""
import pytest

from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.static_values import scalar_power
from test_ee_translate import call, compile, local


@pytest.mark.parametrize("base,exponent,expected", [(3, 33, 5559060566555523),
    (2, -3, .125), (-1, 2**53, 1), (0, 12, 0)])
def test_bounded_powers_keep_ordinary_exact_results(base, exponent, expected):
    assert scalar_power(base, exponent) == expected


@pytest.mark.parametrize("base,exponent", [(2, 2**53), (-2, 2**53), (2**1024, 2)])
def test_integer_powers_reject_before_an_enormous_allocation(base, exponent):
    with pytest.raises(UnsupportedEEError, match="budget"):
        scalar_power(base, exponent)


def test_static_and_image_constant_powers_share_the_same_resource_boundary(local):
    expressions = [call("Number.pow", left=2, right=2**53),
                   call("Image.pow", image1=call("Image.constant", value=2),
                        image2=call("Image.constant", value=2**53))]
    for expression in expressions:
        with pytest.raises(UnsupportedEEError, match="power|Power"):
            compile(expression, local)
