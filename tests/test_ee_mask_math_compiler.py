"""Official API math keeps independent masks through audited consumers."""
from __future__ import annotations

import json
import struct

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.image_mask_math import binary_pixel, unary_pixel
from gee.compat.earthengine.ir import Pixel, const
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


@pytest.fixture
def context():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path="vendor/earthengine-js/algorithms.json",
        )
        metadata, items, _ = synthetic_inputs()
        yield ee, [metadata], items
    assert guard.evidence()["attempt_count"] == 0


def image(ee):
    return ee.Image("scene-a").select("red").toDouble().updateMask(0.25)


def compile_value(context, value):
    ee, catalog, items = context
    return compile_expression(
        ee.serializer.encode(value, for_cloud_api=False), catalog, items,
    )


def mask_operations(result):
    return [json.loads(node["arguments"]["spec"])["op"]
            for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_mask_weights"]


@pytest.mark.parametrize("method", [
    "abs", "sqrt", "log", "log10", "exp", "round", "floor", "ceil",
    "sin", "cos", "tan", "Not", "toFloat", "toDouble", "float", "double",
])
def test_unary_and_cast_mask_getters_and_default_samples(context, method):
    ee, _, _ = context
    value = getattr(image(ee), method)()
    weights = compile_value(context, value.mask())
    samples = compile_value(context, value.sample())
    assert weights["bands"] == ["red"]
    assert "result_value" in mask_operations(weights)
    assert samples["kind"] == "sample_table"
    assert "result_value" in mask_operations(samples)
    assert samples["source_item_ids"] == ["scene-a"]


@pytest.mark.parametrize("method", [
    "add", "subtract", "multiply", "divide", "pow", "mod", "min", "max",
    "eq", "neq", "gt", "gte", "lt", "lte", "And", "Or",
])
@pytest.mark.parametrize("constant_first", [False, True])
def test_scalar_binary_both_directions_keep_official_band_pairing(context, method, constant_first):
    ee, _, _ = context
    weighted = image(ee)
    left, right = (ee.Image.constant(2), weighted) if constant_first else (weighted, 2)
    value = getattr(left, method)(right)
    weights = compile_value(context, value.mask())
    samples = compile_value(context, value.sample(dropNulls=False))
    assert weights["bands"] == (["constant"] if constant_first else ["red"])
    assert "result_value" in mask_operations(weights)
    assert "result_value" in mask_operations(samples)


@pytest.mark.parametrize("method", [
    "asin", "acos", "atan", "sinh", "cosh", "tanh", "cbrt", "signum",
    "gamma", "digamma", "trigamma", "erf", "erfc", "erfInv", "erfcInv",
])
def test_special_unary_functions_keep_the_existing_float32_boundary(context, method):
    ee, _, _ = context
    weighted = image(ee).toFloat()
    result = compile_value(context, getattr(weighted, method)().mask())
    assert result["bands"] == ["red"]
    assert "result_value" in mask_operations(result)
    with pytest.raises(UnsupportedEEError, match="toFloat"):
        compile_value(context, getattr(image(ee), method)().mask())


def test_scalar_composition_and_expression_reach_the_existing_sampler(context):
    ee, _, _ = context
    weighted = image(ee)
    for value in (
        weighted.clamp(-1, 2).unitScale(-1, 2),
        weighted.expression("sqrt(abs(b(0) * 2 - 1))"),
        weighted.toFloat().atan2(ee.Image.constant(2)),
        weighted.add(ee.Image.constant(1).add(2)),
    ):
        result = compile_value(context, value.sample())
        assert result["kind"] == "sample_table"
        assert result["source_item_ids"] == ["scene-a"]


def test_unaudited_two_raster_and_conditional_consumers_stay_explicit(context):
    ee, _, _ = context
    weighted = image(ee)
    for value in (
        weighted.add(weighted),
        weighted.multiply(ee.Image("scene-a").select("nir")),
        weighted.where(ee.Image.constant(1), 2),
        weighted.unmask(0),
    ):
        with pytest.raises(UnsupportedEEError, match="mask-aware consumer"):
            compile_value(context, value.sample())


def test_work_is_precharged_and_original_operands_are_retained():
    raw, weight = const(1), const(0.25)
    carrier = Pixel("with_mask", (raw, weight))
    translator = Translator([], {}, {})
    translator.steps = 49_990
    for operation in (
        lambda: unary_pixel(translator, "sqrt", carrier),
        lambda: binary_pixel(translator, "multiply", carrier, const(2)),
    ):
        with pytest.raises(UnsupportedEEError, match="50000-step"):
            operation()
    assert translator.steps == 49_990
    assert carrier.args == (raw, weight)


@pytest.mark.parametrize("shared_size,tail_size,accepted", [
    (88, 20, False), (95, 10, False), (40, 10, True),
])
def test_shared_constant_subtrees_keep_their_full_depth_before_folding(
    context, shared_size, tail_size, accepted,
):
    ee, _, _ = context
    receiver = ee.Image.constant(0)
    shared = receiver.expression("+".join(["1"] * shared_size))
    scalar = receiver.expression("+".join(["s", *(["1"] * tail_size), "s"]), {"s": shared})
    output = image(ee).add(scalar).mask()
    if accepted:
        assert compile_value(context, output)["bands"] == ["red"]
    else:
        with pytest.raises(UnsupportedEEError, match="depth 96"):
            compile_value(context, output)


def test_mapped_math_mask_getters_keep_actual_same_day_observations(context):
    ee, _, items = context
    for index, item in enumerate(items["sentinel-2-l2a"]):
        item["properties"].update({
            "system:time_start": 1000 + index,
            "proj:code": "EPSG:4326",
            "proj:transform": [0.25, 0, 100, 0, -0.25, 31],
        })
    collection = ee.ImageCollection("sentinel-2-l2a").limit(2)
    weights = collection.map(
        lambda value: value.select("red").toDouble().updateMask(0.25).sqrt().mask(),
    )
    result = compile_value(context, weights.toBands())
    assert result["bands"] == ["scene-a_red", "scene-b_red"]
    loads = [node["arguments"]["_gee_item_ids"]
             for node in result["process_graph"].values()
             if node["process_id"] == "load_collection"]
    assert loads == [["scene-a"], ["scene-b"]]


@pytest.mark.parametrize("raw,rounded", [
    (2**52 + 1, 2**52 + 1), (-(2**52 + 1), -(2**52 + 1)),
    (2**53, 2**53), (-2**53, -2**53),
    (0.49999999999999994, 0), (0.5, 1), (-0.5, 0),
    (-0.5000000000000001, -1), (-0.0, -0.0),
])
def test_folded_round_keeps_exact_integers_ties_and_signed_zero(context, raw, rounded):
    ee, _, _ = context
    scalar = ee.Image.constant(raw).toDouble().round()
    result = compile_value(context, image(ee).subtract(scalar).mask())
    specs = [json.loads(node["arguments"]["spec"])
             for node in result["process_graph"].values()
             if node["process_id"] == "local_ee_integer_values"]
    operands = [operand["constant"] for spec in specs if spec["op"] == "subtract"
                for operand in spec["operands"] if "constant" in operand]
    assert operands == [struct.pack(">d", float(rounded)).hex()]

    # Cover the shared grid-binding fold and ordinary unbound constant path,
    # so the fix cannot live only in masked math's new caller.
    from gee.compat.earthengine.constant_bands import _evaluate
    from gee.compat.earthengine.graph import Graph
    pixel = Pixel("round", (const(raw),))
    assert struct.pack(">d", _evaluate(pixel)) == struct.pack(">d", float(rounded))
    folded, label, _ = Graph(Translator([], {}, {})).expression(pixel)
    assert label is None
    assert struct.pack(">d", folded) == struct.pack(">d", float(rounded))


@pytest.mark.parametrize("operation,raw,expected", [
    ("floor", -0.0, -0.0), ("ceil", -0.0, -0.0),
    ("floor", 0.0, 0.0), ("ceil", 0.0, 0.0),
    ("floor", -0.2, -1.0), ("ceil", -0.2, -0.0),
    ("floor", -5e-324, -1.0), ("ceil", -5e-324, -0.0),
])
def test_scalar_floor_ceil_keep_sign_through_both_atan2_paths(context, operation, raw, expected):
    from gee.float64_values_contract import evaluate_float64_values
    from gee.compat.earthengine.constant_bands import _evaluate

    ee, _, _ = context
    expected_bits = struct.pack(">d", expected)
    assert struct.pack(">d", _evaluate(Pixel(operation, (const(raw),)))) == expected_bits
    assert struct.pack(">d", evaluate_float64_values(operation, [raw])) == expected_bits
    scalar = getattr(ee.Image.constant(raw).toDouble(), operation)().toFloat()
    for weighted in (False, True):
        source = ee.Image("scene-a").select("red").toFloat()
        if weighted:
            source = source.updateMask(0.25)
        result = source.atan2(scalar)
        graph = compile_value(context, result.mask() if weighted else result)["process_graph"]
        node = next(node for node in graph.values()
                    if node["process_id"] == "local_ee_pixel_math")
        merged = graph[node["arguments"]["data"]["from_node"]]
        assert merged["process_id"] == "merge_cubes"
        ref = merged["arguments"]["cube2"]
        for _ in range(10):
            node = graph[ref["from_node"]]
            if node["process_id"] == "local_ee_constant_on_grid":
                assert struct.pack(">d", node["arguments"]["value"]) == expected_bits
                break
            ref = node["arguments"]["data"]
        else:
            pytest.fail("atan2 scalar has no bounded grid constant")
