"""Strict wire and finite-constant policies for the raster integer SPI."""
import json
import math

import pytest

from gee.backend import Processes
from gee.graph import validate
from gee.integer_values_contract import CAST_BOUNDS, OPERATIONS, evaluate_integer_values
from gee.integer_values_spec import constant_operand, decode_integer_values_spec, prepare_integer_values_spec
from gee.local_processes import validate_local_process


def wire(op="bit_and", values=None, dtype=None):
    if values is None:
        values = [{"band": 0}, constant_operand(1024)]
    return prepare_integer_values_spec(op, values, dtype)


def graph(text=None, **extra):
    return {
        "load": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "integer": {"process_id": "local_ee_integer_values", "result": True,
                    "arguments": {"data": {"from_node": "load"}, "spec": wire() if text is None else text, **extra}},
    }


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_all_closed_operations_validate_public_wire(operation):
    unary = operation in {"cast", "bit_not", "bit_count", "absolute", "sqrt", "log", "log10",
                          "exp", "round", "floor", "ceil", "sin", "cos", "tan", "not"}
    if operation in {"select", "where_select"}:
        operands = [{"band": 0}, {"band": 1}, {"band": 2}]
    else:
        operands = [{"band": 0}] if unary else [{"band": 0}, {"band": 1}]
    text = wire(operation, operands, "int16" if operation == "cast" else None)
    validate(graph(text))
    assert decode_integer_values_spec(text)["op"] == operation


def test_binary64_constants_preserve_signed_zero_subnormals_and_high_bits():
    assert constant_operand(-0.0) == {"constant": "8000000000000000"}
    assert constant_operand(0.0) == {"constant": "0000000000000000"}
    for value in (math.ulp(0.0), 2**53, -(2**53), 1.7976931348623157e308):
        text = wire("eq", [{"band": 0}, constant_operand(value)])
        assert decode_integer_values_spec(text)["operands"][1] == constant_operand(value)
    assert evaluate_integer_values("eq", [-0.0, 0.0]) == 1
    assert evaluate_integer_values("gt", [2**40 + 1, 2**40]) == 1
    assert evaluate_integer_values("lt", [math.ulp(0.0), 2 * math.ulp(0.0)]) == 1


@pytest.mark.parametrize("value", [None, True, "3", [], float("nan"), float("inf"), 2**53 + 1, 10**1000])
def test_constants_reject_nonfinite_or_lossy_input(value):
    with pytest.raises(ValueError):
        constant_operand(value)


@pytest.mark.parametrize("op,index,value", [
    ("bit_and", 1, 0.5), ("bit_or", 1, 2.0**54), ("bit_xor", 1, -2.0**54),
    ("left_shift", 1, -1), ("left_shift", 1, 64), ("right_shift", 1, 0.5),
    ("bit_not", 0, 0.25),
])
def test_constant_domains_reject_before_raster_evaluation(op, index, value):
    operands = [{"band": 0}, {"band": 0}]
    if op == "bit_not":
        # Preserve one band while testing the same invalid value through a binary op.
        operands = [{"band": 0}, constant_operand(value)]
        op = "bit_and"
    else:
        operands[index] = constant_operand(value)
    with pytest.raises(ValueError):
        wire(op, operands)


@pytest.mark.parametrize("operands", [
    [], [{"band": 1}, {"band": 1}], [constant_operand(1), constant_operand(2)],
    [{"band": True}, {"band": 0}], [{"band": 0.0}, {"band": 0}],
    [{"band": 0, "constant": "0000000000000000"}, {"band": 0}],
    [{"constant": "7ff0000000000000"}, {"band": 0}],
    [{"constant": "7FF0000000000000"}, {"band": 0}],
])
def test_operand_schema_is_closed_contiguous_and_nonempty(operands):
    with pytest.raises(ValueError):
        wire(values=operands)


def test_noncanonical_unknown_duplicate_fields_and_versions_reject():
    text = wire()
    invalid = [None, {}, "[]", "{}", "x" * 1025, "é", "[" * 1000,
               text + " ", text + text, text.replace('"v":1', '"v":true'),
               text.replace('"v":1', '"v":1.0'), text.replace('"v":1', '"v":2'),
               text[:-1] + ',"extra":0}', text[:-1] + ',"v":1}',
               text.replace('"band":0', '"band":0,"band":0'),
               json.dumps(json.loads(text), indent=2)]
    for value in invalid:
        with pytest.raises(ValueError):
            decode_integer_values_spec(value)


@pytest.mark.parametrize("dtype", CAST_BOUNDS)
def test_constant_casts_truncate_clamp_without_integer_sentinel_loss(dtype):
    minimum, maximum = CAST_BOUNDS[dtype]
    assert evaluate_integer_values("cast", [-1.75], dtype) == max(minimum, -1)
    if dtype != "int64":
        assert evaluate_integer_values("cast", [-1.7976931348623157e308], dtype) == minimum
        assert evaluate_integer_values("cast", [1.7976931348623157e308], dtype) == maximum
    assert evaluate_integer_values("cast", [minimum], dtype) == minimum
    assert evaluate_integer_values("cast", [maximum], dtype) == maximum


def test_two_complement_and_nonwrapping_shift_results():
    assert evaluate_integer_values("bit_count", [-1]) == 64
    assert evaluate_integer_values("bit_count", [-(2**53)]) == 11
    assert evaluate_integer_values("right_shift", [-3, 1]) == -2
    assert evaluate_integer_values("left_shift", [-1, 53]) == -(2**53)
    assert evaluate_integer_values("bit_and", [2**40 + 1024, 1024]) == 1024
    for op, values in (("bit_not", [2**53]), ("left_shift", [1, 54]),
                       ("bit_xor", [2**53, -1]), ("cast", [2.0**54])):
        with pytest.raises(ValueError):
            evaluate_integer_values(op, values, "int64" if op == "cast" else None)


def test_public_gate_and_process_registry_remain_closed():
    args = graph()["integer"]["arguments"]
    with pytest.raises(ValueError, match="top-level"):
        validate_local_process("local_ee_integer_values", args, 1)
    with pytest.raises(ValueError):
        validate(graph(extra=True))
    for data in ("/tmp/x.tif", None, {"from_parameter": "data"}, {"from_node": "load", "x": 0}):
        with pytest.raises(ValueError):
            validate(graph(data=data))
    nodes = graph(data={"from_node": "scalar"})
    nodes["scalar"] = {"process_id": "add", "arguments": {"x": 1, "y": 2}}
    with pytest.raises(ValueError, match="raster cube"):
        validate(nodes)
    spec = Processes().get_process_registry("1.2.0").get_spec("local_ee_integer_values")
    assert [p["name"] for p in spec["parameters"]] == ["data", "spec"]
    assert spec["parameters"][1]["schema"]["maxLength"] == 1024
    assert "Float64" in spec["returns"]["description"]
