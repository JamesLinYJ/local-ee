"""Public graph boundaries for the fixed native pixel-math process."""
import pytest

from gee.backend import Processes
from gee.graph import validate
from gee.local_processes import validate_local_process
from gee.pixel_math_contract import PIXEL_MATH_ARITIES


def graph(operation="asin", **extra):
    return {
        "load": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "math": {"process_id": "local_ee_pixel_math", "result": True,
                 "arguments": {"data": {"from_node": "load"}, "operation": operation, **extra}},
    }


@pytest.mark.parametrize("operation", PIXEL_MATH_ARITIES)
def test_each_native_operation_has_a_valid_direct_top_level_graph(operation):
    validate(graph(operation))


@pytest.mark.parametrize("operation", [None, "atan_2", "GAMMA", {"from_node": "load"}, True])
def test_operation_is_literal_and_closed(operation):
    with pytest.raises(ValueError):
        validate(graph(operation))


@pytest.mark.parametrize("data", [None, "/tmp/input.tif", {"from_parameter": "data"},
                                  {"from_node": "load", "extra": 1}])
def test_native_math_rejects_paths_parameters_and_mixed_references(data):
    with pytest.raises(ValueError):
        validate(graph(data=data))


def test_native_math_rejects_callback_scope_extra_arguments_and_result_input():
    arguments = {"data": {"from_node": "load"}, "operation": "sin"}
    with pytest.raises(ValueError, match="top-level"):
        validate_local_process("local_ee_pixel_math", arguments, 1)
    with pytest.raises(ValueError, match="supported arguments"):
        validate(graph(value=2))
    process_graph = graph()
    process_graph["saved"] = {"process_id": "save_result", "arguments": {
        "data": {"from_node": "load"}, "format": "GTiff"}}
    process_graph["math"]["arguments"]["data"] = {"from_node": "saved"}
    with pytest.raises(ValueError, match="raster cube"):
        validate(process_graph)


def test_public_process_spec_uses_the_same_closed_operation_contract():
    specification = Processes().get_process_registry("1.2.0").get_spec("local_ee_pixel_math")
    assert [parameter["name"] for parameter in specification["parameters"]] == ["data", "operation"]
    assert specification["parameters"][1]["schema"]["enum"] == sorted(PIXEL_MATH_ARITIES)
    assert specification["returns"]["schema"]["subtype"] == "raster-cube"
    assert "Float32" in specification["returns"]["description"]
