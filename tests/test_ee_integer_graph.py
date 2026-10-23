"""Exact Float64 comparisons and native Image integer graph behavior."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.integer_values_spec import constant_operand, prepare_integer_values_spec
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [4, 0], [4, 1], [0, 1], [0, 0]]],
}
COMPARISONS = ("eq", "neq", "lt", "lte", "gt", "gte")


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


@pytest.mark.parametrize("operation", COMPARISONS)
def test_all_float64_predicates_use_exact_native_double_comparison(ee, local, operation):
    source = ee.Image("scene-a").select("x").toDouble()
    value = getattr(source, operation)(2**52 + 1)
    expression = encode(ee, value)
    call = find_invocation(expression, "Image." + operation)
    assert call is not None and set(call["arguments"]) == {"image1", "image2"}

    result = compile_expression(expression, *local)
    integer = nodes(result, "local_ee_integer_values")
    assert len(integer) == 1
    assert json.loads(integer[0]["arguments"]["spec"]) == {
        "dtype": None, "op": operation,
        "operands": [{"band": 0}, constant_operand(2**52 + 1)], "v": 1,
    }
    assert len(nodes(result, "local_ee_to_double")) == 1
    assert result["source_item_ids"] == ["scene-a"]
    assert result["bands"] == ["x"]
    validate(result["process_graph"])


def test_high_integer_predicate_and_signed_zero_comparison_remain_exact(ee, local):
    image = ee.Image("scene-a").select("x").toDouble()
    high = compile_expression(encode(ee, image.gte(2**53)), *local)
    spec = json.loads(nodes(high, "local_ee_integer_values")[0]["arguments"]["spec"])
    assert spec["op"] == "gte"
    assert spec["operands"][1] == constant_operand(2**53)

    # Binary64 constants retain their sign in the wire, while equality obeys
    # IEEE numeric comparison where negative and positive zero are equal.
    neg_zero = compile_expression(
        encode(ee, image.eq(-0.0)), *local,
    )
    zero_spec = json.loads(
        nodes(neg_zero, "local_ee_integer_values")[0]["arguments"]["spec"],
    )
    assert zero_spec["op"] == "eq"
    assert zero_spec["operands"][1] == constant_operand(-0.0)

    # The predicate domain is finite binary64, not the bitwise exact-integer
    # domain; max finite and subnormal thresholds stay valid constants.
    for threshold in (float.fromhex("0x1.fffffffffffffp+1023"),
                      float.fromhex("0x0.0000000000001p-1022")):
        result = compile_expression(encode(ee, image.gte(threshold)), *local)
        spec = json.loads(
            nodes(result, "local_ee_integer_values")[0]["arguments"]["spec"],
        )
        assert spec["operands"][1] == constant_operand(threshold)


def test_bitwise_result_can_feed_an_exact_comparison_without_float32_callback(ee, local):
    image = ee.Image("scene-a").select("x").toDouble()
    value = image.bitwiseAnd(1024).eq(0)
    result = compile_expression(encode(ee, value), *local)
    integer_nodes = nodes(result, "local_ee_integer_values")
    assert len(integer_nodes) == 2
    specs = [json.loads(node["arguments"]["spec"]) for node in integer_nodes]
    assert {spec["op"] for spec in specs} == {"bit_and", "eq"}
    assert all(node["arguments"]["data"] for node in integer_nodes)
    assert not nodes(result, "reduce_dimension")
    validate(result["process_graph"])


def test_boolean_native_predicates_do_not_claim_float64_arithmetic(ee, local):
    value = ee.Image("scene-a").select("x").toDouble().gte(2**52)
    result = compile_expression(encode(ee, value), *local)
    compiler = Graph(Translator(*local, {}))
    pixel_image = compiler.t.evaluate(encode(ee, value))
    assert pixel_image.bands[0][1].boolean is True
    # The already-binary predicate result does not trigger the Float64
    # arithmetic rejection used for general numeric integer-valued outputs.
    assert compiler.has_double_precision(pixel_image.bands[0][1]) is False
    assert nodes(result, "local_ee_integer_values")


def test_exact_comparison_keeps_native_mask_and_mapped_time_metadata(ee, local):
    image = ee.Image("scene-a").select("x").toDouble()
    masked = image.gte(2**52).updateMask(ee.Image("scene-a").select("y").eq(1))
    result = compile_expression(encode(ee, masked), *local)
    integer = nodes(result, "local_ee_integer_values")
    assert len(integer) == 1
    conditionals = [
        step for node in nodes(result, "reduce_dimension")
        for step in node["arguments"].get("reducer", {}).get("process_graph", {}).values()
        if step.get("process_id") == "if"
    ]
    assert any(step["arguments"].get("reject") is None for step in conditionals)
    mapped = ee.ImageCollection("sentinel-2-l2a").map(
        lambda value: ee.Image(value).select("x").toDouble().gte(2**52),
    )
    mapped_result = compile_expression(encode(ee, mapped), *local)
    assert mapped_result["kind"] == "collection"
    assert mapped_result["has_time_dimension"] is True
    assert nodes(mapped_result, "local_ee_integer_values")


def test_float32_and_explicit_to_float_comparisons_keep_the_existing_callback(ee, local):
    image = ee.Image("scene-a").select("x")
    default = compile_expression(encode(ee, image.lte(1)), *local)
    explicit = compile_expression(encode(ee, image.toDouble().toFloat().lte(1)), *local)
    assert not nodes(default, "local_ee_integer_values")
    assert not nodes(explicit, "local_ee_integer_values")
    assert nodes(default, "reduce_dimension")
    assert nodes(explicit, "reduce_dimension")


def test_general_double_and_integer_value_arithmetic_still_requires_to_float(ee, local):
    image = ee.Image("scene-a").select("x")
    with pytest.raises(UnsupportedEEError, match="Float64 pixel arithmetic"):
        compile_expression(encode(ee, image.toDouble().add(1)), *local)
    with pytest.raises(UnsupportedEEError, match="Float64 pixel arithmetic"):
        compile_expression(encode(ee, image.toDouble().And(image.eq(1))), *local)
    with pytest.raises(UnsupportedEEError, match="Float64 pixel arithmetic"):
        compile_expression(encode(ee, image.toDouble().toInt16().add(1)), *local)

    explicit = image.toDouble().bitwiseAnd(1024).toFloat().add(1)
    result = compile_expression(encode(ee, explicit), *local)
    assert nodes(result, "local_ee_integer_values")
    assert nodes(result, "reduce_dimension")


def test_source_bound_constant_cast_uses_exact_predicate_and_masked_constant_rejects(
        ee, local):
    source = ee.Image("scene-a").select("x")
    constant_cast = ee.Image.constant(16777217).toInt32().rename("exact")
    bound = source.addBands(constant_cast).select("exact").gt(2**24)
    result = compile_expression(encode(ee, bound), *local)
    integer = nodes(result, "local_ee_integer_values")
    assert len(integer) == 1
    assert json.loads(integer[0]["arguments"]["spec"]) == {
        "dtype": None, "op": "gt",
        "operands": [{"band": 0}, constant_operand(2**24)], "v": 1,
    }
    assert nodes(result, "local_ee_constant_on_grid")

    unbound_masked = ee.Image.constant(16777217).toInt32().updateMask(
        source.gte(0),
    ).gt(2**24)
    with pytest.raises(UnsupportedEEError, match="Float64 validity masking requires a finite raster grid"):
        compile_expression(encode(ee, unbound_masked), *local)


def test_integer_graph_rejects_unproven_common_grid_before_merging(ee, local):
    value = ee.Image("scene-a").select("x").toDouble().bitwiseAnd(
        ee.Image("scene-b").select("x").toDouble(),
    )
    expression = encode(ee, value)
    translator = Translator(*local, {})
    image = translator.evaluate(expression)
    graph = Graph(translator)
    with pytest.raises(UnsupportedEEError, match="proven common pixel grid"):
        graph.image(image)
    assert not any(node["process_id"] == "merge_cubes" for node in graph.graph.values())


def test_integer_specs_retain_ordered_double_inputs_and_double_comparison_output():
    first = Source("catalog", ("scene",), ("x",))
    second = Source("other-catalog", ("scene",), ("y",))
    left = Pixel("band", (first, "x"))
    right = Pixel("band", (second, "y"))
    spec = prepare_integer_values_spec("bit_and", [{"band": 0}, {"band": 1}])
    pixel = Pixel("integer_values", ((left, right), spec))
    translator = Translator([{"id": "catalog"}], {"catalog": [{"id": "scene"}]}, {})
    graph = Graph(translator)
    with pytest.raises(UnsupportedEEError, match="distinct collection lineages"):
        graph.expression(pixel)
    assert not any(node["process_id"] == "merge_cubes" for node in graph.graph.values())
