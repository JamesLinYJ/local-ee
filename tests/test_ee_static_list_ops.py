"""Pinned static List API contracts, semantics and bounded rejection paths."""
import json
from pathlib import Path
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from gee.ee_translate import Translator, UnsupportedEEError, compile_expression
from gee.compat.earthengine.static_list_ops import LIST_EXTRA_FUNCTIONS, _ARGUMENTS
from gee.compat.earthengine.array_values import StaticArray
from gee.compat.earthengine.ir import Image, Pixel
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.compat.earthengine.static_equality import static_equal


ROOT = Path(__file__).resolve().parents[1]


def invoke(name, **arguments):
    return Translator([], {}, None).invoke(name, arguments)


def test_supported_names_and_arguments_match_pinned_algorithm_metadata():
    metadata = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())
    definitions = {
        item["name"].removeprefix("algorithms/"): item
        for item in metadata["algorithms"]
        if item["name"].removeprefix("algorithms/") in LIST_EXTRA_FUNCTIONS
    }
    assert set(definitions) == LIST_EXTRA_FUNCTIONS
    for name, definition in definitions.items():
        args = definition["arguments"]
        assert {item["argumentName"] for item in args} == _ARGUMENTS[name]
        if name == "List.join":
            separator = next(item for item in args if item["argumentName"] == "separator")
            assert separator["optional"] is True and separator["defaultValue"] == ""
        if name == "List.splice":
            other = next(item for item in args if item["argumentName"] == "other")
            assert other["optional"] is True and other["defaultValue"] is None


def test_official_python_sdk_serialization_compiles_pinned_list_operations():
    program = textwrap.dedent("""
        import json
        from gee.ee_python_client import configure_local_ee
        from gee.ee_translate import compile_expression
        ee = configure_local_ee('http://127.0.0.1:8787/openeo/1.2', 'c' * 48,
                                signatures_path='vendor/earthengine-js/algorithms.json')
        values = ee.List([1, None, 1, 'x'])
        point = ee.Geometry.Point([1, 2], proj='EPSG:4326', geodesic=False)
        objects = {
            'contains_all': ee.List([1, 1, None]).containsAll([1, 1, 1]),
            'equals': ee.List([1, None]).equals([1, None]),
            'frequency': values.frequency(1),
            'first': values.indexOf(1),
            'missing': values.indexOf('missing'),
            'sublist': ee.List([1, 2, 1, 2]).indexOfSublist([1, 2]),
            'last_sublist': ee.List([1, 2, 1, 2]).lastIndexOfSubList([1, 2]),
            'insert': ee.List([1, 2, 3]).insert(-1, 9),
            'remove': values.remove(1),
            'remove_all': values.removeAll([1]),
            'replace': ee.List([1, 1, 2]).replace(1, 7),
            'replace_all': ee.List([1, 1, 2]).replaceAll(1, 7),
            'rotate': ee.List([1, 2, 3, 4]).rotate(1),
            'splice': ee.List([1, 2, 3, 4]).splice(-2, 1, [8, 9]),
            'splice_insert': ee.List([1, 2, 3, 4]).splice(2, 0, ['X', 'Y']),
            'splice_default': ee.List([1, 2, 3, 4]).splice(start=1, count=2),
            'join_default': ee.List(['a', 'b']).join(),
            'join': ee.List(['a', True, 2.0]).join(separator='|'),
            'number': ee.List([4, 9]).getNumber(-1),
            'string': ee.List(['a', 'b']).getString(-1),
            'array': ee.List([ee.Array([[1, 2], [3, 4]])]).getArray(-1),
            'geometry': ee.List([point]).getGeometry(-1),
        }
        output = {}
        for key, value in objects.items():
            encoded = ee.serializer.encode(value, for_cloud_api=False)
            output[key] = compile_expression(encoded, [], {})['value']
        print(json.dumps(output, allow_nan=False))
    """)
    result = subprocess.run([sys.executable, "-c", program], cwd=ROOT,
                            capture_output=True, text=True, check=True, timeout=20)
    assert json.loads(result.stdout) == {
        "contains_all": True, "equals": True, "frequency": 2, "first": 0,
        "missing": -1, "sublist": 0, "last_sublist": 2,
        "insert": [1, 2, 9, 3], "remove": [None, 1, "x"],
        "remove_all": [None, "x"], "replace": [7, 1, 2],
        "replace_all": [7, 7, 2], "rotate": [4, 1, 2, 3],
        "splice": [1, 2, 8, 9, 4], "splice_insert": [1, 2, "X", "Y", 3, 4],
        "splice_default": [1, 4],
        "join_default": "ab",
        "join": "a|true|2", "number": 9, "string": "b",
        "array": [[1, 2], [3, 4]],
        "geometry": {"type": "Point", "coordinates": [1, 2]},
    }


def test_official_python_sdk_rejects_unsafe_integers_on_new_list_paths():
    program = textwrap.dedent("""
        import json
        from gee.ee_python_client import configure_local_ee
        from gee.ee_translate import compile_expression, UnsupportedEEError
        ee = configure_local_ee('http://127.0.0.1:8787/openeo/1.2', 'c' * 48,
                                signatures_path='vendor/earthengine-js/algorithms.json')
        unsafe = 2**53 + 1
        objects = {
            'direct': ee.List([unsafe]).rotate(0),
            'nested': ee.List([{'nested': [unsafe]}]).rotate(0),
            'getter': ee.List([unsafe]).getNumber(0),
            'equals': ee.List([unsafe]).equals([unsafe]),
            'search': ee.List([1]).indexOf(unsafe),
            'insert': ee.List([]).insert(0, unsafe),
            'positive_limit': ee.List([2**53]).getNumber(0),
            'negative_limit': ee.List([-(2**53)]).getNumber(0),
            'limit_equals': ee.List([2**53, -(2**53)]).equals([2**53, -(2**53)]),
        }
        rejected = []
        accepted = {}
        for key, value in objects.items():
            encoded = ee.serializer.encode(value, for_cloud_api=False)
            try:
                accepted[key] = compile_expression(encoded, [], {})['value']
            except UnsupportedEEError:
                rejected.append(key)
        print(json.dumps({'rejected': rejected, 'accepted': accepted}, allow_nan=False))
    """)
    result = subprocess.run([sys.executable, "-c", program], cwd=ROOT,
                            capture_output=True, text=True, check=True, timeout=20)
    output = json.loads(result.stdout)
    assert set(output["rejected"]) == {
        "direct", "nested", "getter", "equals", "search", "insert",
    }
    assert output["accepted"] == {
        "positive_limit": 2**53,
        "negative_limit": -(2**53),
        "limit_equals": True,
    }


@pytest.mark.parametrize(("name", "arguments", "expected"), [
    ("List.containsAll", {"list": [2, 1, 2], "other": [1, 1]}, True),
    ("List.containsAll", {"list": [1], "other": [1, 2]}, False),
    ("List.equals", {"list": [1, None, 1], "other": [1, None, 1]}, True),
    ("List.equals", {"list": [1, 1], "other": [1]}, False),
    ("List.frequency", {"list": [None, 1, None, False], "element": None}, 2),
    ("List.indexOf", {"list": [1, 2, 1], "element": 1}, 0),
    ("List.indexOfSublist", {"list": [1, 2, 1, 2], "target": [1, 2]}, 0),
    ("List.lastIndexOfSubList", {"list": [1, 2, 1, 2], "target": [1, 2]}, 2),
    ("List.indexOfSublist", {"list": [1, 2], "target": []}, 0),
    ("List.lastIndexOfSubList", {"list": [1, 2], "target": []}, 2),
    ("List.rotate", {"list": [], "distance": 5}, []),
    ("List.insert", {"list": [1, 2, 3], "index": -1, "element": 8}, [1, 2, 8, 3]),
    ("List.insert", {"list": [1, 2], "index": -2, "element": 8}, [8, 1, 2]),
    ("List.insert", {"list": [1, 2], "index": 2, "element": 8}, [1, 2, 8]),
    ("List.remove", {"list": [1, 2, 1], "element": 1}, [2, 1]),
    ("List.removeAll", {"list": [1, 2, 1, None], "other": [1]}, [2, None]),
    ("List.replace", {"list": [1, 1], "oldval": 1, "newval": 9}, [9, 1]),
    ("List.replaceAll", {"list": [1, 1], "oldval": 1, "newval": 9}, [9, 9]),
    ("List.rotate", {"list": [1, 2, 3, 4], "distance": -1}, [2, 3, 4, 1]),
    ("List.rotate", {"list": [1, 2, 3, 4], "distance": 5}, [4, 1, 2, 3]),
    ("List.splice", {"list": [1, 2, 3, 4], "start": -2, "count": 1, "other": [8, 9]}, [1, 2, 8, 9, 4]),
    ("List.splice", {"list": [], "start": 0, "count": 0}, []),
    ("List.join", {"list": ["a", True, 2.0], "separator": "|"}, "a|true|2"),
    ("List.join", {"list": []}, ""),
])
def test_list_operations_match_independent_sequence_expectations(name, arguments, expected):
    before = {key: list(value) if type(value) is list else value
              for key, value in arguments.items()}
    result = invoke(name, **arguments)
    assert result == expected
    if type(expected) is list:
        assert result is not arguments["list"]
    for key, value in before.items():
        if type(value) is list:
            assert arguments[key] == value


def test_typed_getters_support_negative_indexes_and_reject_mismatches():
    assert invoke("List.getNumber", list=[2, 4], index=-1) == 4
    assert invoke("List.getString", list=["a", "b"], index=-2) == "a"
    array_value = StaticArray(np.array([1, 2]))
    assert invoke("List.getArray", list=[array_value], index=-1) is array_value
    for name, values in [
        ("List.getNumber", [True]), ("List.getString", [2]),
        ("List.getArray", [[1, 2]]), ("List.getGeometry", [{"type": "Point", "coordinates": [1, 2], "geodesic": True}]),
    ]:
        with pytest.raises(UnsupportedEEError):
            invoke(name, list=values, index=0)
    with pytest.raises(UnsupportedEEError, match="bounds"):
        invoke("List.getNumber", list=[], index=-1)


def test_geometry_getter_revalidates_and_owns_known_geometry_subclass():
    source = GeometryValue(
        {"type": "Point", "coordinates": [1, 2]},
        {"geodesic": False}, validated=True,
    )
    translator = Translator([], {}, None)
    result = translator.invoke("List.getGeometry", {"list": [source], "index": 0})
    assert type(result) is GeometryValue
    assert result == source
    assert result.geometry_metadata == {"geodesic": False}
    assert result.geometry_metadata is not source.geometry_metadata
    result["coordinates"][0] = 99
    assert source["coordinates"] == [1, 2]
    assert translator.steps > 0

    source["coordinates"][0] = 181
    with pytest.raises(UnsupportedEEError, match="coordinates"):
        invoke("List.getGeometry", list=[source], index=0)

    flagged = GeometryValue(
        {"type": "Point", "coordinates": [1, 2]}, validated=True,
    )
    flagged["geodesic"] = True
    with pytest.raises(UnsupportedEEError, match="spherical"):
        invoke("List.getGeometry", list=[flagged], index=0)

    class ForeignGeometry(dict):
        pass

    with pytest.raises(UnsupportedEEError, match="ForeignGeometry"):
        invoke("List.getGeometry", list=[ForeignGeometry({
            "type": "Point", "coordinates": [1, 2],
        })], index=0)


@pytest.mark.parametrize("unsupported", [Image([], {}), Pixel("constant", (1,)), object()])
def test_list_operations_reject_opaque_or_dynamic_values(unsupported):
    for name, arguments in [
        ("List.rotate", {"list": [unsupported], "distance": 1}),
        ("List.indexOf", {"list": [], "element": unsupported}),
    ]:
        with pytest.raises(UnsupportedEEError, match="does not support"):
            invoke(name, **arguments)


def test_list_bad_arguments_bounds_limits_and_shared_work_budget_are_stable():
    for name, arguments in [
        ("List.insert", {"list": [1], "index": 2, "element": 3}),
        ("List.splice", {"list": [1], "start": -2, "count": 0}),
        ("List.splice", {"list": [1], "start": 0, "count": -1}),
        ("List.rotate", {"list": [1], "distance": 1.5}),
        ("List.join", {"list": [None]}),
        ("List.getNumber", {"list": [1], "index": 0, "ignored": True}),
        ("List.remove", {"list": [1]}),
    ]:
        with pytest.raises(UnsupportedEEError):
            invoke(name, **arguments)
    with pytest.raises(UnsupportedEEError, match="10000"):
        invoke("List.rotate", list=list(range(10001)), distance=1)
    with pytest.raises(UnsupportedEEError, match="10000"):
        invoke("List.insert", list=list(range(10000)), index=0, element=1)
    translator = Translator([], {}, None)
    translator.steps = 49_995
    with pytest.raises(UnsupportedEEError, match="work budget"):
        translator.invoke("List.frequency", {"list": [1], "element": 1})
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke("List.join", list=["x" * 50_001])


def test_list_nested_dictionary_and_array_equality_uses_typed_shared_semantics():
    first = {"nested": [StaticArray(np.array([[1, 2], [3, 4]])), None]}
    same = {"nested": [StaticArray(np.array([[1, 2], [3, 4]])), None]}
    different_shape = {"nested": [StaticArray(np.array([1, 2, 3, 4])), None]}
    assert invoke("List.frequency", list=[first, same], element=first) == 2
    assert invoke("List.containsAll", list=[first], other=[same]) is True
    assert invoke("List.indexOf", list=[first, different_shape], element=same) == 0
    assert invoke("List.equals", list=[first], other=[different_shape]) is False


def test_exact_integer_validation_is_opt_in_recursive_and_charged_before_array_scan():
    unsafe = 2**53 + 1
    for value in [
        unsafe,
        {"nested": [unsafe]},
        [StaticArray(np.array([unsafe]))],
        StaticArray(np.array([unsafe], dtype=np.uint64)),
    ]:
        with pytest.raises(UnsupportedEEError, match="exact Float64 domain"):
            static_equal(Translator([], {}, None), value, value, exact_integers=True)
    for value in [
        2**53,
        -(2**53),
        {"nested": [2**53, -(2**53)]},
        StaticArray(np.array([2**53, -(2**53)], dtype=np.int64)),
    ]:
        assert static_equal(Translator([], {}, None), value, value, exact_integers=True)

    legacy = Translator([], {}, None)
    assert not static_equal(legacy, unsafe, float(2**53))
    translator = Translator([], {}, None)
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        static_equal(translator, StaticArray(np.array([unsafe])),
                     StaticArray(np.array([unsafe])), exact_integers=True)


def test_new_list_search_insert_equals_and_number_getter_reject_unsafe_integers():
    unsafe = 2**53 + 1
    for name, arguments in [
        ("List.rotate", {"list": [unsafe], "distance": 0}),
        ("List.rotate", {"list": [{"nested": [unsafe]}], "distance": 0}),
        ("List.getNumber", {"list": [unsafe], "index": 0}),
        ("List.equals", {"list": [unsafe], "other": [unsafe]}),
        ("List.indexOf", {"list": [1], "element": unsafe}),
        ("List.insert", {"list": [], "index": 0, "element": unsafe}),
    ]:
        with pytest.raises(UnsupportedEEError, match="exact Float64 domain"):
            invoke(name, **arguments)
    assert invoke("List.getNumber", list=[2**53], index=0) == 2**53
    assert invoke("List.getNumber", list=[-(2**53)], index=0) == -(2**53)


def test_unknown_list_operation_remains_an_explicit_compiler_error():
    with pytest.raises(UnsupportedEEError, match="Unsupported"):
        compile_expression({"type": "Invocation", "functionName": "List.shuffle",
                            "arguments": {"list": [1, 2]}}, [], {})
