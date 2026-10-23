"""Pinned-SDK and bounded graph contracts for Image pixel math."""
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.image_pixel_math import (
    IMAGE_PIXEL_MATH_FUNCTIONS,
    invoke_image_pixel_math,
)
from gee.compat.earthengine.ir import Image, ImageSequence, Pixel, Source
from gee.compat.earthengine.pixel_math_graph import (
    contains_pixel_math,
    requires_per_item_pixel_math,
)
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
UNARY = (
    "asin", "acos", "atan", "sinh", "cosh", "tanh", "cbrt", "signum",
    "gamma", "digamma", "trigamma", "erf", "erfc", "erfInv", "erfcInv",
)
OPERATIONS = (*UNARY, "atan2")
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
    names = ["x", "y", "z"]
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {
        "bands": {"values": names}}}]
    items = {"sentinel-2-l2a": [
        {"id": "pixel-scene-a", "bbox": [0, 0, 4, 1], "geometry": GEOMETRY,
         "properties": {"system:index": "pixel-scene-a", "system:time_start": 1000}},
        {"id": "pixel-scene-b", "bbox": [0, 0, 4, 1], "geometry": GEOMETRY,
         "properties": {"system:index": "pixel-scene-b", "system:time_start": 1000}},
    ]}
    return catalog, items


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def find_invocation(value, function_name):
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == function_name:
            return value
        for child in value.values():
            result = find_invocation(child, function_name)
            if result is not None:
                return result
    elif isinstance(value, (list, tuple)):
        for child in value:
            result = find_invocation(child, function_name)
            if result is not None:
                return result
    return None


def process_nodes(result, process_id):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == process_id]


def named_input_bands(result, reference):
    """Trace the ordered input branches through casts to their final labels."""
    graph = result["process_graph"]
    names = []

    def visit(ref):
        node = graph[ref["from_node"]]
        process = node["process_id"]
        arguments = node["arguments"]
        if process == "merge_cubes":
            visit(arguments["cube1"])
            visit(arguments["cube2"])
        elif process == "rename_labels":
            names.extend(arguments["target"])
        elif process == "local_ee_to_float":
            visit(arguments["data"])

    visit(reference)
    return names


@pytest.mark.parametrize("operation", OPERATIONS)
def test_pinned_sdk_serialization_and_every_operation_lowers_to_its_spi_name(
        ee, local, operation):
    source = ee.Image("pixel-scene-a").select("x")
    if operation == "atan2":
        value = source.atan2(ee.Image("pixel-scene-a").select("y"))
        parameters = {"image1", "image2"}
    else:
        value = getattr(source, operation)()
        parameters = {"value"}

    expression = encode(ee, value)
    call = find_invocation(expression, "Image." + operation)
    assert call is not None
    assert set(call["arguments"]) == parameters

    compiled = compile_expression(expression, *local)
    assert compiled["kind"] == "image"
    assert compiled["bands"] == ["x"]
    assert compiled["source_item_ids"] == ["pixel-scene-a"]
    assert compiled["has_time_dimension"] is False
    assert [node["arguments"]["operation"]
            for node in process_nodes(compiled, "local_ee_pixel_math")] == [operation]
    assert named_input_bands(
        compiled, process_nodes(compiled, "local_ee_pixel_math")[0]["arguments"]["data"],
    ) == (["x", "y"] if operation == "atan2" else ["x"])
    validate(compiled["process_graph"])


def test_sdk_method_inventory_and_actual_argument_arities_are_closed(ee):
    assert IMAGE_PIXEL_MATH_FUNCTIONS == frozenset("Image." + name for name in OPERATIONS)
    source = ee.Image("pixel-scene-a")
    for operation in UNARY:
        assert callable(getattr(source, operation))
        call = find_invocation(encode(ee, getattr(source, operation)()), "Image." + operation)
        assert set(call["arguments"]) == {"value"}
    call = find_invocation(
        encode(ee, source.atan2(ee.Image("pixel-scene-a"))), "Image.atan2",
    )
    assert set(call["arguments"]) == {"image1", "image2"}


def test_atan2_uses_sdk_x_then_y_order_with_single_band_broadcast(ee, local):
    source = ee.Image("pixel-scene-a")
    result = compile_expression(encode(ee, source.select("x").atan2(source.select(["z", "y"]))),
                                *local)
    assert result["bands"] == ["z", "y"]
    math_node = process_nodes(result, "local_ee_pixel_math")[0]
    assert math_node["arguments"]["operation"] == "atan2"
    assert named_input_bands(result, math_node["arguments"]["data"]) == ["x", "y"]


def test_atan2_scalar_is_bound_to_the_real_raster_grid(ee, local):
    source = ee.Image("pixel-scene-a").select("x")
    result = compile_expression(encode(ee, source.atan2(0.5)), *local)
    assert result["source_item_ids"] == ["pixel-scene-a"]
    math_node = process_nodes(result, "local_ee_pixel_math")[0]
    inputs = named_input_bands(result, math_node["arguments"]["data"])
    assert inputs == ["x", "y"]
    assert len(process_nodes(result, "local_ee_constant_on_grid")) == 1
    validate(result["process_graph"])


def test_atan2_rejects_mismatched_and_hidden_mixed_source_lineages(ee, local):
    first = ee.Image("pixel-scene-a").select("x")
    second = ee.Image("pixel-scene-b").select("x")
    with pytest.raises(UnsupportedEEError, match="same ordered source collection and item IDs"):
        compile_expression(encode(ee, first.atan2(second)), *local)

    mixed = first.add(second)
    with pytest.raises(UnsupportedEEError, match="multiple local source lineages"):
        compile_expression(encode(ee, mixed.atan2(first)), *local)

    translator = Translator(local[0], local[1], {})
    source_a = Source("sentinel-2-l2a", ("pixel-scene-a",), ("x",))
    source_b = Source("other-collection", ("pixel-scene-a",), ("x",))
    pixel = Pixel(
        "math_atan2",
        (Pixel("band", (source_a, "x")), Pixel("band", (source_b, "x"))),
    )
    with pytest.raises(UnsupportedEEError, match="same ordered source collection and item IDs"):
        Graph(translator).expression(pixel)


@pytest.mark.parametrize("operation", ["add", "addBands"])
def test_mapped_constant_math_uses_per_item_grids_for_same_timestamp_items(
        ee, local, operation):
    collection = ee.ImageCollection("sentinel-2-l2a")
    if operation == "add":
        mapped = collection.map(
            lambda image: image.select("x").add(ee.Image.constant(0.5).erf()),
        )
    else:
        mapped = collection.map(
            lambda image: image.select("x").addBands(
                ee.Image.constant(0.5).erf().rename("error"),
            ),
        )
    result = compile_expression(encode(ee, mapped), *local)

    assert result["kind"] == "collection"
    assert result["source_item_ids"] == ["pixel-scene-a", "pixel-scene-b"]
    assert result["has_time_dimension"] is True
    assert [feature["properties"]["system:time_start"] for feature in result["features"]] == [1000, 1000]
    evaluated = Translator(local[0], local[1], {}).evaluate(encode(ee, mapped))
    assert isinstance(evaluated, ImageSequence)
    assert [image.source.ids for image in evaluated.images] == [
        ("pixel-scene-a",), ("pixel-scene-b",),
    ]
    assert all(contains_pixel_math(tuple(pixel for _, pixel in image.bands))
               for image in evaluated.images)

    first_result = compile_expression(encode(ee, mapped.first()), *local)
    assert first_result["source_item_ids"] == ["pixel-scene-a"]
    assert [node["arguments"]["operation"]
            for node in process_nodes(first_result, "local_ee_pixel_math")] == ["erf"]
    assert len(process_nodes(first_result, "local_ee_constant_on_grid")) == 1
    validate(first_result["process_graph"])


def test_mapped_atan2_scalar_uses_each_item_grid_and_keeps_double_guard(ee, local):
    collection = ee.ImageCollection("sentinel-2-l2a")
    mapped = collection.map(lambda image: image.select("x").atan2(0.5))
    result = compile_expression(encode(ee, mapped), *local)
    assert result["kind"] == "collection"
    assert result["source_item_ids"] == ["pixel-scene-a", "pixel-scene-b"]
    assert result["has_time_dimension"] is True
    assert [feature["properties"]["system:time_start"] for feature in result["features"]] == [1000, 1000]
    evaluated = Translator(local[0], local[1], {}).evaluate(encode(ee, mapped))
    assert isinstance(evaluated, ImageSequence)
    assert [image.source.ids for image in evaluated.images] == [
        ("pixel-scene-a",), ("pixel-scene-b",),
    ]
    first_result = compile_expression(encode(ee, mapped.first()), *local)
    assert len(process_nodes(first_result, "local_ee_constant_on_grid")) == 1
    assert len(process_nodes(first_result, "local_ee_pixel_math")) == 1

    double_mapped = collection.map(
        lambda image: image.select("x").toDouble().atan2(0.5),
    )
    with pytest.raises(UnsupportedEEError, match=r"apply toFloat\(\) explicitly"):
        compile_expression(encode(ee, double_mapped.first()), *local)


def test_pixel_math_float32_boundary_is_visible_in_graph_compiler():
    graph = Graph(Translator([], {}, {}))
    value, label, timed = graph.expression(Pixel("to_float", (Pixel("constant", (16777217,)),)))
    assert (value, label, timed) == (16777216.0, None, True)


def test_per_item_pixel_math_scan_precharges_the_translator_budget():
    translator = Translator([], {}, {})
    translator.steps = 49_999
    image = Image([("x", Pixel("math_erf", (Pixel("constant", (0.5,)),)))], {})
    with pytest.raises(UnsupportedEEError, match="graph exceeds compilation limits"):
        requires_per_item_pixel_math(image, translator)
    assert translator.steps == 49_999


def test_deferred_constant_math_binds_to_the_destination_real_grid(ee, local):
    source = ee.Image("pixel-scene-a").select("x")
    constant_math = ee.Image.constant(0.5).erf().rename("error")
    result = compile_expression(encode(ee, source.addBands(constant_math)), *local)

    assert result["bands"] == ["x", "error"]
    assert result["source_item_ids"] == ["pixel-scene-a"]
    math_node = process_nodes(result, "local_ee_pixel_math")[0]
    assert math_node["arguments"]["operation"] == "erf"
    assert len(process_nodes(result, "local_ee_constant_on_grid")) == 1
    assert process_nodes(result, "local_ee_to_float")
    validate(result["process_graph"])


def test_unbound_constant_math_has_no_fabricated_global_grid(ee, local):
    expression = encode(ee, ee.Image.constant(0.5).digamma())
    with pytest.raises(UnsupportedEEError, match="standalone constant image needs a raster grid"):
        compile_expression(expression, *local)


def test_double_precision_input_is_rejected_until_explicit_float_cast(ee, local):
    source = ee.Image("pixel-scene-a").select("x")
    with pytest.raises(UnsupportedEEError, match=r"apply toFloat\(\) explicitly"):
        compile_expression(encode(ee, source.toDouble().asin()), *local)

    narrowed = compile_expression(encode(ee, source.toDouble().toFloat().asin()), *local)
    assert process_nodes(narrowed, "local_ee_pixel_math")
    assert process_nodes(narrowed, "local_ee_to_float")

    widened = compile_expression(encode(ee, source.erf().toDouble()), *local)
    assert process_nodes(widened, "local_ee_to_double")


def test_math_pixels_inside_scalar_subtrees_bind_only_when_joined_to_real_raster(
        ee, local):
    source = ee.Image("pixel-scene-a").select("x")
    deferred = ee.Image.constant(0.5).digamma().add(1).rename("shifted")
    result = compile_expression(encode(ee, source.addBands(deferred)), *local)
    assert result["bands"] == ["x", "shifted"]
    assert [node["arguments"]["operation"]
            for node in process_nodes(result, "local_ee_pixel_math")] == ["digamma"]

    mixed = source.add(ee.Image.constant(0.5).erfc().add(1))
    mixed_result = compile_expression(encode(ee, mixed), *local)
    assert process_nodes(mixed_result, "local_ee_pixel_math")[0]["arguments"]["operation"] == "erfc"


def test_mapped_math_keeps_distinct_same_timestamp_observation_ids(ee, local):
    collection = ee.ImageCollection("sentinel-2-l2a").map(
        lambda image: image.select("x").trigamma(),
    )
    result = compile_expression(encode(ee, collection), *local)
    assert result["kind"] == "collection"
    assert result["source_item_ids"] == ["pixel-scene-a", "pixel-scene-b"]
    assert result["has_time_dimension"] is True
    assert process_nodes(result, "local_ee_pixel_math")


def test_pixel_math_rejects_unknown_arguments_mismatched_bands_and_unbounded_work(
        ee, local, monkeypatch):
    source = ee.Image("pixel-scene-a").select("x")
    expression = encode(ee, source.asin())
    call = find_invocation(expression, "Image.asin")
    call["arguments"]["unexpected"] = 1
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(expression, *local)

    mismatched = encode(ee,
        ee.Image("pixel-scene-a").select(["x", "y"]).atan2(
            ee.Image("pixel-scene-a").select(["x", "y", "z"]),
        ),
    )
    with pytest.raises(UnsupportedEEError, match="equal band counts"):
        compile_expression(mismatched, *local)

    translator = Translator([], {}, None)
    translator.steps = 49_999
    monkeypatch.setattr(
        "gee.compat.earthengine.image_pixel_math.as_image",
        lambda *_args: pytest.fail("operand allocation occurred before work preflight"),
    )
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_image_pixel_math(translator, "Image.asin", {"value": [1]})
