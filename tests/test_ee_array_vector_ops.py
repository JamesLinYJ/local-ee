"""Pinned SDK and bounded static semantics for Array vector helpers."""
import math
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_core import (
    MAX_ARRAY_CELLS,
    MAX_ARRAY_WORK,
    StaticArray,
    wrap_array,
)
from gee.compat.earthengine import array_vector_ops
from gee.compat.earthengine.decoder import Translator
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def output(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def invoke(name, **arguments):
    return array_vector_ops.invoke_array_vector(
        Translator([], {}, {}), name, arguments
    )


def invocation_nodes(value):
    if isinstance(value, dict):
        found = [value] if value.get("type") == "Invocation" else []
        for child in value.values():
            found.extend(invocation_nodes(child))
        return found
    if isinstance(value, (list, tuple)):
        return [node for item in value for node in invocation_nodes(item)]
    return []


def test_pinned_sdk_serializes_identity_dot_product_and_pad_arguments(ee):
    assert ee.__version__ == "1.7.49"
    identity = ee.serializer.encode(ee.Array.identity(2), for_cloud_api=False)
    assert identity == {
        "type": "Invocation",
        "functionName": "Array.identity",
        "arguments": {"size": 2},
    }

    dot = ee.serializer.encode(
        ee.Array([1, 2]).dotProduct([3, 4]), for_cloud_api=False
    )
    dot_call = next(
        node for node in invocation_nodes(dot)
        if node["functionName"] == "Array.dotProduct"
    )
    assert set(dot_call["arguments"]) == {"array1", "array2"}

    default_pad = ee.serializer.encode(
        ee.Array([1]).pad([3]), for_cloud_api=False
    )
    pad_call = next(
        node for node in invocation_nodes(default_pad)
        if node["functionName"] == "Array.pad"
    )
    assert set(pad_call["arguments"]) == {"array", "lengths"}

    explicit_pad = ee.serializer.encode(
        ee.Array([1]).pad([3], 7), for_cloud_api=False
    )
    pad_call = next(
        node for node in invocation_nodes(explicit_pad)
        if node["functionName"] == "Array.pad"
    )
    assert pad_call["arguments"]["pad"] == 7


def test_pinned_sdk_static_array_vector_operations_compile(ee):
    assert output(ee, ee.Array.identity(0)) == []
    assert output(ee, ee.Array.identity(3)) == [
        [1, 0, 0], [0, 1, 0], [0, 0, 1]
    ]
    assert output(ee, ee.Array([1, 2]).dotProduct([3, 4])) == 11
    assert output(ee, ee.Array([1, 2]).dotProduct([3.0, 4.0])) == 11.0
    assert output(ee, ee.Array([1, 2]).pad([4])) == [1, 2, 0, 0]
    assert output(ee, ee.Array([[1], [2]]).pad([3, 2], -1)) == [
        [1, -1], [2, -1], [-1, -1]
    ]
    # A requested target shorter than an axis does not truncate that axis.
    assert output(ee, ee.Array([1, 2]).pad([1], 8)) == [1, 2]


def test_identity_checks_dimension_cell_and_work_limits_before_allocation():
    empty = invoke("Array.identity", size=0)
    assert isinstance(empty, StaticArray)
    assert empty.data.shape == (0, 0)
    assert empty.to_value() == []
    assert empty.data.flags.writeable is False

    identity = invoke("Array.identity", size=4)
    assert isinstance(identity, StaticArray)
    assert identity.to_value() == [
        [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]
    ]
    assert identity.data.flags.writeable is False
    assert invoke("Array.identity", size=100).data.size == MAX_ARRAY_CELLS

    for size in (-1, 101, 10**100, 1.5, float("inf"), True):
        with pytest.raises(UnsupportedEEError):
            invoke("Array.identity", size=size)

    translator = Translator([], {}, {})
    translator.steps = MAX_ARRAY_WORK - 1
    assert array_vector_ops.invoke_array_vector(
        translator, "Array.identity", {"size": 0}
    ).data.shape == (0, 0)
    assert translator.steps == MAX_ARRAY_WORK
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_vector_ops.invoke_array_vector(
            translator, "Array.identity", {"size": 0}
        )
    assert translator.steps == MAX_ARRAY_WORK

    translator = Translator([], {}, {})
    translator.steps = MAX_ARRAY_WORK - 1
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_vector_ops.invoke_array_vector(
            translator, "Array.identity", {"size": 1}
        )
    assert translator.steps == MAX_ARRAY_WORK - 1


def test_dot_product_keeps_exact_integer_domain_and_handles_float_cancellation():
    assert invoke(
        "Array.dotProduct",
        array1=wrap_array([2**52, 1]),
        array2=wrap_array([1, 1]),
    ) == 2**52 + 1
    assert invoke(
        "Array.dotProduct",
        array1=wrap_array([2**53, 2**53]),
        array2=wrap_array([2**53, -(2**53)]),
    ) == 0
    with pytest.raises(UnsupportedEEError, match="exact Float64 domain"):
        invoke(
            "Array.dotProduct",
            array1=wrap_array([2**53, 1]),
            array2=wrap_array([1, 1]),
        )

    result = invoke(
        "Array.dotProduct",
        array1=wrap_array([1e154, 1e154]),
        array2=wrap_array([1e154, -1e154]),
    )
    assert math.isclose(result, 0.0, abs_tol=1e-16)
    assert math.isclose(
        invoke(
            "Array.dotProduct",
            array1=wrap_array([0.1, 0.2]),
            array2=wrap_array([0.3, 0.4]),
        ),
        0.11,
        rel_tol=1e-15,
    )

    maximum = wrap_array([0] * MAX_ARRAY_CELLS)
    assert invoke(
        "Array.dotProduct", array1=maximum, array2=maximum
    ) == 0


def test_dot_product_rejects_wrong_shapes_nonfinite_values_and_budget_overflow():
    vector = wrap_array([1, 2])
    with pytest.raises(UnsupportedEEError, match="rank-1"):
        invoke(
            "Array.dotProduct",
            array1=wrap_array([[1, 2]]),
            array2=wrap_array([[1, 2]]),
        )
    with pytest.raises(UnsupportedEEError, match="equal lengths"):
        invoke("Array.dotProduct", array1=vector, array2=wrap_array([1]))
    with pytest.raises(UnsupportedEEError, match="finite"):
        invoke(
            "Array.dotProduct",
            array1=StaticArray(np.array([np.inf])),
            array2=wrap_array([1]),
        )

    translator = Translator([], {}, {})
    translator.steps = MAX_ARRAY_WORK - 10
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_vector_ops.invoke_array_vector(
            translator,
            "Array.dotProduct",
            {"array1": wrap_array([1, 2, 3]), "array2": wrap_array([1, 2, 3])},
        )
    assert translator.steps == MAX_ARRAY_WORK - 10


def test_pad_preserves_existing_values_and_promotes_for_fractional_fill():
    source = wrap_array([[1, 2], [3, 4]])
    padded = invoke("Array.pad", array=source, lengths=[3, 4], pad=2.5)
    assert padded.data.dtype.kind == "f"
    assert padded.to_value() == [
        [1.0, 2.0, 2.5, 2.5],
        [3.0, 4.0, 2.5, 2.5],
        [2.5, 2.5, 2.5, 2.5],
    ]
    assert source.to_value() == [[1, 2], [3, 4]]
    assert padded.data.flags.writeable is False

    empty = wrap_array(np.empty((2, 0), dtype=np.float64))
    assert invoke("Array.pad", array=empty, lengths=[2, 3]).to_value() == [
        [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    ]
    scalar = wrap_array(7)
    assert invoke("Array.pad", array=scalar, lengths=[]).to_value() == 7


def test_pad_rejects_invalid_lengths_values_shapes_and_work_overflow():
    source = wrap_array([1, 2])
    cases = [
        ({"array": source}, "requires"),
        (
            {"array": source, "lengths": [2], "extra": 1},
            "Unsupported algorithm arguments",
        ),
        ({"array": source, "lengths": [2, 2]}, "one integer"),
        ({"array": source, "lengths": "2"}, "one integer"),
        ({"array": source, "lengths": [True]}, "integer"),
        ({"array": source, "lengths": [1.5]}, "integer"),
        ({"array": source, "lengths": [-1]}, "between"),
        ({"array": source, "lengths": [MAX_ARRAY_CELLS + 1]}, "between"),
        ({"array": source, "lengths": [2], "pad": float("nan")}, "finite"),
        ({"array": source, "lengths": [2], "pad": float("inf")}, "finite"),
        ({"array": source, "lengths": [2], "pad": True}, "finite"),
        ({"array": source, "lengths": [2], "pad": 2**53 + 1}, "exact Float64"),
    ]
    for arguments, message in cases:
        with pytest.raises(UnsupportedEEError, match=message):
            array_vector_ops.invoke_array_vector(
                Translator([], {}, {}), "Array.pad", arguments
            )

    large = wrap_array(np.ones((100, 100), dtype=np.int64))
    with pytest.raises(UnsupportedEEError, match="10000 cells"):
        invoke("Array.pad", array=large, lengths=[101, 100])

    translator = Translator([], {}, {})
    translator.steps = MAX_ARRAY_WORK - 1
    with pytest.raises(UnsupportedEEError, match="work budget"):
        array_vector_ops.invoke_array_vector(
            translator, "Array.pad", {"array": source, "lengths": [4]}
        )
    assert translator.steps == MAX_ARRAY_WORK - 1


@pytest.mark.parametrize("name", ["Array.unknown", "Array.matrixAdd"])
def test_dispatch_rejects_operations_outside_vector_family(name):
    with pytest.raises(UnsupportedEEError, match="Unsupported"):
        invoke(name)
