"""Consumer, output ownership, descriptor and budget boundaries for wave41."""
from dataclasses import replace
from pathlib import Path

import pytest

from gee.compat.earthengine.composed_reducer_spec import validate_reducer_spec
from gee.compat.earthengine.composed_reducer_values import reduce_list
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.statistical_reducer_leaves import invoke_statistical_reducer
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
CONSTRUCTORS = [
    ("percentile", {"percentiles": [25, 75]}),
    ("intervalMean", {"minPercentile": 0, "maxPercentile": 100}),
    ("mode", {}), ("skew", {}), ("kurtosis", {}),
    ("circularMean", {}), ("circularStddev", {}), ("circularVariance", {}),
]


@pytest.fixture
def ee():
    with OfflineGuard() as guard:
        yield configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                 signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
    assert guard.evidence()["attempt_count"] == 0


def output(ee, value):
    return compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})["value"]


def test_all_eight_registered_names_have_closed_family_implementations():
    from gee.compat.earthengine.statistical_reducer_leaves import STATISTICAL_REDUCER_NAMES
    from scripts.ee_inventory.declarations import read_declared_handlers

    names = {"Reducer." + name for name, _ in CONSTRUCTORS}
    assert len(names) == 8
    assert names <= STATISTICAL_REDUCER_NAMES
    assert STATISTICAL_REDUCER_NAMES <= read_declared_handlers(ROOT / "gee/ee_translate.py")


@pytest.mark.parametrize("name,args", CONSTRUCTORS)
def test_new_reducers_reject_root_control_flow_arrays_and_raster_consumers(ee, name, args):
    reducer = ee.call("Reducer." + name, **args)
    for value in (reducer, ee.Algorithms.If(reducer, 1, 0),
                  ee.Image.constant(1).reduce(reducer), ee.Array([]).reduce(reducer, [0]),
                  ee.ImageCollection([]).reduce(reducer)):
        with pytest.raises(UnsupportedEEError):
            output(ee, value)


@pytest.mark.parametrize("name,args", CONSTRUCTORS)
def test_new_descriptors_revalidate_empty_inputs_and_shared_budget(name, args):
    spec = invoke_statistical_reducer(Translator([], {}, {}), "Reducer." + name, args)
    assert validate_reducer_spec(spec) == 1
    for bad in (replace(spec, input_count=2), replace(spec, outputs=("fake",)),
                replace(spec, leaf=replace(spec.leaf, name="unknown")),
                replace(spec, repeat_count=2)):
        with pytest.raises(UnsupportedEEError):
            reduce_list(Translator([], {}, {}), [], bad)
    translator = Translator([], {}, {})
    translator.steps = 50_000
    with pytest.raises(UnsupportedEEError, match="50000"):
        validate_reducer_spec(spec, translator)


@pytest.mark.parametrize("name,args", CONSTRUCTORS)
def test_new_reducers_cannot_silently_discard_table_weights(ee, name, args):
    reducer = ee.call("Reducer." + name, **args)
    collection = ee.FeatureCollection([ee.Feature(None, {"x": 1, "weight": 2})])
    with pytest.raises(UnsupportedEEError, match="weight"):
        output(ee, collection.reduceColumns(reducer, ["x"], ["weight"]))


def test_selected_percentile_outputs_are_detached_and_for_each_works(ee):
    reducer = ee.Reducer.percentile([0, 50, 100], ["low", "mid", "high"])
    result = output(ee, reducer.getOutputs())
    result[0] = "mutated"
    assert output(ee, reducer.getOutputs()) == ["low", "mid", "high"]
    selected = reducer.setOutputs([None, "middle", ""])
    assert output(ee, ee.List([1, 3, 5]).reduce(selected)) == 3
    columns = ee.List([[1, 10], [3, 30], [5, 50]])
    assert output(ee, columns.reduce(
        ee.Reducer.percentile([50], ["mid"]).forEach(["x", "y"]))) == {"x": 3, "y": 30}


@pytest.mark.parametrize("name,args", CONSTRUCTORS)
def test_new_families_keep_1000_row_boundary(ee, name, args):
    reducer = ee.call("Reducer." + name, **args)
    with pytest.raises(UnsupportedEEError, match="1000"):
        output(ee, ee.List([1] * 1001).reduce(reducer))
