"""Cross-family typed-tree, scope, scale and selected-value contracts."""
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.array_values import StaticArray
from gee.compat.earthengine.composed_reducer_spec import validate_reducer_spec
from gee.compat.earthengine.composed_reducer_tables import reduce_columns
from gee.compat.earthengine.composed_reducer_values import reduce_list
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.statistical_reducer_leaves import invoke_statistical_reducer
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
CONSTRUCTORS = [
    ("pearsonsCorrelation", {}), ("spearmansCorrelation", {}),
    ("kendallsCorrelation", {}), ("sensSlope", {}),
    ("covariance", {}), ("centeredCovariance", {}),
    ("fixedHistogram", {"min": 0, "max": 4, "steps": 2}),
    ("fixed2DHistogram", {"xMin": 0, "xMax": 4, "xSteps": 2,
                          "yMin": 0, "yMax": 4, "ySteps": 2}),
    ("toList", {}), ("toCollection", {"propertyNames": ["x"]}),
]


@pytest.fixture
def ee():
    with OfflineGuard() as guard:
        yield configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                 signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
    assert guard.evidence()["attempt_count"] == 0


def output(ee, value):
    return compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})["value"]


@pytest.mark.parametrize("name,args", CONSTRUCTORS)
def test_statistical_leaves_reject_root_control_flow_and_raster_consumers(ee, name, args):
    reducer = ee.call("Reducer." + name, **args)
    for value in (reducer, ee.Algorithms.If(reducer, 1, 0),
                  ee.Image.constant(1).reduce(reducer), ee.Array([]).reduce(reducer, [0]),
                  ee.ImageCollection([]).reduce(reducer)):
        with pytest.raises(UnsupportedEEError):
            output(ee, value)


@pytest.mark.parametrize("name,args", CONSTRUCTORS)
def test_descriptors_are_closed_validated_even_for_empty_tables(name, args):
    spec = invoke_statistical_reducer(Translator([], {}, {}), "Reducer." + name, args)
    assert validate_reducer_spec(spec) == 1
    for malformed in (replace(spec, input_count=32), replace(spec, outputs=("invented",)),
                      replace(spec, leaf=replace(spec.leaf, name="unknown")),
                      replace(spec, repeat_count=1)):
        with pytest.raises(UnsupportedEEError):
            reduce_list(Translator([], {}, {}), [], malformed)
    translator = Translator([], {}, {})
    translator.steps = 50_000
    with pytest.raises(UnsupportedEEError, match="50000"):
        validate_reducer_spec(spec, translator)


def test_covariance_selected_arrays_are_typed_detached_and_reject_invalid_arrays():
    spec = invoke_statistical_reducer(Translator([], {}, {}), "Reducer.covariance", {})
    first, second = StaticArray(np.array([1., 2.])), StaticArray(np.array([3., 4.]))

    def collection(values):
        return {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"v": value}} for value in values]}

    result = reduce_columns(Translator([], {}, {}),
                            {"collection": collection([first, second]), "selectors": ["v"]}, spec)
    np.testing.assert_array_equal(result["array"].data, [[2, 2], [2, 2]])
    assert not result["array"].data.flags.writeable
    first.data[0] = -999
    np.testing.assert_array_equal(result["array"].data, [[2, 2], [2, 2]])
    for invalid in ([1, 2], StaticArray(np.array([1, np.inf])),
                    StaticArray(np.array([2**53 + 1], dtype=np.int64)), spec):
        with pytest.raises(UnsupportedEEError):
            reduce_columns(Translator([], {}, {}),
                           {"collection": collection([None, invalid]), "selectors": ["v"]}, spec)


def test_collectors_preserve_tuple_shape_optional_nulls_and_grouping(ee):
    rows = ee.List([[1, None], [2, 4], [None, 8]])
    assert output(ee, rows.reduce(ee.Reducer.toList(2, 1))) == [[1, None], [2, 4]]
    assert output(ee, ee.List([1, 2]).reduce(ee.Reducer.toList(1))) == [[1], [2]]
    assert output(ee, ee.List([1, None, 2]).reduce(ee.Reducer.toList())) == [1, 2]
    grouped = ee.List([[1, 0], [2, 0], [3, 1]]).reduce(ee.Reducer.toList().group(1, "zone"))
    assert output(ee, grouped) == [{"zone": 0, "list": [1, 2]}, {"zone": 1, "list": [3]}]
    repeated = ee.List([[1, 10], [2, 20]]).reduce(ee.Reducer.toList().repeat(2))
    assert output(ee, repeated) == [[1, 2], [10, 20]]


def test_weight_selectors_stay_rejected_even_for_empty_statistical_tables(ee):
    with pytest.raises(UnsupportedEEError, match="weightSelectors"):
        output(ee, ee.FeatureCollection([]).reduceColumns(
            ee.Reducer.pearsonsCorrelation(), ["x", "y"], ["weight"]))


def test_correlations_do_not_skip_invalid_fields_in_incomplete_rows(ee):
    with pytest.raises(UnsupportedEEError, match="finite exact"):
        output(ee, ee.List([[1, 2], [None, "invalid"]]).reduce(ee.Reducer.pearsonsCorrelation()))


def test_quadratic_algorithms_precharge_and_keep_existing_budget(ee):
    values = ee.List.sequence(0, 999)
    with pytest.raises(UnsupportedEEError, match="50000"):
        output(ee, values.reduce(ee.Reducer.kendallsCorrelation()))
    pairs = values.map(lambda value: ee.List([value, value]))
    with pytest.raises(UnsupportedEEError, match="50000"):
        output(ee, pairs.reduce(ee.Reducer.sensSlope()))
