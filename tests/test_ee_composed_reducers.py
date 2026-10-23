"""Pinned reducer composition syntax and bounded table/list evaluation."""
from copy import deepcopy
from pathlib import Path

import pytest
import numpy as np

from gee.compat.earthengine.composed_reducers import (
    ReducerSpec,
    as_reducer_spec,
    invoke_composed_reducer,
    is_reducer_spec,
)
from gee.compat.earthengine.composed_reducer_tables import reduce_columns
from gee.compat.earthengine.composed_reducer_values import reduce_list, reduce_records
from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Reducer, UnsupportedEEError
from gee.compat.earthengine.table_reducers import TableReducer
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def output(ee, value):
    encoded = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(encoded, [], {})["value"]


def feature_collection(rows):
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": None, "properties": row}
            for row in rows
        ],
    }


def invoke(name, arguments, translator=None):
    translator = translator or Translator([], {}, {})
    return translator, invoke_composed_reducer(translator, name, arguments)


def test_sdk_group_combine_set_outputs_reduce_columns_and_independent_values(ee):
    rows = ee.FeatureCollection([
        ee.Feature(None, {"zone": "north", "value": 10}),
        ee.Feature(None, {"zone": "north", "value": 12}),
        ee.Feature(None, {"zone": "south", "value": 20}),
        ee.Feature(None, {"zone": "south", "value": 22}),
    ])
    reducer = (
        ee.Reducer.mean()
        .combine(ee.Reducer.sum(), sharedInputs=True)
        .combine(ee.Reducer.count(), sharedInputs=True)
        .setOutputs(["average", "total", "n"])
        .group(groupField=1, groupName="zone")
    )
    result = rows.reduceColumns(reducer, ["value", "zone"])
    assert output(ee, result) == {
        "groups": [
            {"zone": "north", "average": 11, "total": 22, "n": 2},
            {"zone": "south", "average": 21, "total": 42, "n": 2},
        ],
    }


def test_composed_specs_never_enter_raster_reducer_consumers(ee):
    image = ee.Image.constant(1)
    reducer = ee.Reducer.mean().combine(ee.Reducer.sum(), sharedInputs=True)
    with pytest.raises(UnsupportedEEError, match="static List.reduce"):
        output(ee, image.reduce(reducer))


def test_sdk_combine_shared_and_concatenated_input_modes(ee):
    rows = ee.FeatureCollection([
        ee.Feature(None, {"x": 1, "y": 10}),
        ee.Feature(None, {"x": 3, "y": 30}),
    ])
    shared = ee.Reducer.mean().combine(
        ee.Reducer.sum(), outputPrefix="right_", sharedInputs=True,
    )
    assert output(ee, rows.reduceColumns(shared, ["x"])) == {
        "mean": 2, "right_sum": 4,
    }
    separate = ee.Reducer.mean().combine(
        ee.Reducer.sum(), outputPrefix="right_", sharedInputs=False,
    )
    assert output(ee, rows.reduceColumns(separate, ["x", "y"])) == {
        "mean": 2, "right_sum": 40,
    }


@pytest.mark.parametrize(("name", "output_name", "expected"), [
    ("sum", "sum", 6), ("mean", "mean", 3), ("min", "min", 2),
    ("max", "max", 4), ("count", "count", 2), ("first", "first", 2),
    ("last", "last", 4), ("median", "median", 3),
    ("sampleStdDev", "stdDev", 2**0.5),
])
def test_sdk_scalar_reducer_leaves_execute_in_reduce_columns(ee, name, output_name, expected):
    collection = ee.FeatureCollection([
        ee.Feature(None, {"value": 2}),
        ee.Feature(None, {"value": None}),
        ee.Feature(None, {"value": 4}),
    ])
    reducer = getattr(ee.Reducer, name)()
    result = output(ee, collection.reduceColumns(reducer, ["value"]))
    assert result == pytest.approx({output_name: expected})


def test_get_outputs_is_static_and_set_outputs_null_or_empty_names_drop_outputs(ee):
    reducer = ee.Reducer.mean().combine(ee.Reducer.sum(), sharedInputs=True)
    assert output(ee, reducer.getOutputs()) == ["mean", "sum"]
    dropped = reducer.setOutputs([None, ""])
    assert output(ee, ee.FeatureCollection([]).reduceColumns(dropped, ["x"])) == {}


def test_list_reduce_composed_results_preserve_sdk_single_and_multiple_shapes(ee):
    values = ee.List([1, 2, 3])
    single = ee.Reducer.mean().setOutputs(["average"])
    multiple = ee.Reducer.mean().combine(ee.Reducer.sum(), sharedInputs=True)
    assert output(ee, values.reduce(single)) == 2
    assert output(ee, values.reduce(multiple)) == {"mean": 2, "sum": 6}


def test_combine_and_group_can_be_built_from_existing_regression_and_scalar_leaves():
    translator = Translator([], {}, {})
    fit = TableReducer("linearFit", 1, 1)
    reducer = invoke_composed_reducer(
        translator, "Reducer.combine",
        {"reducer1": fit, "reducer2": Reducer("sum"), "sharedInputs": False},
    )
    assert reducer.input_count == 3
    rows = [[0, 1, 4], [1, 3, 6], [2, 5, 8]]
    result = reduce_records(translator, rows, reducer)
    assert result["scale"] == pytest.approx(2.0)
    assert result["offset"] == pytest.approx(1.0)
    assert result["sum"] == 18


def test_unshared_regression_input_arity_routes_columns_to_each_child():
    translator = Translator([], {}, {})
    reducer = invoke_composed_reducer(
        translator, "Reducer.combine",
        {"reducer1": TableReducer("linearFit", 1, 1),
         "reducer2": Reducer("sum"), "sharedInputs": False},
    )
    result = reduce_records(translator, [[0, 1, 5], [1, 3, 7]], reducer)
    assert result["scale"] == pytest.approx(2.0)
    assert result["offset"] == pytest.approx(1.0)
    assert result["sum"] == 12


def test_nested_grouping_uses_each_childs_output_and_preserves_first_seen_order():
    translator = Translator([], {}, {})
    mean = as_reducer_spec(translator, Reducer("mean"))
    inner = invoke_composed_reducer(
        translator, "Reducer.group",
        {"reducer": mean, "groupField": 1, "groupName": "zone"},
    )
    outer = invoke_composed_reducer(
        translator, "Reducer.group",
        {"reducer": inner, "groupField": 0, "groupName": "year"},
    )
    # Outer input layout is [year, value, zone]. The inner grouping receives
    # [value, zone] after the outer year field is removed.
    result = reduce_records(
        translator,
        [[2020, 10, "a"], [2020, 12, "a"], [2020, 20, "b"], [2021, 30, "a"]],
        outer,
    )
    assert result == {"groups": [
        {"year": 2020, "groups": [
            {"zone": "a", "mean": 11}, {"zone": "b", "mean": 20},
        ]},
        {"year": 2021, "groups": [{"zone": "a", "mean": 30}]},
    ]}


def test_set_outputs_can_resolve_duplicate_child_names_before_dictionary_boundary():
    translator = Translator([], {}, {})
    child = invoke_composed_reducer(
        translator, "Reducer.combine",
        {"reducer1": Reducer("mean"), "reducer2": Reducer("mean"),
         "sharedInputs": True},
    )
    renamed = invoke_composed_reducer(
        translator, "Reducer.setOutputs",
        {"reducer": child, "outputs": ["left", "right"]},
    )
    assert reduce_records(translator, [[2], [4]], renamed) == {"left": 3, "right": 3}
    with pytest.raises(UnsupportedEEError, match="collide"):
        reduce_records(translator, [[2], [4]], child)
    group_collision = invoke_composed_reducer(
        translator, "Reducer.group",
        {"reducer": child, "groupField": 0},
    )
    with pytest.raises(UnsupportedEEError, match="collide"):
        reduce_records(translator, [], group_collision)


def test_group_name_collision_and_boolean_numeric_key_types_are_explicit():
    translator = Translator([], {}, {})
    child = invoke_composed_reducer(
        translator, "Reducer.setOutputs",
        {"reducer": Reducer("mean"), "outputs": ["zone"]},
    )
    group = invoke_composed_reducer(
        translator, "Reducer.group",
        {"reducer": child, "groupField": 1, "groupName": "zone"},
    )
    with pytest.raises(UnsupportedEEError, match="collides"):
        reduce_records(translator, [[1, "a"]], group)

    scalar = invoke_composed_reducer(
        translator, "Reducer.group",
        {"reducer": Reducer("count"), "groupField": 1, "groupName": "key"},
    )
    result = reduce_records(translator, [[7, True], [7, 1], [8, 1.0]], scalar)
    assert result == {"groups": [
        {"key": True, "count": 1}, {"key": 1, "count": 2},
    ]}


def test_null_group_keys_are_skipped_and_invalid_keys_fail_even_on_empty_tables():
    translator = Translator([], {}, {})
    group = invoke_composed_reducer(
        translator, "Reducer.group",
        {"reducer": Reducer("count"), "groupField": 1},
    )
    assert reduce_records(translator, [[1, None], [2, "a"]], group) == {
        "groups": [{"group": "a", "count": 1}],
    }
    bad = invoke_composed_reducer(
        translator, "Reducer.group",
        {"reducer": Reducer("count"), "groupField": 1},
    )
    with pytest.raises(UnsupportedEEError, match="group keys"):
        reduce_records(translator, [[None, []]], bad)


def test_reduce_columns_accepts_empty_weights_but_rejects_nonempty_weights():
    translator = Translator([], {}, {})
    reducer = Reducer("mean")
    arguments = {
        "collection": feature_collection([{"value": 2}, {"value": 4}]),
        "selectors": ["value"],
        "reducer": reducer,
    }
    assert reduce_columns(translator, {**arguments, "weightSelectors": []}, reducer) == {
        "mean": 3,
    }
    with pytest.raises(UnsupportedEEError, match="Non-empty weightSelectors"):
        reduce_columns(translator, {**arguments, "weightSelectors": ["weight"]}, reducer)


def test_scalar_null_empty_count_and_non_numeric_policies_match_existing_kernels():
    translator = Translator([], {}, {})
    assert reduce_list(translator, [None, 1, 3], Reducer("mean")) == 2
    assert reduce_list(translator, [None, "x", {}, []], Reducer("count")) == 3
    assert reduce_list(translator, [None], Reducer("sum")) == 0
    assert reduce_list(translator, [], Reducer("mean")) is None
    with pytest.raises(UnsupportedEEError, match="finite numbers"):
        reduce_list(translator, [1, "bad"], Reducer("sum"))


def test_first_and_last_results_are_detached_and_reject_cycles_and_oversize():
    source = {"nested": [1, {"x": "keep"}]}
    translator = Translator([], {}, {})
    first = reduce_list(translator, [source, {"later": True}], Reducer("first"))
    first["nested"][1]["x"] = "changed"
    assert source["nested"][1]["x"] == "keep"

    cycle = []
    cycle.append(cycle)
    with pytest.raises(UnsupportedEEError, match="cycles"):
        reduce_list(translator, [cycle], Reducer("last"))
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reduce_list(translator, ["x" * 1_000_001], Reducer("first"))


def test_nested_static_arrays_are_detached_and_remain_read_only():
    source_data = np.asarray([1.0, 2.0])
    source_data.flags.writeable = False
    source = {"array": StaticArray(source_data)}
    result = reduce_list(Translator([], {}, {}), [source], Reducer("first"))
    copied = result["array"].data
    assert not np.shares_memory(source_data, copied)
    assert not copied.flags.writeable
    with pytest.raises(ValueError):
        copied[0] = 7
    assert source_data.tolist() == [1.0, 2.0]


def test_reducer_snapshot_is_detached_and_mutated_descriptors_fail_closed():
    original = Reducer("mean")
    spec = as_reducer_spec(Translator([], {}, {}), original)
    assert is_reducer_spec(spec)
    object.__setattr__(original, "name", "sum")
    assert reduce_list(Translator([], {}, {}), [1, 3], spec) == 2

    object.__setattr__(spec, "input_count", 33)
    with pytest.raises(UnsupportedEEError, match="input or output arity"):
        reduce_list(Translator([], {}, {}), [1, 3], spec)


def test_descriptor_cycle_and_node_depth_output_budgets_are_bounded():
    translator = Translator([], {}, {})
    spec = as_reducer_spec(translator, Reducer("mean"))
    cyclic = ReducerSpec("setOutputs", 1, ("mean",), child=spec,
                         output_selection=("mean",))
    object.__setattr__(cyclic, "child", cyclic)
    with pytest.raises(UnsupportedEEError, match="cycles"):
        as_reducer_spec(Translator([], {}, {}), cyclic)

    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_composed_reducer(
            translator, "Reducer.getOutputs", {"reducer": spec},
        )

    depth_translator = Translator([], {}, {})
    nested = as_reducer_spec(depth_translator, Reducer("mean"))
    for _ in range(15):
        nested = invoke_composed_reducer(
            depth_translator, "Reducer.setOutputs",
            {"reducer": nested, "outputs": ["mean"]},
        )
    with pytest.raises(UnsupportedEEError, match="depth 16"):
        invoke_composed_reducer(
            depth_translator, "Reducer.setOutputs",
            {"reducer": nested, "outputs": ["mean"]},
        )

    def balanced(depth):
        if depth == 0:
            return as_reducer_spec(Translator([], {}, {}), Reducer("mean"))
        left, right = balanced(depth - 1), balanced(depth - 1)
        return ReducerSpec(
            "combine", 1, left.outputs + right.outputs,
            left=left, right=right, shared_inputs=True,
        )

    too_many_nodes = balanced(6)
    with pytest.raises(UnsupportedEEError, match="64 descriptor nodes"):
        as_reducer_spec(Translator([], {}, {}), too_many_nodes)


def test_table_scan_preflights_json_and_feature_limits():
    reducer = Reducer("count")
    arguments = {
        "collection": feature_collection([{"value": "x" * 10_001}]),
        "selectors": ["value"], "reducer": reducer,
    }
    with pytest.raises(UnsupportedEEError, match="bounded string length"):
        reduce_columns(Translator([], {}, {}), arguments, reducer)

    too_many = feature_collection([{"value": index} for index in range(1001)])
    with pytest.raises(UnsupportedEEError, match="1000 inline features"):
        reduce_columns(Translator([], {}, {}), {
            **arguments, "collection": too_many,
        }, reducer)


def test_reducer_table_input_types_nulls_and_selectors_fail_explicitly():
    reducer = Reducer("sum")
    base = {
        "collection": feature_collection([{"value": 1}, {"value": None}]),
        "selectors": ["value"], "reducer": reducer,
    }
    assert reduce_columns(Translator([], {}, {}), base, reducer) == {"sum": 1}
    for bad in (True, "2", float("inf"), 2**53 + 1):
        with pytest.raises(UnsupportedEEError):
            reduce_columns(Translator([], {}, {}), {
                **base, "collection": feature_collection([{"value": bad}]),
            }, reducer)
    with pytest.raises(UnsupportedEEError, match="exactly 1 selectors"):
        reduce_columns(Translator([], {}, {}), {**base, "selectors": []}, reducer)


def test_bad_constructor_arguments_and_unsupported_contexts_fail_explicitly():
    translator = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError, match="equal input counts"):
        invoke_composed_reducer(
            translator, "Reducer.combine",
            {"reducer1": TableReducer("linearFit", 1, 1),
             "reducer2": Reducer("mean"), "sharedInputs": True},
        )
    with pytest.raises(UnsupportedEEError, match="must be boolean"):
        invoke_composed_reducer(
            translator, "Reducer.combine",
            {"reducer1": Reducer("mean"), "reducer2": Reducer("sum"),
             "sharedInputs": "false"},
        )
    with pytest.raises(UnsupportedEEError, match="Unweighted reducer inputs"):
        as_reducer_spec(translator, Reducer("mean", unweighted=True))


def test_compose_descriptor_output_can_be_copied_without_aliasing():
    translator = Translator([], {}, {})
    spec = invoke_composed_reducer(
        translator, "Reducer.combine",
        {"reducer1": Reducer("mean"), "reducer2": Reducer("sum"),
         "sharedInputs": True},
    )
    names = invoke_composed_reducer(translator, "Reducer.getOutputs", {"reducer": spec})
    detached = deepcopy(names)
    detached[0] = "changed"
    assert names == ["mean", "sum"]
