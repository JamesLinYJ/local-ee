"""Public graph and strict wire controls for the focal raster process."""
import json

import pytest

from gee.backend import Processes
from gee.focal_spec import decode_focal_spec, prepare_focal_spec
from gee.graph import validate
from gee.local_processes import validate_local_process


def graph(spec=None, **extra):
    return {
        "load": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "focal": {"process_id": "local_ee_focal", "result": True, "arguments": {
            "data": {"from_node": "load"},
            "spec": spec if spec is not None else prepare_focal_spec("mean", [(0, 0)]),
            **extra,
        }},
    }


@pytest.mark.parametrize("operation", ["mean", "min", "max", "median", "mode"])
def test_native_operations_have_valid_direct_top_level_graphs(operation):
    validate(graph(prepare_focal_spec(operation, [(1, 0), (-1, 0), (0, 0)])))


def test_wire_round_trip_canonical_order_limits_and_input_ownership():
    offsets = [[32, 0], [-32, -1], [0, 0]]
    text = prepare_focal_spec("mode", offsets, 8, False)
    offsets[0][0] = 99
    assert decode_focal_spec(text) == {
        "v": 1, "operation": "mode", "iterations": 8, "skip_masked": False,
        "offsets": [[-32, -1], [0, 0], [32, 0]],
    }
    maximum = prepare_focal_spec("mean", [(x, y) for y in range(-16, 17) for x in range(-16, 17)])
    assert len(decode_focal_spec(maximum)["offsets"]) == 1089


@pytest.mark.parametrize("field,value", [
    ("v", True), ("v", 1.0), ("v", 2), ("operation", "sum"),
    ("operation", {"from_node": "load"}), ("iterations", True),
    ("iterations", 0), ("iterations", 9), ("iterations", 1.0),
    ("skip_masked", 1), ("offsets", []), ("offsets", [[0, 0, 0]]),
    ("offsets", [[True, 0]]), ("offsets", [[0.0, 0]]),
    ("offsets", [[33, 0]]), ("offsets", [[0, 0], [0, 0]]),
    ("offsets", [[1, 0], [0, 0]]), ("offsets", [[0, 0]] * 1090),
])
def test_malformed_specs_reject_before_native_execution(field, value):
    spec = decode_focal_spec(prepare_focal_spec("mean", [(0, 0)]))
    spec[field] = value
    with pytest.raises(ValueError):
        validate(graph(json.dumps(spec, sort_keys=True, separators=(",", ":"))))


@pytest.mark.parametrize("text", [
    "{}", "[]", "[" * 1001, "x" * 32769, "é", None, {},
    '{"v":1,"v":1}',
    ' {"iterations":1,"offsets":[[0,0]],"operation":"mean","skip_masked":true,"v":1}',
])
def test_decoder_rejects_noncanonical_or_unbounded_json(text):
    with pytest.raises(ValueError):
        decode_focal_spec(text)


@pytest.mark.parametrize("offsets", [iter([(0, 0)]), [[True, 0]], [[0, 0]] * 1090, [[0, 0], [0, 0]]])
def test_encoder_requires_a_bounded_finite_sequence(offsets):
    with pytest.raises(ValueError):
        prepare_focal_spec("mean", offsets)


@pytest.mark.parametrize("data", [None, "/tmp/a.tif", {"from_parameter": "data"},
                                  {"from_node": "load", "extra": 1}])
def test_focal_rejects_paths_parameters_and_mixed_references(data):
    with pytest.raises(ValueError):
        validate(graph(data=data))


def test_focal_rejects_callbacks_extra_args_and_result_inputs():
    with pytest.raises(ValueError, match="top-level"):
        validate_local_process("local_ee_focal", graph()["focal"]["arguments"], 1)
    with pytest.raises(ValueError):
        validate(graph(extra=True))
    nodes = graph()
    nodes["saved"] = {"process_id": "save_result", "arguments": {
        "data": {"from_node": "load"}, "format": "GTiff"}}
    nodes["focal"]["arguments"]["data"] = {"from_node": "saved"}
    with pytest.raises(ValueError, match="raster cube"):
        validate(nodes)


def test_focal_public_spec_declares_only_a_cube_and_bounded_text():
    spec = Processes().get_process_registry("1.2.0").get_spec("local_ee_focal")
    assert [p["name"] for p in spec["parameters"]] == ["data", "spec"]
    assert spec["parameters"][1]["schema"] == {"type": "string", "maxLength": 32768}
    assert spec["returns"]["schema"]["subtype"] == "raster-cube"


def test_focal_inventory_names_match_implemented_families():
    from gee.compat.earthengine.capabilities import SUPPORTED_FUNCTIONS
    from gee.compat.earthengine.image_focal import FOCAL_FUNCTIONS
    from gee.compat.earthengine.kernel_values import KERNEL_FUNCTIONS
    assert len(FOCAL_FUNCTIONS) == 11
    assert {"Kernel.fixed", "Kernel.circle", "Kernel.square", "Kernel.rectangle",
            "Kernel.plus", "Kernel.cross", "Kernel.diamond", "Kernel.octagon"} <= KERNEL_FUNCTIONS
    assert FOCAL_FUNCTIONS | KERNEL_FUNCTIONS <= SUPPORTED_FUNCTIONS
