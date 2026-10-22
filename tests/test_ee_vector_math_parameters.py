"""Strict type, shape, resource and failure contracts for vector math."""
import math
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine import array_arithmetic, number_math
from gee.compat.earthengine.array_core import MAX_ARRAY_WORK, StaticArray, wrap_array
from gee.compat.earthengine.array_arithmetic import invoke_arithmetic
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.static_values import invoke_static
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import SUPPORTED, validate
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


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
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]]}
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["x"]}}}]
    items = {"sentinel-2-l2a": [{
        "id": "vector-scene", "bbox": [0, 0, 2, 1], "geometry": geometry,
        "properties": {"system:index": "vector-scene", "system:time_start": 1000},
    }]}
    return catalog, items


def invocation(name, arguments):
    return {"type": "Invocation", "functionName": name, "arguments": arguments}


def encoded(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


@pytest.mark.parametrize("method,valid,invalid", [
    ("Number.hypot", {"left": 3, "right": 4}, [None, True, "1", [], {},
        float("nan"), float("inf"), float("-inf"), 2**53 + 1]),
    ("Number.atan2", {"left": 3, "right": 4}, [None, True, "1", [], {},
        float("nan"), float("inf"), float("-inf"), 2**53 + 1]),
])
def test_number_algorithms_require_exact_arguments_and_finite_numeric_values(
        ee, method, valid, invalid):
    method_call = getattr(ee.Number(valid["left"]), method.split(".")[1])
    expression = encoded(ee, method_call(valid["right"]))
    assert expression["functionName"] == method
    assert set(expression["arguments"]) == {"left", "right"}
    for arguments in ({}, {"left": 1}, {"left": 1, "right": 2, "extra": 3},
                      {"x": 1, "y": 2}):
        with pytest.raises(UnsupportedEEError):
            compile_expression(invocation(method, arguments), [], {})
    for value in invalid:
        with pytest.raises(UnsupportedEEError):
            compile_expression(invocation(method, {"left": value, "right": 1}), [], {})
    if method == "Number.hypot":
        with pytest.raises(UnsupportedEEError, match="finite real number"):
            compile_expression(invocation(method, {"left": 1.7e308, "right": 1.7e308}), [], {})


def test_atan2_signed_zero_and_negative_x_axis_branch_are_preserved(ee):
    values = [ee.Number(-1).atan2(0.0), ee.Number(-1).atan2(-0.0),
              ee.Number(1).atan2(-0.0)]
    expression = encoded(ee, values)
    actual = compile_expression(expression, [], {})["value"]
    assert actual[0] == math.pi
    assert actual[1] == -math.pi
    assert actual[2] == 0 and math.copysign(1, actual[2]) == -1


@pytest.mark.parametrize("value", [None, True, "2", {"value": 2},
                                   float("nan"), float("inf"), float("-inf"), 2**53 + 1])
@pytest.mark.parametrize("algorithm", ["Array.hypot", "Array.atan2"])
def test_array_algorithms_reject_untyped_or_invalid_operands(ee, value, algorithm):
    with pytest.raises(UnsupportedEEError):
        compile_expression(invocation(algorithm, {"left": value, "right": [1, 2]}), [], {})
    with pytest.raises(UnsupportedEEError):
        compile_expression(invocation(algorithm, {
            "left": invocation("Array", {"values": [[1, 2]]}),
            "right": invocation("Array", {"values": [value]}),
        }), [], {})


@pytest.mark.parametrize("algorithm", ["Array.hypot", "Array.atan2"])
def test_array_algorithms_require_typed_same_shape_nonempty_arrays(ee, algorithm):
    def array(values):
        return invocation("Array", {"values": values})

    for arguments in ({}, {"left": array([1, 2])},
                      {"left": array([1, 2]), "right": array([1, 2]), "extra": 0},
                      {"input": array([1, 2])}):
        with pytest.raises(UnsupportedEEError):
            compile_expression(invocation(algorithm, arguments), [], {})
    for left, right in (([1, 2], [1]), ([[1, 2]], [[1], [2]]), ([], [])):
        with pytest.raises(UnsupportedEEError):
            compile_expression(invocation(algorithm, {
                "left": array(left), "right": array(right),
            }), [], {})


def test_array_hypot_inherits_static_array_cell_and_rank_boundaries(ee):
    boundary = compile_expression(encoded(ee, ee.Array([1] * 10_000)), [], {})["value"]
    assert len(boundary) == 10_000 and boundary[0] == boundary[-1] == 1
    with pytest.raises(UnsupportedEEError, match="10000"):
        compile_expression(encoded(ee, ee.Array([1] * 10_001)), [], {})

    def nested(rank, scalar=1):
        value = scalar
        for _ in range(rank):
            value = [value]
        return value

    rank_eight = compile_expression(
        encoded(ee, ee.Array(nested(8)).hypot(ee.Array(nested(8)))), [], {})["value"]
    assert rank_eight == nested(8, math.sqrt(2))
    with pytest.raises(UnsupportedEEError, match="rank exceeds 8"):
        compile_expression(encoded(ee, ee.Array(nested(9))), [], {})


def test_number_and_array_work_preflight_runs_before_math_kernel(monkeypatch):
    scalar = Translator([], {}, None)
    scalar.steps = MAX_ARRAY_WORK - 1

    def scalar_kernel_must_not_run(*_):
        raise AssertionError("Number math ran before shared-work preflight")

    monkeypatch.setattr(number_math.math, "hypot", scalar_kernel_must_not_run)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_static(scalar, "Number.hypot", {"left": 3, "right": 4})
    assert scalar.steps == MAX_ARRAY_WORK - 1

    atan_scalar = Translator([], {}, None)
    atan_scalar.steps = MAX_ARRAY_WORK - 1

    def scalar_atan_must_not_run(*_):
        raise AssertionError("Number.atan2 ran before shared-work preflight")

    monkeypatch.setattr(number_math.math, "atan2", scalar_atan_must_not_run)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_static(atan_scalar, "Number.atan2", {"left": 3, "right": 4})
    assert atan_scalar.steps == MAX_ARRAY_WORK - 1

    array = StaticArray(np.array([3.0, 4.0]))
    translator = Translator([], {}, None)
    translator.steps = MAX_ARRAY_WORK - 1

    def array_kernel_must_not_run(*_):
        raise AssertionError("Array math ran before shared-work preflight")

    monkeypatch.setattr(array_arithmetic.np, "hypot", array_kernel_must_not_run)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_arithmetic(translator, "Array.hypot", {"left": array, "right": array})
    assert translator.steps == MAX_ARRAY_WORK - 1

    atan_array_translator = Translator([], {}, None)
    atan_array_translator.steps = MAX_ARRAY_WORK - 1

    def array_atan_must_not_run(*_):
        raise AssertionError("Array.atan2 ran before shared-work preflight")

    monkeypatch.setattr(array_arithmetic.np, "arctan2", array_atan_must_not_run)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        invoke_arithmetic(atan_array_translator, "Array.atan2", {"left": array, "right": array})
    assert atan_array_translator.steps == MAX_ARRAY_WORK - 1
    np.testing.assert_array_equal(array.data, [3, 4])
    assert array.data.flags.writeable  # Direct IR inputs are not implicitly copied.
    assert not wrap_array(np.array([3.0, 4.0])).data.flags.writeable


def test_array_atan2_and_hypot_keep_inputs_unchanged_and_reject_output_overflow(ee):
    left = ee.Array([[3, 4], [-3, 0]])
    right = ee.Array([[4, 3], [-4, 0]])
    for result in (left.atan2(right), left.hypot(right)):
        encoded_value = encoded(ee, result)
        compile_expression(encoded_value, [], {})

    original_left = np.array([[3.0, 4.0], [-3.0, 0.0]])
    original_right = np.array([[4.0, 3.0], [-4.0, 0.0]])
    left_value, right_value = wrap_array(original_left), wrap_array(original_right)
    left_before, right_before = left_value.data.copy(), right_value.data.copy()
    result = invoke_arithmetic(Translator([], {}, None), "Array.hypot", {
        "left": left_value, "right": right_value,
    })
    np.testing.assert_array_equal(left_value.data, left_before)
    np.testing.assert_array_equal(right_value.data, right_before)
    assert not left_value.data.flags.writeable and not right_value.data.flags.writeable
    assert not result.data.flags.writeable
    assert result.data.dtype == np.dtype(np.float64)
    with pytest.raises(UnsupportedEEError):
        compile_expression(encoded(ee, ee.Array([1.7e308]).hypot([1.7e308])), [], {})


def test_image_hypot_rejects_bad_arguments_float64_and_real_over_budget_graph(ee, local):
    for arguments in ({}, {"image1": 1}, {"image1": 1, "image2": 2, "extra": 0},
                      {"input": 1, "right": 2}):
        with pytest.raises(UnsupportedEEError):
            compile_expression(invocation("Image.hypot", arguments), [], {})

    with pytest.raises(UnsupportedEEError, match="Float32 range"):
        compile_expression(encoded(ee, ee.Image.constant(3.4e38).hypot(
            ee.Image.constant(3.4e38))), [], {})

    # Float64 callbacks are outside the current pixel-kernel contract; callers
    # can explicitly narrow before entering hypot's Float32 output path.
    image = ee.Image("vector-scene").select("x").toDouble()
    with pytest.raises(UnsupportedEEError):
        compile_expression(encoded(ee, image.hypot(ee.Image.constant(4))), *local)
    narrowed = image.toFloat().hypot(ee.Image.constant(4))
    assert compile_expression(encoded(ee, narrowed), *local)["kind"] == "image"

    # Independent shallow chains exceed the unchanged 500-node graph guard
    # without approaching the decoder's nesting limit.
    base = ee.Image("vector-scene").select("x")
    branches = []
    for index in range(12):
        branch = base
        for _ in range(4):
            branch = branch.hypot(ee.Image.constant(index + 1))
        branches.append(branch.rename(f"h{index}"))
    chain = ee.Image.cat(*branches)
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compile_expression(encoded(ee, chain), *local)


def test_image_atan2_stays_unsupported_until_the_pixel_kernel_exists(ee, local):
    expression = encoded(ee, ee.Image("vector-scene").select("x").atan2(2))
    assert any(
        node.get("functionName") == "Image.atan2"
        for _, node in expression.get("scope", [])
        if isinstance(node, dict)
    )
    with pytest.raises(UnsupportedEEError):
        compile_expression(expression, *local)

    assert "arctan2" not in SUPPORTED
    with pytest.raises(ValueError, match="不支持的算子"):
        validate({"angle": {"process_id": "arctan2", "arguments": {
            "x": {"from_parameter": "x"}, "y": {"from_parameter": "y"},
        }, "result": True}})
