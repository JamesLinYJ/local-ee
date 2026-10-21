"""Pinned Python serialization and independent bounded static-value semantics."""
import json
import math
from pathlib import Path
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from gee.ee_translate import Translator, UnsupportedEEError, compile_expression
from gee.compat.earthengine.array_values import StaticArray
from gee.compat.earthengine.ir import Image, Pixel
from gee.compat.earthengine.static_equality import static_equal


ROOT = Path(__file__).resolve().parents[1]


def invoke(name, **arguments):
    return Translator([], {}, None).invoke(name, arguments)


def test_official_python_sdk_serialization_reaches_static_handlers():
    # Keep the SDK's process-global local session independent of other tests.
    program = textwrap.dedent("""
        import json
        from gee.ee_python_client import configure_local_ee
        from gee.ee_translate import compile_expression
        ee = configure_local_ee('http://127.0.0.1:8787/openeo/1.2', 'b' * 48,
                                signatures_path='vendor/earthengine-js/algorithms.json')
        dictionary = ee.Dictionary({'z': 9, 'a': 1, 'null': None})
        objects = {
            'empty': dictionary.values(keys=[]),
            'ordered': dictionary.values(keys=['z', 'a', 'z']),
            'all': dictionary.values(),
            'false_default': dictionary.get(key='missing', defaultValue=False),
            'empty_default': dictionary.get(key='missing', defaultValue=[]),
            'null_value': dictionary.get(key='null', defaultValue=17),
            'count': ee.List.sequence(start=0, end=1, count=5),
            'count_step': ee.List.sequence(start=4, step=-2, count=3),
            'precedence': ee.List.sequence(start=0, end=4, step=100, count=3),
            'array_contains': ee.List([ee.Array([1, 2]), ee.Array([3, 4])]).contains(ee.Array([1, 2])),
            'array_missing_shape': ee.List([ee.Array([1, 2])]).contains(ee.Array([[1, 2]])),
            'array_distinct': ee.List([ee.Array([1, 2]), ee.Array([1, 2]), ee.Array([[1, 2]])]).distinct(),
            'nested_contains': ee.List([{'a': [ee.Array([1, 2]), 0]}]).contains({'a': [ee.Array([1, 2]), 0]}),
            'number_contains': ee.List([ee.Number(1)]).contains(ee.Number(1.0)),
            'number_distinct': ee.List([ee.Number(1), ee.Number(1.0)]).distinct(),
            'nested_numbers': ee.List([{'a': [ee.Number(1)]}]).contains({'a': [ee.Number(1.0)]}),
        }
        results = {}
        for key, value in objects.items():
            encoded = ee.serializer.encode(value, for_cloud_api=False)
            results[key] = compile_expression(encoded, [], {})['value']
        print(json.dumps(results, allow_nan=False))
    """)
    result = subprocess.run([sys.executable, "-c", program], cwd=ROOT,
                            capture_output=True, text=True, check=True, timeout=15)
    assert json.loads(result.stdout) == {
        "empty": [], "ordered": [9, 1, 9], "all": [1, None, 9],
        "false_default": False, "empty_default": [], "null_value": None,
        "count": [0, 0.25, 0.5, 0.75, 1], "count_step": [4, 2, 0],
        "precedence": [0, 2, 4],
        "array_contains": True, "array_missing_shape": False,
        "array_distinct": [[1, 2], [[1, 2]]], "nested_contains": True,
        "number_contains": True, "number_distinct": [1], "nested_numbers": True,
    }


@pytest.mark.parametrize("default", [None, pytest.param(..., id="omitted")])
def test_dictionary_missing_key_rejects_null_or_omitted_default(default):
    args = {"dictionary": {"present": None}, "key": "missing"}
    if default is not ...:
        args["defaultValue"] = default
    with pytest.raises(UnsupportedEEError, match="does not contain key"):
        invoke("Dictionary.get", **args)
    assert invoke("Dictionary.get", dictionary={"present": None}, key="present",
                  defaultValue=99) is None


@pytest.mark.parametrize("default", [0, False, "", [], {}, [1, None]])
def test_dictionary_missing_key_returns_every_nonnull_default(default):
    assert invoke("Dictionary.get", dictionary={}, key="missing", defaultValue=default) == default


def test_dictionary_values_distinguishes_empty_null_order_and_duplicates():
    data = {"z": 9, "a": 1, "null": None}
    assert invoke("Dictionary.values", dictionary=data, keys=[]) == []
    assert invoke("Dictionary.values", dictionary=data, keys=None) == [1, None, 9]
    assert invoke("Dictionary.values", dictionary=data, keys=["z", "a", "z"]) == [9, 1, 9]
    assert invoke("Dictionary.keys", dictionary=data) == ["a", "null", "z"]
    with pytest.raises(UnsupportedEEError, match="does not contain key"):
        invoke("Dictionary.values", dictionary=data, keys=["missing"])
    assert data == {"z": 9, "a": 1, "null": None}


@pytest.mark.parametrize("name,args", [
    ("Dictionary.get", {"dictionary": {}, "key": []}),
    ("Dictionary.contains", {"dictionary": [], "key": "a"}),
    ("Dictionary.set", {"dictionary": {}, "key": "a"}),
    ("Dictionary.values", {"dictionary": {}, "keys": "a"}),
    ("Dictionary.values", {"dictionary": {}, "keys": [1]}),
    ("Dictionary.values", {"dictionary": {"a": 1}, "keys": ["a"] * 10001}),
])
def test_dictionary_invalid_arguments_fail_explicitly(name, args):
    with pytest.raises(UnsupportedEEError):
        invoke(name, **args)


@pytest.mark.parametrize("start,end,count", [(0, 10, 6), (5, -1, 4), (-0.2, 0.8, 7)])
def test_sequence_count_matches_independent_numpy_linspace(start, end, count):
    result = invoke("List.sequence", start=start, end=end, count=count)
    np.testing.assert_allclose(result, np.linspace(start, end, count), atol=1e-15, rtol=1e-15)
    assert result[0] == start and result[-1] == end


def test_sequence_count_precedence_and_missing_end():
    assert invoke("List.sequence", start=1, end=5, step=-100, count=3) == [1, 3, 5]
    assert invoke("List.sequence", start=1, end=5, step=0, count=3) == [1, 3, 5]
    assert invoke("List.sequence", start=2, step=-2, count=4) == [2, 0, -2, -4]
    assert invoke("List.sequence", start=2, count=3) == [2, 3, 4]
    assert invoke("List.sequence", start=2, step=0, count=3) == [2, 2, 2]
    assert invoke("List.sequence", start=2, end=5, count=0) == []
    assert invoke("List.sequence", start=2, end=5, count=1) == [2]


def test_sequence_step_direction_inclusive_endpoints_and_nondivisible_span():
    assert invoke("List.sequence", start=5, end=-1, step=-2) == list(range(5, -2, -2))
    assert invoke("List.sequence", start=0, end=5, step=2) == [0, 2, 4]
    assert invoke("List.sequence", start=5, end=0) == []
    assert invoke("List.sequence", start=0, end=5, step=-1) == []
    # Strict computed-Float64 bounds deliberately omit .30000000000000004.
    assert invoke("List.sequence", start=0, end=0.3, step=0.1) == [0, 0.1, 0.2]
    assert invoke("List.sequence", start=3, end=3) == [3]


def test_sequence_limits_cover_all_materialization_paths():
    assert len(invoke("List.sequence", start=0, end=9999)) == 10000
    assert len(invoke("List.sequence", start=0, count=10000)) == 10000
    for args in ({"start": 0, "end": 10000}, {"start": 0, "count": 10001},
                 {"start": 0, "end": 1e10, "step": 0.001}):
        with pytest.raises(UnsupportedEEError, match="10000"):
            invoke("List.sequence", **args)


@pytest.mark.parametrize("args", [
    {}, {"start": 0}, {"start": True, "count": 2}, {"start": "0", "end": 3},
    {"start": 0, "end": 3, "step": 0}, {"start": 0, "count": -1},
    {"start": 0, "count": 1.5}, {"start": 0, "count": True},
    {"start": 0, "count": float("inf")}, {"start": float("nan"), "end": 2},
    {"start": 0, "end": float("inf")}, {"start": 0, "end": 1, "step": float("nan")},
    {"start": 10**1000, "count": 2}, {"start": -1e308, "end": 1e308},
    {"start": 1e308, "step": 1e308, "count": 4},
])
def test_sequence_invalid_nonfinite_and_unbounded_inputs_fail(args):
    with pytest.raises(UnsupportedEEError):
        invoke("List.sequence", **args)


def test_sequence_finite_count_interpolation_avoids_intermediate_overflow():
    assert invoke("List.sequence", start=-1e308, end=1e308, count=3) == [-1e308, 0, 1e308]


def test_unknown_arguments_and_missing_defaults_are_stable_compiler_errors():
    for name, arguments in [
        ("List.sequence", {"start": 0, "end": 1, "unexpected": 2}),
        ("Dictionary.get", {"dictionary": {}, "key": "absent"}),
    ]:
        with pytest.raises(UnsupportedEEError):
            compile_expression({"type": "Invocation", "functionName": name,
                                "arguments": arguments}, [], {})


@pytest.mark.parametrize("arguments,expected", [
    ({"start": 0, "end": math.nextafter(1.0, 0), "step": 1}, [0]),
    ({"start": 0, "end": math.nextafter(-1.0, 0), "step": -1}, [0]),
    ({"start": 0, "end": 1.0, "step": 1}, [0, 1]),
    ({"start": 0, "end": 0.3, "step": 0.1}, [0, 0.1, 0.2]),
    ({"start": 0, "end": math.nextafter(0.3, math.inf), "step": 0.1},
     [0, 0.1, 0.2, 0.30000000000000004]),
])
def test_sequence_float64_endpoint_policy_never_crosses_supplied_end(arguments, expected):
    values = invoke("List.sequence", **arguments)
    assert values == expected
    if arguments["step"] > 0:
        assert all(value <= arguments["end"] for value in values)
    else:
        assert all(value >= arguments["end"] for value in values)


def array(value, dtype=None):
    return StaticArray(np.array(value, dtype=dtype))


def test_static_array_equality_preserves_shape_dtype_and_value_without_broadcasting():
    translator = Translator([], {}, None)
    assert static_equal(translator, array([1, 2]), array([1, 2]))
    assert not static_equal(translator, array([1, 2]), array([1, 3]))
    assert not static_equal(translator, array([1, 2]), array([[1, 2]]))
    assert not static_equal(translator, array([1, 2]), [1, 2])
    assert not static_equal(translator, array([1, 2]), array([1.0, 2.0]))
    assert not static_equal(translator, array([1, 2], dtype=np.int32),
                            array([1, 2], dtype=np.int64))


def test_recursive_static_equality_handles_nested_dictionary_and_list_arrays():
    translator = Translator([], {}, None)
    left = {"z": [array([[1, 2], [3, 4]]), None], "a": False}
    right = {"a": False, "z": [array([[1, 2], [3, 4]]), None]}
    assert static_equal(translator, left, right)
    right["z"][0] = array([[1, 2], [4, 3]])
    assert not static_equal(translator, left, right)
    assert not static_equal(translator, [True], [1])
    assert static_equal(translator, [1], [1.0])
    assert static_equal(translator, {"a": [1]}, {"a": [1.0]})
    assert not static_equal(translator, 2**53 + 1, float(2**53))
    assert static_equal(translator, "", "")


def test_list_contains_and_distinct_arrays_preserve_first_occurrence():
    first, same, other_shape = array([1, 2]), array([1, 2]), array([[1, 2]])
    values = [first, same, other_shape]
    assert invoke("List.contains", list=values, element=array([1, 2])) is True
    assert invoke("List.contains", list=values, element=array([2, 1])) is False
    result = invoke("List.distinct", list=values)
    assert len(result) == 2 and result[0] is first and result[1] is other_shape
    result = invoke("List.distinct", list=[0, False, 0.0, False, 0])
    assert len(result) == 2 and type(result[0]) is int and type(result[1]) is bool


@pytest.mark.parametrize("unsupported", [Image([], {}), Pixel("constant", (1,)), object()])
def test_static_equality_rejects_unsupported_ir_even_inside_mismatched_containers(unsupported):
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="does not support"):
        static_equal(translator, [unsupported], [])
    with pytest.raises(UnsupportedEEError, match="does not support"):
        invoke("List.contains", list=[], element={"nested": unsupported})
    with pytest.raises(UnsupportedEEError, match="does not support"):
        invoke("List.distinct", list=[unsupported])


def test_static_equality_charges_cell_and_list_work_to_shared_translator_budget():
    translator = Translator([], {}, None)
    assert static_equal(translator, array([1, 2, 3]), array([1, 2, 3]))
    assert translator.steps >= 9
    translator.steps = 49998
    with pytest.raises(UnsupportedEEError, match="work budget"):
        static_equal(translator, array([1, 2]), array([1, 2]))
    assert translator.steps <= 50000
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        translator.invoke("List.distinct", {"list": list(range(1000))})
    assert translator.steps <= 50000


def test_static_equality_large_arrays_and_repeated_comparisons_cannot_reset_budget():
    translator = Translator([], {}, None)
    value = array(np.arange(10000))
    assert static_equal(translator, value, value)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        static_equal(translator, value, value)
    assert translator.steps <= 50000


def test_static_equality_bounds_depth_and_rejects_nonfinite_values():
    nested = None
    for _ in range(100):
        nested = [nested]
    with pytest.raises(UnsupportedEEError, match="nesting limit"):
        static_equal(Translator([], {}, None), nested, nested)
    for value in [float("nan"), array([float("inf")]), array([True]), (1, 2)]:
        with pytest.raises(UnsupportedEEError):
            static_equal(Translator([], {}, None), value, value)
