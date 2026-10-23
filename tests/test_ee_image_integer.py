"""Pinned SDK Image integer-cast and bitwise invocation contracts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.image_integer import (
    IMAGE_INTEGER_FUNCTIONS,
    invoke_image_integer,
)
from gee.compat.earthengine.ir import Image, Pixel, Source, UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
CASTS = {
    "byte": "uint8", "toByte": "uint8", "uint8": "uint8", "toUint8": "uint8",
    "int8": "int8", "toInt8": "int8", "short": "int16", "toShort": "int16",
    "int16": "int16", "toInt16": "int16", "int": "int32", "toInt": "int32",
    "int32": "int32", "toInt32": "int32", "uint16": "uint16", "toUint16": "uint16",
    "uint32": "uint32", "toUint32": "uint32", "long": "int64", "toLong": "int64",
    "int64": "int64", "toInt64": "int64",
}
BITWISE = {
    "bitwiseAnd": ("bit_and", 2), "bitwise_and": ("bit_and", 2),
    "bitwiseOr": ("bit_or", 2), "bitwise_or": ("bit_or", 2),
    "bitwiseXor": ("bit_xor", 2), "bitwise_xor": ("bit_xor", 2),
    "bitwiseNot": ("bit_not", 1), "bitwise_not": ("bit_not", 1),
    "bitCount": ("bit_count", 1), "leftShift": ("left_shift", 2),
    "left_shift": ("left_shift", 2), "rightShift": ("right_shift", 2),
    "right_shift": ("right_shift", 2),
}
GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [4, 0], [4, 1], [0, 1], [0, 0]]],
}


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
        "bands": {"values": ["x", "y", "z"]}}}]
    items = {"sentinel-2-l2a": [{
        "id": "scene-a", "bbox": [0, 0, 4, 1], "geometry": GEOMETRY,
        "properties": {"system:index": "scene-a", "system:time_start": 1000},
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


@pytest.mark.parametrize("name,dtype", CASTS.items())
def test_each_pinned_cast_serializes_and_compiles_to_its_canonical_dtype(ee, local, name, dtype):
    image = ee.Image("scene-a").select("x").set("marker", "kept")
    expression = encode(ee, getattr(image, name)())
    call = find_invocation(expression, "Image." + name)
    assert call is not None and set(call["arguments"]) == {"value"}

    result = compile_expression(expression, *local)
    integer = nodes(result, "local_ee_integer_values")
    assert len(integer) == 1
    assert json.loads(integer[0]["arguments"]["spec"]) == {
        "dtype": dtype, "op": "cast", "operands": [{"band": 0}], "v": 1,
    }
    assert result["bands"] == ["x"]
    assert result["properties"]["marker"] == "kept"
    assert result["source_item_ids"] == ["scene-a"]
    assert len(nodes(result, "local_ee_to_double")) == 1
    validate(result["process_graph"])


@pytest.mark.parametrize("name,wire", BITWISE.items())
def test_each_pinned_bitwise_method_and_snake_alias_uses_sdk_arguments_and_spec(
        ee, local, name, wire):
    operation, arity = wire
    source = ee.Image("scene-a")
    image = source.select("x")
    if arity == 1:
        value = getattr(image, name)()
        expected_arguments = {"value"}
    else:
        value = getattr(image, name)(source.select("y"))
        expected_arguments = {"image1", "image2"}
    expression = encode(ee, value)
    call = find_invocation(expression, "Image." + name)
    assert call is not None and set(call["arguments"]) == expected_arguments

    result = compile_expression(expression, *local)
    integer = nodes(result, "local_ee_integer_values")
    assert len(integer) == 1
    assert json.loads(integer[0]["arguments"]["spec"]) == {
        "dtype": None, "op": operation,
        "operands": ([{"band": 0}] if arity == 1 else [{"band": 0}, {"band": 1}]),
        "v": 1,
    }
    assert len(nodes(result, "local_ee_to_double")) == arity
    validate(result["process_graph"])


def test_public_handler_inventory_is_the_closed_cast_and_bitwise_family():
    assert IMAGE_INTEGER_FUNCTIONS == frozenset(
        "Image." + name for name in (*CASTS, *BITWISE)
    )


@pytest.mark.parametrize("left_names,right_names,expected_names", [
    (["x"], ["z", "y"], ["z", "y"]),
    (["x", "y"], ["z"], ["x", "y"]),
    (["x", "y"], ["y", "x"], ["x", "y"]),
])
def test_pairing_uses_sdk_band_names_broadcast_and_image1_order(
        ee, local, left_names, right_names, expected_names):
    source = ee.Image("scene-a")
    expression = encode(
        ee, source.select(left_names).bitwiseAnd(source.select(right_names)),
    )
    call = find_invocation(expression, "Image.bitwiseAnd")
    assert set(call["arguments"]) == {"image1", "image2"}
    result = compile_expression(expression, *local)
    assert result["bands"] == expected_names
    specs = [json.loads(node["arguments"]["spec"])
             for node in nodes(result, "local_ee_integer_values")]
    assert [spec["operands"] for spec in specs] == [
        [{"band": 0}, {"band": 1}], [{"band": 0}, {"band": 1}],
    ]
    validate(result["process_graph"])


@pytest.mark.parametrize("name,args,expected", [
    ("Image.toUint8", {"value": Image([("constant", Pixel("constant", (-1.75,)))], {})}, 0),
    ("Image.toByte", {"value": Image([("constant", Pixel("constant", (257.8,)))], {})}, 255),
    ("Image.bitwiseAnd", {
        "image1": Image([("constant", Pixel("to_double", (Pixel("constant", (13,)),)))], {}),
        "image2": Image([("constant", Pixel("constant", (5,)))], {}),
    }, 5),
    ("Image.bitwiseAnd", {
        "image1": Image([("constant", Pixel("constant", (13,)))], {}),
        "image2": Image([("constant", Pixel("constant", (5,)))], {}),
    }, 5),
    ("Image.bitCount", {"value": Image([("constant", Pixel("constant", (-1,)))], {})}, 64),
])
def test_static_integer_operations_fold_to_existing_constant_pixel(name, args, expected):
    translator = Translator([], {}, {})
    result = invoke_image_integer(translator, name, args)
    assert isinstance(result, Image)
    folded = result.bands[0][1]
    assert folded.op == "to_double"
    assert folded.args[0].op == "constant"
    assert folded.args[0].args == (expected,)


def test_integer_operation_precharges_large_outputs_before_pair_materialization():
    source = Source("catalog", ("scene",), tuple(f"b{i}" for i in range(313)))
    image = Image([
        (name, Pixel("band", (source, name))) for name in source.names
    ], {})
    translator = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_image_integer(translator, "Image.toInt32", {"value": image})
    assert translator.steps < 50_000


@pytest.mark.parametrize("name,left,right", [
    ("Image.bitwiseAnd", 1.5, 1),
    ("Image.bitwiseOr", 2**53 + 2, 1),
    ("Image.leftShift", 1, 64),
    ("Image.leftShift", 2**53, 1),
    ("Image.rightShift", 1, -1),
])
def test_invalid_constant_bit_values_and_shifts_reject(name, left, right):
    image1 = Image([("constant", Pixel("constant", (left,)))], {})
    image2 = Image([("constant", Pixel("constant", (right,)))], {})
    translator = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError, match="unsupported integer values"):
        invoke_image_integer(
            translator, name, {"image1": image1, "image2": image2},
        )


def test_image_cast_preserves_all_existing_ir_metadata_fields():
    source = Source("catalog", ("scene",), ("x",))
    footprint = {"type": "Polygon", "coordinates": []}
    image = Image(
        [("x", Pixel("band", (source, "x")))], {"marker": "kept"}, source,
        True, False, ("marker",), footprint, True,
    )
    result = invoke_image_integer(
        Translator([], {}, {}), "Image.toInt16", {"value": image},
    )
    assert result.props == image.props
    assert result.source == image.source
    assert result.mapped is image.mapped
    assert result.inherit_props is image.inherit_props
    assert result.copied_props == image.copied_props
    assert result.footprint is image.footprint
    assert result.footprint_is_absolute is image.footprint_is_absolute


def test_binary_operation_keeps_left_properties_and_footprint_with_source_fallback():
    source = Source("catalog", ("scene",), ("x",))
    left_footprint = {"type": "Polygon", "coordinates": []}
    left = Image(
        [("x", Pixel("constant", (3,)))], {"left": 1}, None, False,
        True, ("left",), left_footprint, True,
    )
    right = Image(
        [("y", Pixel("band", (source, "x")))], {"right": 2}, source, True,
        False, ("right",), {"type": "Polygon", "coordinates": []}, False,
    )
    result = invoke_image_integer(
        Translator([], {}, {}), "Image.bitwiseAnd",
        {"image1": left, "image2": right},
    )
    assert result.props == left.props
    assert result.source == source
    assert result.mapped is True
    assert result.inherit_props is left.inherit_props
    assert result.copied_props == left.copied_props
    assert result.footprint is left_footprint
    assert result.footprint_is_absolute is left.footprint_is_absolute
