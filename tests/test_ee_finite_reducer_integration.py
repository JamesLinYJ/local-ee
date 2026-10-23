"""Cross-family arity, type, scope and scale contracts through the pinned SDK."""
from dataclasses import replace
from pathlib import Path

import pytest

from gee.compat.earthengine.composed_reducer_spec import validate_reducer_spec
from gee.compat.earthengine.composed_reducer_values import reduce_list
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.finite_reducer_leaves import (
    FiniteReducerLeaf, finite_leaf_outputs, invoke_finite_reducer,
)
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    with OfflineGuard() as guard:
        yield configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                 signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
    assert guard.evidence()["attempt_count"] == 0


def output(ee, expression):
    return compile_expression(ee.serializer.encode(expression, for_cloud_api=False), [], {})["value"]


def test_count_every_has_zero_selected_columns_and_retains_every_source_row(ee):
    rows = ee.FeatureCollection([ee.Feature(None, {}), ee.Feature(None, {"x": None})])
    assert output(ee, rows.reduceColumns(ee.Reducer.countEvery(), [])) == {"count": 2}
    assert output(ee, ee.FeatureCollection([]).reduceColumns(ee.Reducer.countEvery(), [])) == {"count": 0}
    assert output(ee, ee.List([None, 0, False, {}, [1, 2]]).reduce(ee.Reducer.countEvery())) == 5
    with pytest.raises(UnsupportedEEError, match="exactly 0 selectors"):
        output(ee, rows.reduceColumns(ee.Reducer.countEvery(), ["x"]))


def test_zero_input_children_survive_repeat_for_each_and_group(ee):
    rows = ee.FeatureCollection([ee.Feature(None, {"zone": "a"}), ee.Feature(None, {"zone": "a"})])
    assert output(ee, rows.reduceColumns(ee.Reducer.countEvery().repeat(3), [])) == {"count": [2, 2, 2]}
    assert output(ee, rows.reduceColumns(ee.Reducer.countEvery().forEach(["a", "b"]), [])) == {"a": 2, "b": 2}
    assert output(ee, rows.reduceColumns(ee.Reducer.countEvery().group(0, "zone"), ["zone"])) == {
        "groups": [{"zone": "a", "count": 2}],
    }
    assert output(ee, ee.List([1, 2]).reduce(ee.Reducer.countEvery().repeat(2))) == [2, 2]
    with pytest.raises(UnsupportedEEError, match="equal input counts"):
        output(ee, ee.Reducer.mean().combine(ee.Reducer.countEvery(), sharedInputs=True))


def test_count_every_still_rejects_opaque_or_unbounded_list_values():
    translator = Translator([], {}, {})
    reducer = invoke_finite_reducer(translator, "Reducer.countEvery", {})
    from gee.compat.earthengine.ir import Reducer

    for values in ([Reducer("sum")], [float("inf")], [1] * 1001):
        with pytest.raises(UnsupportedEEError):
            reduce_list(Translator([], {}, {}), values, reducer)
    cycle = []
    cycle.append(cycle)
    with pytest.raises(UnsupportedEEError, match="cycle"):
        reduce_list(Translator([], {}, {}), cycle, reducer)


def test_finite_descriptors_reject_public_escape_and_unsupported_consumers(ee):
    numeric = {"product", "stdDev", "variance", "sampleVariance", "minMax"}
    for name in finite_leaf_outputs():
        reducer = ee.call("Reducer." + name)
        expressions = [
            reducer, ee.Algorithms.If(reducer, 1, 0),
            ee.Image.constant(1).reduce(reducer),
            ee.ImageCollection([]).reduce(reducer),
        ]
        if name not in numeric:
            expressions.append(ee.Array([1, 2]).reduce(reducer, [0]))
        for expression in expressions:
            with pytest.raises(UnsupportedEEError):
                output(ee, expression)


def test_numeric_finite_descriptors_enter_only_audited_array_paths(ee):
    expected = {"product": 2, "stdDev": 0.5, "variance": 0.25, "sampleVariance": 0.5}
    for name, value in expected.items():
        assert output(ee, ee.Array([1, 2]).reduce(ee.call("Reducer." + name), [0])) == pytest.approx([value], rel=1e-15)
    assert output(ee, ee.Array([[1], [2]]).reduce(ee.Reducer.minMax(), [0], 1)) == [[1, 2]]


def test_leaf_descriptors_validate_name_arity_outputs_and_unused_fields():
    spec = invoke_finite_reducer(Translator([], {}, {}), "Reducer.minMax", {})
    for broken in (
        replace(spec, input_count=0), replace(spec, outputs=("max", "min")),
        replace(spec, leaf=FiniteReducerLeaf("invented")),
        replace(spec, leaf=FiniteReducerLeaf([])), replace(spec, repeat_count=1),
    ):
        with pytest.raises(UnsupportedEEError):
            validate_reducer_spec(broken, Translator([], {}, {}))
    with pytest.raises(UnsupportedEEError):
        invoke_finite_reducer(Translator([], {}, {}), "Reducer.product", {"weights": [1]})


def test_thousand_row_table_variance_and_count_remain_within_existing_budget(ee):
    rows = ee.FeatureCollection([ee.Feature(None, {"x": index}) for index in range(1000)])
    assert output(ee, rows.reduceColumns(ee.Reducer.variance(), ["x"])) == {
        "variance": pytest.approx((1000**2 - 1) / 12, rel=2e-15),
    }
    assert output(ee, rows.reduceColumns(ee.Reducer.countEvery(), [])) == {"count": 1000}


def test_thousand_repeated_histogram_rows_fit_but_full_unique_path_keeps_budget(ee):
    rows = ee.FeatureCollection([ee.Feature(None, {"x": 1}) for _ in range(1000)])
    assert output(ee, rows.reduceColumns(ee.Reducer.frequencyHistogram(), ["x"])) == {
        "histogram": {"1": 1000},
    }
    assert output(ee, rows.aggregate_histogram("x")) == {"1": 1000}
    distinct = ee.FeatureCollection([ee.Feature(None, {"x": value}) for value in range(1000)])
    for expression in (distinct.aggregate_histogram("x"),
                       distinct.reduceColumns(ee.Reducer.frequencyHistogram(), ["x"])):
        with pytest.raises(UnsupportedEEError, match="50000-step"):
            output(ee, expression)


def test_empty_table_cannot_hide_unsupported_weights_or_type_mismatches(ee):
    rows = ee.FeatureCollection([])
    with pytest.raises(UnsupportedEEError, match="weightSelectors"):
        output(ee, rows.reduceColumns(ee.Reducer.variance(), ["x"], ["w"]))
    with pytest.raises(UnsupportedEEError, match="exactly 1 selectors"):
        output(ee, rows.reduceColumns(ee.Reducer.variance(), []))
