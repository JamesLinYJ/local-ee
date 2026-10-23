"""Closed Float64 core-operation lowering and precision preservation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.image_integer import _float64_pixel
from gee.compat.earthengine.ir import Pixel, Source, UnsupportedEEError, const
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.float64_values_contract import FLOAT64_ARITIES
from gee.graph import validate
from gee.integer_values_spec import constant_operand
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [4, 0], [4, 1], [0, 1], [0, 0]]],
}
API_NAMES = {
    "power": "pow", "absolute": "abs", "min2": "min", "max2": "max",
    "and": "and", "or": "or",
    "not": "not",
}
PYTHON_METHODS = {"and": "And", "or": "Or", "not": "Not"}


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


@pytest.fixture
def local():
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {
        "bands": {"values": ["x", "y"]}}}]
    items = {"sentinel-2-l2a": [{
        "id": "scene-a", "bbox": [0, 0, 4, 1], "geometry": GEOMETRY,
        "properties": {"system:index": "scene-a", "system:time_start": 1000,
                       "proj:code": "EPSG:32649",
                       "proj:transform": [10, 0, 220000, 0, -10, 3420000]},
    }, {
        "id": "scene-b", "bbox": [0, 0, 4, 1], "geometry": GEOMETRY,
        "properties": {"system:index": "scene-b", "system:time_start": 2000,
                       "proj:code": "EPSG:32649",
                       "proj:transform": [20, 0, 220000, 0, -20, 3420000]},
    }]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def find_invocation(value, name):
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == name:
            return value
        for child in value.values():
            result = find_invocation(child, name)
            if result is not None:
                return result
    elif isinstance(value, (list, tuple)):
        for child in value:
            result = find_invocation(child, name)
            if result is not None:
                return result
    return None


def nodes(result, process_id):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == process_id]


def _sdk_expression(image, other, operation):
    method = PYTHON_METHODS.get(operation, API_NAMES.get(operation, operation))
    function = getattr(image, method)
    return function(other) if FLOAT64_ARITIES[operation] == 2 else function()


@pytest.mark.parametrize("operation", tuple(FLOAT64_ARITIES))
def test_core_float64_sdk_operations_use_ordered_native_wire(ee, local, operation):
    left = ee.Image("scene-a").select("x").toDouble()
    right = ee.Image("scene-a").select("y").toDouble()
    expression = _sdk_expression(left, right, operation)
    serialized = encode(ee, expression)
    api_name = API_NAMES.get(operation, operation)
    assert find_invocation(serialized, "Image." + api_name) is not None

    result = compile_expression(serialized, *local)
    native = nodes(result, "local_ee_integer_values")
    assert len(native) == 1
    spec = json.loads(native[0]["arguments"]["spec"])
    assert spec == {
        "dtype": None, "op": operation,
        "operands": [{"band": 0}, {"band": 1}]
        if FLOAT64_ARITIES[operation] == 2 else [{"band": 0}],
        "v": 1,
    }
    assert result["bands"] == ["x"]
    assert result["source_item_ids"] == ["scene-a"]
    assert len(result["process_graph"]) <= 500
    assert len(json.dumps(result, separators=(",", ":"))) <= 1_000_000
    validate(result["process_graph"])


def test_float32_and_explicit_to_float_keep_the_existing_callback(ee, local):
    image = ee.Image("scene-a").select("x")
    default = compile_expression(encode(ee, image.add(1)), *local)
    explicit = compile_expression(
        encode(ee, image.toDouble().toFloat().add(1)), *local,
    )
    assert not nodes(default, "local_ee_integer_values")
    assert not nodes(explicit, "local_ee_integer_values")
    assert nodes(default, "reduce_dimension")
    assert nodes(explicit, "reduce_dimension")


def test_double_arithmetic_intersects_masks_and_preserves_band_and_source_metadata(
        ee, local):
    x = ee.Image("scene-a").select("x").toDouble()
    y = ee.Image("scene-a").select("y").toDouble()
    expression = x.add(y).updateMask(y.gt(0))
    result = compile_expression(encode(ee, expression), *local)
    specs = [json.loads(node["arguments"]["spec"])
             for node in nodes(result, "local_ee_integer_values")]
    assert {spec["op"] for spec in specs} == {"add", "gt"}
    assert nodes(result, "mask")
    assert result["bands"] == ["x"]
    assert result["source_item_ids"] == ["scene-a"]
    validate(result["process_graph"])


def test_double_clamp_unitscale_normalized_difference_and_hypot_use_core_ir(
        ee, local):
    source = ee.Image("scene-a").select(["x", "y"]).toDouble()
    x = source.select("x")
    y = source.select("y")
    cases = (
        (x.clamp(-2, 2), {"min2", "max2"}),
        (x.unitScale(-2, 2), {"subtract", "divide"}),
        (source.normalizedDifference(["x", "y"]), {"lt", "add", "subtract", "divide"}),
        # Image.hypot deliberately narrows its final value to Float32.
        (x.hypot(y), {"absolute", "min2", "max2", "divide", "power", "add", "multiply", "sqrt"}),
    )
    for expression, expected in cases:
        result = compile_expression(encode(ee, expression), *local)
        operations = {
            json.loads(node["arguments"]["spec"])["op"]
            for node in nodes(result, "local_ee_integer_values")
        }
        assert expected <= operations
        if expression is cases[-1][0]:
            assert nodes(result, "local_ee_to_float")
        validate(result["process_graph"])


def test_double_arithmetic_rejects_unproven_grid_before_merge(ee, local):
    x = ee.Image("scene-a").select("x").toDouble()
    y = ee.Image("scene-b").select("x").toDouble()
    expression = encode(ee, x.add(y))
    translator = Translator(*local, {})
    image = translator.evaluate(expression)
    graph = Graph(translator)
    with pytest.raises(UnsupportedEEError, match="proven common pixel grid"):
        graph.image(image)
    assert not any(node["process_id"] == "merge_cubes"
                   for node in graph.graph.values())


def test_static_float64_round_domain_and_typed_boolean_folding():
    translator = Translator([], {}, {})
    input_pixel = Pixel("to_double", (const(2.5),))
    rounded = _float64_pixel(translator, "Image.round", "round", (input_pixel,))
    assert rounded == Pixel("to_double", (const(3.0),))
    graph = Graph(translator)
    assert graph.expression(Pixel("round", (input_pixel,))) == (3.0, None, True)
    assert not graph.graph

    invalid = _float64_pixel(
        translator, "Image.sqrt", "sqrt",
        (Pixel("to_double", (const(-1),)),),
    )
    assert invalid == Pixel("constant", (None,))

    logical = _float64_pixel(
        translator, "Image.and", "and", (const(True), const(False)),
    )
    assert logical == Pixel("constant", (False,), True)

    untyped_boolean = Pixel("constant", (True,), False)
    with pytest.raises(UnsupportedEEError, match="unsupported Float64 values"):
        _float64_pixel(translator, "Image.add", "add", (untyped_boolean, const(1)))


def test_exact_double_comparison_normalizes_only_typed_boolean_constants(ee, local):
    source = ee.Image("scene-a").select("x").toDouble()
    result = compile_expression(encode(ee, source.eq(ee.Image.constant(True))), *local)
    spec = json.loads(nodes(result, "local_ee_integer_values")[0]["arguments"]["spec"])
    assert spec["op"] == "eq"
    assert spec["operands"] == [{"band": 0}, constant_operand(1)]


def test_source_bound_static_double_constant_keeps_exact_predicate(ee, local):
    source = ee.Image("scene-a").select("x")
    exact = ee.Image.constant(16777217).toDouble().add(0).rename("exact")
    expression = source.addBands(exact).select("exact").gt(2**24)
    result = compile_expression(encode(ee, expression), *local)
    spec = json.loads(nodes(result, "local_ee_integer_values")[0]["arguments"]["spec"])
    assert spec == {
        "dtype": None, "op": "gt",
        "operands": [{"band": 0}, constant_operand(2**24)], "v": 1,
    }
    assert nodes(result, "local_ee_constant_on_grid")
    assert nodes(result, "local_ee_integer_values")


def test_source_bound_explicit_float_cast_rounds_before_outer_operation(ee, local):
    source = ee.Image("scene-a").select("x")
    rounded = (ee.Image.constant(16777217).toDouble().toFloat().round()
               .rename("rounded"))
    expression = source.addBands(rounded).select("rounded").gt(16777216)
    result = compile_expression(encode(ee, expression), *local)
    constant = nodes(result, "local_ee_constant_on_grid")
    assert len(constant) == 1
    assert constant[0]["arguments"]["value"] == 16777216
    # The explicit Float32 cast is a real boundary; the later predicate sees
    # its rounded value, which remains exactly representable on the Double grid.
    spec = json.loads(nodes(result, "local_ee_integer_values")[0]
                      ["arguments"]["spec"])
    assert spec["op"] == "gt"
    assert spec["operands"] == [{"band": 0}, constant_operand(16777216)]


def test_float64_work_budget_and_unimplemented_scientific_ops_remain_closed(
        local):
    source = Source("sentinel-2-l2a", ("scene-a",), ("x", "y"))
    raster = Pixel("to_double", (Pixel("band", (source, "x")),))
    translator = Translator(*local, {})
    translator.steps = 50_000
    graph = Graph(translator)
    with pytest.raises(UnsupportedEEError, match="50000-step compilation work budget"):
        graph.expression(Pixel("add", (raster, const(1))))
    assert not graph.graph

    scientific = Pixel("math_asin", (raster,))
    with pytest.raises(UnsupportedEEError, match="Float64 pixel arithmetic"):
        Graph(Translator(*local, {})).expression(scientific)
