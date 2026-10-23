"""The SDK mask adapter must lower to safe real-cube processes, not callbacks."""
import json
from pathlib import Path
import pytest

from gee import graph
from gee.backend import Processes
from gee.ee_translate import UnsupportedEEError
from gee.integer_values_spec import constant_operand
from test_ee_translate import local, compile, call, first, select, col


def filled(value=None):
    return call("Image.unmask", input=select(first(), "nir"),
                **({"value": value} if value is not None else {}))


def test_constant_fill_has_its_own_valid_grid_and_keeps_large_integer(local):
    compiled = compile(filled(16_777_219), local)
    graph.validate(compiled["process_graph"])
    nodes = list(compiled["process_graph"].values())
    constant = next(n for n in nodes if n["process_id"] == "local_ee_constant_on_grid")
    assert constant["arguments"]["value"] == 16_777_219
    assert any(n["process_id"] == "local_ee_unmask" for n in nodes)
    assert nodes[-1]["process_id"] == "rename_labels"


def test_raster_fill_is_a_separate_cube_with_its_own_mask(local):
    compiled = compile(filled(select(first(), "red")), local)
    graph.validate(compiled["process_graph"])
    nodes = list(compiled["process_graph"].values())
    assert not any(n["process_id"] == "local_ee_constant_on_grid" for n in nodes)
    unmask = next(n for n in nodes if n["process_id"] == "local_ee_unmask")
    assert unmask["arguments"]["data"] != unmask["arguments"]["value"]


def test_fixed_official_sdk_raster_expressions_reach_valid_native_graphs(local):
    fixture = json.loads((Path(__file__).parent / "fixtures/ee-mask-1.7.49.json").read_text())
    for expression in fixture["raster_expressions"].values():
        result = compile(expression, local)
        graph.validate(result["process_graph"])
        assert result["bands"] == ["nir"]
        assert result["has_time_dimension"] is False


def test_float64_fill_uses_native_arithmetic_and_explicit_float_uses_callback(local):
    native = compile(call("Image.add", image1=filled(), image2=1), local)
    graph.validate(native["process_graph"])
    integer = [node for node in native["process_graph"].values()
               if node["process_id"] == "local_ee_integer_values"]
    assert len(integer) == 1
    assert json.loads(integer[0]["arguments"]["spec"]) == {
        "dtype": None, "op": "add",
        "operands": [{"band": 0}, constant_operand(1)], "v": 1,
    }
    assert any(node["process_id"] == "local_ee_unmask"
               for node in native["process_graph"].values())
    assert not any(node["process_id"] == "reduce_dimension"
                   and node["arguments"].get("dimension") == "bands"
                   for node in native["process_graph"].values())

    explicit_float = compile(
        call("Image.add", image1=call("Image.toFloat", value=filled()), image2=1), local,
    )
    graph.validate(explicit_float["process_graph"])
    assert not any(node["process_id"] == "local_ee_integer_values"
                   for node in explicit_float["process_graph"].values())
    assert any(node["process_id"] == "reduce_dimension"
               and node["arguments"].get("dimension") == "bands"
               for node in explicit_float["process_graph"].values())
    mapped = call("Collection.map", collection=col(), baseAlgorithm={
        "type": "Function", "argumentNames": ["im"], "body": call("Image.unmask", input={"type": "ArgumentRef", "value": "im"})})
    result = compile(call("reduce.mean", collection=mapped), local)
    graph.validate(result["process_graph"])
    assert any(node["process_id"] == "local_ee_reduce_bands"
               for node in result["process_graph"].values())
    assert result["has_time_dimension"] is False


def test_timed_multi_item_input_cannot_silently_use_daily_merged_observations(local):
    from gee.ee_translate import Translator, Graph
    translator = Translator(*local, None)
    collection = translator.evaluate(col())
    image = translator.invoke("Image.unmask", {"input": collection.image})
    with pytest.raises(UnsupportedEEError, match="individual observations"):
        Graph(translator).image(image)


def test_folded_scalar_replacement_obeys_the_same_finite_range_as_literals(local):
    too_large = call("Image.add", image1=call("Image.constant", value=2**53), image2=1)
    for value in (too_large, 1e16, float("inf")):
        with pytest.raises(UnsupportedEEError, match="Float64|finite"):
            compile(filled(value), local)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 2**53+1, "/tmp/source", {"from_node": "load"}])
def test_constant_process_rejects_unsafe_or_inexact_values(value):
    nodes = {"load": {"process_id": "load_collection", "arguments": {"id": "test"}},
             "fill": {"process_id": "local_ee_constant_on_grid", "arguments": {
                 "data": {"from_node": "load"}, "value": value}, "result": True}}
    with pytest.raises(ValueError):
        graph.validate(nodes)


def test_mask_specs_declare_cube_replacement_and_finite_scalar():
    registry = Processes().get_process_registry("1.2.0")
    for name in ("local_ee_constant_on_grid", "local_ee_unmask"):
        assert [p["name"] for p in registry.get_spec(name)["parameters"]][:2] == ["data", "value"]
