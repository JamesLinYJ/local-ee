"""Finite, bounded Reducer.toList and Reducer.toCollection leaves."""
import json

import numpy as np
import pytest

from gee.compat.earthengine import collecting_reducers as collecting
from gee.compat.earthengine import collecting_reducer_values as collecting_values
from gee.compat.earthengine.array_values import StaticArray
from gee.compat.earthengine.collecting_reducers import (
    COLLECTING_REDUCER_NAMES,
    CollectingReducerLeaf,
    describe_collecting_reducer,
    make_collecting_reducer,
    reduce_collecting_reducer,
)
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.public_values import public_value


def translator():
    return Translator([], {}, {})


def invoke(name, args, rows):
    t = translator()
    leaf = make_collecting_reducer(t, name, args)
    return t, leaf, reduce_collecting_reducer(t, leaf, rows)


def test_constructor_names_defaults_and_canonical_snapshots():
    t = translator()
    assert COLLECTING_REDUCER_NAMES == {
        "Reducer.toList", "Reducer.toCollection",
    }
    default = make_collecting_reducer(t, "Reducer.toList", {})
    explicit_null = make_collecting_reducer(
        t, "Reducer.toList", {"tupleSize": None, "numOptional": None},
    )
    assert type(default) is CollectingReducerLeaf
    assert describe_collecting_reducer(t, default) == (1, ("list",))
    assert describe_collecting_reducer(t, explicit_null) == (1, ("list",))

    source_names = ["x", "y"]
    collection = make_collecting_reducer(
        t, "Reducer.toCollection", {"propertyNames": source_names},
    )
    source_names[0] = "changed"
    assert collection.property_names == ("x", "y")
    assert describe_collecting_reducer(t, collection) == (2, ("collection",))


def test_to_list_default_returns_scalars_and_owns_nested_json_values():
    original = {"nested": [1, {"v": "kept"}]}
    _, _, pairs = invoke(
        "Reducer.toList", {}, [[1], [original], [None], [3]],
    )
    assert pairs == [("list", [1, original, 3])]
    result = pairs[0][1]
    assert result[1] is not original
    assert result[1]["nested"] is not original["nested"]
    result[1]["nested"][1]["v"] = "changed"
    assert original["nested"][1]["v"] == "kept"


def test_to_list_explicit_tuple_size_returns_tuples_and_handles_optional_tail():
    _, _, pairs = invoke(
        "Reducer.toList",
        {"tupleSize": 3, "numOptional": 2},
        [[1, None, "a"], [None, "drop", "required"], [2, None, None]],
    )
    assert pairs == [("list", [[1, None, "a"], [2, None, None]])]

    _, _, one_tuple = invoke(
        "Reducer.toList", {"tupleSize": 1}, [[1], [None], [2]],
    )
    assert one_tuple == [("list", [[1], [2]])]


def test_to_list_all_optional_nulls_are_retained_and_empty_input_is_empty_list():
    _, _, all_optional = invoke(
        "Reducer.toList", {"tupleSize": 2, "numOptional": 2},
        [[None, None], [None, 5]],
    )
    assert all_optional == [("list", [[None, None], [None, 5]])]

    _, _, empty = invoke("Reducer.toList", {}, [])
    assert empty == [("list", [])]


def test_to_collection_emits_null_geometry_owned_features_without_ids():
    shared = {"nested": [1]}
    _, _, pairs = invoke(
        "Reducer.toCollection",
        {"propertyNames": ["left", "right"], "numOptional": 1},
        [["keep", shared], [None, {"bad": True}], ["keep", shared]],
    )
    expected = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None,
             "properties": {"left": "keep", "right": {"nested": [1]}}},
            {"type": "Feature", "geometry": None,
             "properties": {"left": "keep", "right": {"nested": [1]}}},
        ],
    }
    assert pairs == [("collection", expected)]
    features = pairs[0][1]["features"]
    assert all("id" not in feature for feature in features)
    first = features[0]["properties"]["right"]
    second = features[1]["properties"]["right"]
    assert first is not shared and second is not shared and first is not second
    first["nested"].append(9)
    assert shared == {"nested": [1]}
    assert second == {"nested": [1]}


def test_to_collection_preserves_null_optional_property_and_empty_rows():
    _, _, pairs = invoke(
        "Reducer.toCollection",
        {"propertyNames": ["required", "optional"], "numOptional": 1},
        [[4, None], [None, 5]],
    )
    assert pairs == [("collection", {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": None,
                      "properties": {"required": 4, "optional": None}}],
    })]

    _, _, empty = invoke(
        "Reducer.toCollection", {"propertyNames": ["x"], "numOptional": None}, [],
    )
    assert empty == [("collection", {"type": "FeatureCollection", "features": []})]


def test_to_collection_supports_32_inputs_and_1000_rows():
    names = [f"p{index}" for index in range(32)]
    row = list(range(32))
    _, leaf, result = invoke(
        "Reducer.toCollection", {"propertyNames": names}, [row],
    )
    assert describe_collecting_reducer(translator(), leaf) == (32, ("collection",))
    assert result[0][1]["features"][0]["properties"] == dict(zip(names, row))

    _, _, full = invoke("Reducer.toList", {}, [[index] for index in range(1000)])
    assert len(full[0][1]) == 1000
    t = translator()
    leaf = make_collecting_reducer(t, "Reducer.toList", {})
    with pytest.raises(UnsupportedEEError, match="1000 input rows"):
        reduce_collecting_reducer(t, leaf, [[index] for index in range(1001)])


@pytest.mark.parametrize("name,args", [
    ("Reducer.toList", {"tupleSize": 0}),
    ("Reducer.toList", {"tupleSize": 33}),
    ("Reducer.toList", {"numOptional": 2}),
    ("Reducer.toList", {"extra": 1}),
    ("Reducer.toCollection", {"propertyNames": []}),
    ("Reducer.toCollection", {"propertyNames": ["x", "x"]}),
    ("Reducer.toCollection", {"propertyNames": [""]}),
    ("Reducer.toCollection", {"propertyNames": [".geo"]}),
    ("Reducer.toCollection", {"propertyNames": [".id"]}),
    ("Reducer.toCollection", {"propertyNames": ["system:index"]}),
    ("Reducer.toCollection", {"propertyNames": ["x"], "numOptional": 2}),
    ("Reducer.toCollection", {"propertyNames": ["x"], "other": 1}),
])
def test_invalid_parameters_are_rejected(name, args):
    with pytest.raises(UnsupportedEEError):
        make_collecting_reducer(translator(), name, args)


def test_property_names_and_reducer_descriptors_are_fully_revalidated():
    t = translator()
    leaf = make_collecting_reducer(
        t, "Reducer.toCollection", {"propertyNames": ["x", "y"]},
    )
    object.__setattr__(leaf, "property_names", ("x", "x"))
    with pytest.raises(UnsupportedEEError, match="unique"):
        describe_collecting_reducer(t, leaf)

    t = translator()
    list_leaf = make_collecting_reducer(t, "Reducer.toList", {})
    object.__setattr__(list_leaf, "tuple_size", True)
    with pytest.raises(UnsupportedEEError, match="tupleSize"):
        reduce_collecting_reducer(t, list_leaf, [[1]])


def test_all_values_are_scanned_even_when_required_null_drops_the_row():
    cyclic = []
    cyclic.append(cyclic)
    t = translator()
    leaf = make_collecting_reducer(
        t, "Reducer.toList", {"tupleSize": 2, "numOptional": 1},
    )
    with pytest.raises(UnsupportedEEError, match="cycles"):
        reduce_collecting_reducer(t, leaf, [[None, cyclic]])

    t = translator()
    leaf = make_collecting_reducer(t, "Reducer.toCollection", {"propertyNames": ["x"]})
    with pytest.raises(UnsupportedEEError, match="exactly 1 inputs"):
        reduce_collecting_reducer(t, leaf, [[1, 2]])


def test_nested_cycles_depth_oversized_keys_and_unsupported_typed_objects_reject():
    cyclic = {"back": None}
    cyclic["back"] = cyclic
    with pytest.raises(UnsupportedEEError, match="cycles"):
        invoke("Reducer.toList", {}, [[cyclic]])

    nested = []
    for _ in range(98):
        nested = [nested]
    with pytest.raises(UnsupportedEEError, match="depth 96"):
        invoke("Reducer.toList", {}, [[nested]])

    with pytest.raises(UnsupportedEEError, match="10000-character"):
        invoke("Reducer.toList", {}, [[{"k" * 10_001: 1}]])

    with pytest.raises(UnsupportedEEError, match="not object"):
        invoke("Reducer.toList", {}, [[object()]])


def test_output_json_size_and_shared_work_limits_are_enforced_before_copy(monkeypatch):
    with pytest.raises(UnsupportedEEError, match="1 MB"):
        invoke("Reducer.toList", {}, [["x" * 1_000_001]])

    payload = [[{"nested": [1]}]]
    probe = translator()
    probe_leaf = make_collecting_reducer(probe, "Reducer.toList", {})
    probe_start = probe.steps
    original_charge = collecting_values._charge
    final_charge = []

    def observe_charge(target, work, label):
        if label == "Reducer.toList owned output copy":
            final_charge.append((target.steps, work))
        return original_charge(target, work, label)

    monkeypatch.setattr(collecting_values, "_charge", observe_charge)
    reduce_collecting_reducer(probe, probe_leaf, payload)
    assert len(final_charge) == 1
    pre_copy_steps, copy_work = final_charge[0]
    pre_copy_delta = pre_copy_steps - probe_start

    t = translator()
    leaf = make_collecting_reducer(t, "Reducer.toList", {})
    t.steps = collecting.MAX_TRANSLATOR_WORK - pre_copy_delta - 1
    copied = []

    def observe_copy(value):
        copied.append(value)
        return value

    monkeypatch.setattr(collecting_values, "_copy_value", observe_copy)
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reduce_collecting_reducer(t, leaf, payload)
    assert copied == []
    assert t.steps == collecting.MAX_TRANSLATOR_WORK - 1
    assert copy_work > 0


def test_static_array_values_keep_the_public_array_shape_and_are_owned():
    source_array = StaticArray(np.array([[1.0, 2.0], [3.0, 4.0]]))
    _, _, pairs = invoke("Reducer.toList", {}, [[source_array]])
    result = pairs[0][1][0]
    assert type(result) is StaticArray
    assert result is not source_array
    assert result.data.tolist() == [[1.0, 2.0], [3.0, 4.0]]
    assert not result.data.flags.writeable


def test_nested_static_array_is_owned_and_materializes_at_public_boundary():
    source_array = StaticArray(np.array([[1, 2], [3, 4]], dtype=np.int64))
    source = {"nested": [source_array]}
    _, _, pairs = invoke("Reducer.toList", {}, [[source]])
    result = pairs[0][1][0]
    nested_array = result["nested"][0]
    assert type(nested_array) is StaticArray
    assert nested_array is not source_array
    assert nested_array.data.tolist() == [[1, 2], [3, 4]]
    assert not nested_array.data.flags.writeable
    assert public_value(result) == {"nested": [[[1, 2], [3, 4]] ]}


def test_repeated_property_name_output_bytes_are_preflighted_before_copy(monkeypatch):
    t = translator()
    leaf = make_collecting_reducer(
        t, "Reducer.toCollection", {"propertyNames": ["p" * 10]},
    )
    rows = [[index] for index in range(10)]
    monkeypatch.setattr(collecting_values, "MAX_PUBLIC_BYTES", 180)
    copied = []

    def observe_copy(value):
        copied.append(value)
        return value

    monkeypatch.setattr(collecting_values, "_copy_value", observe_copy)
    with pytest.raises(UnsupportedEEError, match="1 MB"):
        reduce_collecting_reducer(t, leaf, rows)
    assert copied == []


def test_recursive_preflight_matches_default_json_spacing_for_owned_values():
    payload = {"first": [1, {"second": "é"}], "last": False}
    t = translator()
    wire = [0]
    collecting_values._scan_value(t, payload, wire, set())
    assert wire[0] == len(json.dumps(payload, allow_nan=False))

    array_value = StaticArray(np.array([[1, 2, 3], [4, 5, 6]], dtype=np.int64))
    t = translator()
    wire = [0]
    collecting_values._scan_value(t, array_value, wire, set())
    assert wire[0] == len(json.dumps(array_value.to_value(), allow_nan=False))


@pytest.mark.parametrize("values", [
    np.array([2**53 + 1], dtype=np.int64),
    np.array([2**53 + 1], dtype=np.uint64),
    np.array([1], dtype=object),
])
def test_static_array_requires_supported_dtype_and_exact_integer_domain(values):
    with pytest.raises(UnsupportedEEError):
        invoke("Reducer.toList", {}, [[StaticArray(values)]])


def test_static_array_rejects_extended_precision_float_dtype_when_available():
    dtype = np.dtype(np.longdouble)
    if dtype.itemsize <= 8:
        pytest.skip("platform long double is not wider than Float64")
    with pytest.raises(UnsupportedEEError, match="bounded numeric"):
        invoke("Reducer.toList", {}, [[StaticArray(np.array([1], dtype=dtype))]])
