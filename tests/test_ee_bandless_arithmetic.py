"""Explicit zero-band arithmetic limits, independent of operand direction."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.ir import Image, binary, const, pairs, unary
from gee.ee_translate import UnsupportedEEError


@pytest.mark.parametrize("op", ["add", "subtract", "multiply", "eq", "and", "or"])
@pytest.mark.parametrize("count", [1, 2])
def test_no_one_sided_empty_broadcast_can_discard_real_operands(op, count):
    empty = Image([], {"owner": "empty"})
    actual = Image([(f"b{i}", const(i + 1)) for i in range(count)], {"owner": "actual"})
    for left, right in ((empty, actual), (actual, empty)):
        with pytest.raises(UnsupportedEEError, match="Zero-band Image arithmetic"):
            binary(left, right, op)
    assert empty.bands == [] and empty.props == {"owner": "empty"}
    assert len(actual.bands) == count and actual.props == {"owner": "actual"}


@pytest.mark.parametrize("op", ["add", "multiply", "eq", "or"])
def test_empty_pair_has_no_pixel_nodes_or_fabricated_band(op):
    first = Image([], {"title": "first"})
    second = Image([], {"title": "second"})
    _, _, paired = pairs(first, second)
    result = binary(first, second, op)
    assert paired == []
    assert result.bands == []
    assert result.props == {"title": "first"}
    assert result.source is None


def test_empty_cast_or_unary_operation_cannot_recreate_discarded_values():
    image = Image([], {"title": "empty"})
    for op in ("to_float", "to_double", "absolute", "not"):
        result = unary(image, op)
        assert result.bands == [] and result.source is None
        assert result.props == image.props
