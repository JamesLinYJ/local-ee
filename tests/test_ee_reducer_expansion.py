"""Bounded Reducer.repeat/forEach syntax and finite table/list evaluation."""
from copy import deepcopy
from pathlib import Path

import pytest

from gee.compat.earthengine.composed_reducers import (
    as_reducer_spec,
    invoke_composed_reducer,
)
from gee.compat.earthengine.composed_reducer_values import reduce_list
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Reducer, UnsupportedEEError
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


def test_sdk_repeat_on_list_and_reduce_columns_keeps_independent_input_blocks(ee):
    rows = [[1, 10], [3, 30]]
    values = ee.List(rows)
    single = ee.Reducer.mean().repeat(2)
    multiple = ee.Reducer.mean().combine(
        ee.Reducer.sum(), sharedInputs=True,
    ).repeat(2)

    assert output(ee, values.reduce(single)) == [2, 20]
    assert output(ee, values.reduce(multiple)) == {
        "mean": [2, 20], "sum": [4, 40],
    }

    table = ee.FeatureCollection([
        ee.Feature(None, {"x": x, "y": y}) for x, y in rows
    ])
    assert output(ee, table.reduceColumns(single, ["x", "y"])) == {
        "mean": [2, 20],
    }


def test_sdk_for_each_single_output_names_are_used_as_is(ee):
    values = ee.List([[1, 10], [3, 30]])
    reducer = ee.Reducer.sum().forEach(["left", "right"])
    assert output(ee, values.reduce(reducer)) == {"left": 4, "right": 40}


def test_sdk_for_each_multi_output_prefixes_names_with_underscore(ee):
    rows = [
        {"x1": 0, "y1": 1, "x2": 0, "y2": 10},
        {"x1": 1, "y1": 3, "x2": 1, "y2": 13},
    ]
    table = ee.FeatureCollection([ee.Feature(None, row) for row in rows])
    reducer = ee.Reducer.linearFit().forEach(["first", "second"])
    result = output(
        ee, table.reduceColumns(reducer, ["x1", "y1", "x2", "y2"]),
    )
    assert result == {
        "first_scale": pytest.approx(2),
        "first_offset": pytest.approx(1),
        "second_scale": pytest.approx(3),
        "second_offset": pytest.approx(10),
    }


def test_sdk_combine_set_outputs_and_nested_group_can_wrap_expansions(ee):
    rows = [
        {"x": 1, "y": 10, "zone": "a"},
        {"x": 3, "y": 30, "zone": "a"},
        {"x": 5, "y": 50, "zone": "b"},
    ]
    table = ee.FeatureCollection([ee.Feature(None, row) for row in rows])
    reducer = (
        ee.Reducer.mean().forEach(["x", "y"])
        .combine(ee.Reducer.sum().repeat(2), sharedInputs=True)
        .setOutputs(["mean_x", "mean_y", "totals"])
        .group(groupField=2, groupName="zone")
    )
    assert output(
        ee, table.reduceColumns(reducer, ["x", "y", "zone"]),
    ) == {
        "groups": [
            {"zone": "a", "mean_x": 2, "mean_y": 20, "totals": [4, 40]},
            {"zone": "b", "mean_x": 5, "mean_y": 50, "totals": [5, 50]},
        ],
    }


def test_nested_repeat_returns_one_nested_list_per_copy(ee):
    reducer = ee.Reducer.sum().repeat(2).repeat(2)
    assert output(ee, ee.List([[1, 10, 100, 1000]]).reduce(reducer)) == [
        [1, 10], [100, 1000],
    ]


def test_expansion_preserves_valid_zero_output_reducers_with_real_input_arity(ee):
    table = ee.FeatureCollection([
        ee.Feature(None, {"x": 1, "y": 10}),
        ee.Feature(None, {"x": 3, "y": 30}),
    ])
    no_outputs = ee.Reducer.mean().setOutputs([""])
    repeated = no_outputs.repeat(2)
    per_name = no_outputs.forEach(["left", "right"])
    assert output(ee, table.reduceColumns(repeated, ["x", "y"])) == {}
    assert output(ee, table.reduceColumns(per_name, ["x", "y"])) == {}


def test_expansion_names_and_values_are_owned():
    source_left = {"items": [1]}
    source_right = {"items": [2]}
    translator = Translator([], {}, {})
    child = as_reducer_spec(translator, Reducer("first"))
    repeated = invoke_composed_reducer(
        translator, "Reducer.repeat", {"reducer": child, "count": 2},
    )
    result = reduce_list(translator, [[source_left, source_right]], repeated)
    assert result == [source_left, source_right]
    assert result[0] is not source_left and result[1] is not source_right
    assert result[0] is not result[1]
    result[0]["items"].append(9)
    assert source_left["items"] == [1]

    names = invoke_composed_reducer(
        translator, "Reducer.getOutputs", {"reducer": repeated},
    )
    copied = deepcopy(names)
    copied[0] = "changed"
    assert names == ["first"]


def test_zero_copy_and_unbounded_expansions_are_rejected_without_phantom_arity(ee):
    with pytest.raises(UnsupportedEEError, match="zero-copy"):
        output(ee, ee.Reducer.sum().repeat(0))
    with pytest.raises(UnsupportedEEError, match="zero-copy"):
        output(ee, ee.Reducer.sum().forEach([]))
    with pytest.raises(UnsupportedEEError, match="32-input"):
        output(ee, ee.Reducer.sum().repeat(1_000_000_000))
    with pytest.raises(UnsupportedEEError, match="32-input"):
        output(ee, ee.Reducer.sum().forEach([f"n{i}" for i in range(33)]))


def test_output_collisions_and_group_collisions_fail_even_for_empty_rows(ee):
    table = ee.FeatureCollection([])
    duplicate = ee.Reducer.sum().forEach(["same", "same"])
    with pytest.raises(UnsupportedEEError, match="collide"):
        output(ee, table.reduceColumns(duplicate, ["x", "y"]))

    duplicate_multi = ee.Reducer.linearFit().forEach(["same", "same"])
    with pytest.raises(UnsupportedEEError, match="collide"):
        output(
            ee, table.reduceColumns(duplicate_multi, ["x1", "y1", "x2", "y2"]),
        )

    group = ee.Reducer.sum().forEach(["group"]).group(
        groupField=1, groupName="group",
    )
    with pytest.raises(UnsupportedEEError, match="collides"):
        output(ee, table.reduceColumns(group, ["value", "zone"]))


def test_expansion_node_budget_counts_logical_copies_before_evaluation():
    translator = Translator([], {}, {})
    leaves = [as_reducer_spec(translator, Reducer("mean")) for _ in range(32)]
    while len(leaves) > 1:
        combined = []
        for index in range(0, len(leaves), 2):
            combined.append(invoke_composed_reducer(
                translator, "Reducer.combine",
                {"reducer1": leaves[index], "reducer2": leaves[index + 1],
                 "sharedInputs": True},
            ))
        leaves = combined
    with pytest.raises(UnsupportedEEError, match="64 logical descriptor nodes"):
        invoke_composed_reducer(
            Translator([], {}, {}), "Reducer.forEach",
            {"reducer": leaves[0], "outputNames": ["a", "b"]},
        )


def test_expanded_row_work_is_precharged_before_child_reduction():
    translator = Translator([], {}, {})
    child = as_reducer_spec(translator, Reducer("sum"))
    repeated = invoke_composed_reducer(
        translator, "Reducer.repeat", {"reducer": child, "count": 32},
    )
    rows = [[index] * 32 for index in range(510)]
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        reduce_list(translator, rows, repeated)


@pytest.mark.parametrize("payload", [[], [None], [1]])
def test_for_each_rejects_malformed_output_name_lists(ee, payload):
    with pytest.raises(UnsupportedEEError, match="Reducer.forEach"):
        output(ee, ee.Reducer.sum().forEach(payload))

    with pytest.raises(UnsupportedEEError, match="outputNames must be a list"):
        invoke_composed_reducer(
            Translator([], {}, {}),
            "Reducer.forEach",
            {"reducer": Reducer("sum"), "outputNames": "names"},
        )


def test_malformed_unused_expansion_fields_fail_closed():
    translator = Translator([], {}, {})
    leaf = as_reducer_spec(translator, Reducer("sum"))
    object.__setattr__(leaf, "repeat_count", 1)
    with pytest.raises(UnsupportedEEError, match="invalid descriptor fields"):
        as_reducer_spec(Translator([], {}, {}), leaf)

    clean = as_reducer_spec(Translator([], {}, {}), Reducer("sum"))
    repeated = invoke_composed_reducer(
        Translator([], {}, {}), "Reducer.repeat", {"reducer": clean, "count": 2},
    )
    object.__setattr__(repeated, "for_each_names", ("unused",))
    with pytest.raises(UnsupportedEEError, match="invalid copy count"):
        as_reducer_spec(Translator([], {}, {}), repeated)


def test_composed_expansions_are_still_rejected_by_raster_consumers(ee):
    with pytest.raises(UnsupportedEEError, match="exactly one input"):
        output(ee, ee.Image.constant(1).reduce(ee.Reducer.sum().repeat(2)))
