"""Bounded weighted Kernel constructors and focus-aligned transforms."""
import json
import math
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.kernel_values import (
    KERNEL_FUNCTIONS,
    KernelSpec,
    invoke_kernel,
)
from gee.ee_python_client import configure_local_ee


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def _kernel(name, arguments, translator=None):
    return invoke_kernel(translator or Translator([], {}, None), name, arguments)


def _evaluate(ee, expression):
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    return Translator([], {}, None).evaluate(encoded)


def test_pinned_signatures_and_sdk_routes_constructors_and_methods(ee):
    metadata = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())
    definitions = {
        item["name"].removeprefix("algorithms/"): item
        for item in metadata["algorithms"]
        if item["name"].removeprefix("algorithms/") in KERNEL_FUNCTIONS
    }
    assert set(definitions) == KERNEL_FUNCTIONS
    expressions = [
        ee.Kernel.gaussian(3),
        ee.Kernel.laplacian4(),
        ee.Kernel.laplacian8(),
        ee.Kernel.sobel(),
        ee.Kernel.prewitt(),
        ee.Kernel.roberts(),
        ee.Kernel.sobel().rotate(1),
        ee.Kernel.square(1, normalize=False).add(
            ee.Kernel.fixed(weights=[[1]], x=0, y=0), normalize=False,
        ),
    ]
    for expression in expressions:
        assert type(_evaluate(ee, expression)) is KernelSpec
    gaussian = definitions["Kernel.gaussian"]
    defaults = {arg["argumentName"]: arg.get("defaultValue")
                for arg in gaussian["arguments"] if arg.get("optional")}
    assert defaults == {
        "sigma": 1.0, "units": "pixels", "normalize": True, "magnitude": 1.0,
    }
    for name in ("Kernel.laplacian4", "Kernel.laplacian8", "Kernel.sobel",
                 "Kernel.prewitt", "Kernel.roberts"):
        defaults = {arg["argumentName"]: arg.get("defaultValue")
                    for arg in definitions[name]["arguments"] if arg.get("optional")}
        assert defaults == {"magnitude": 1.0, "normalize": False}
    assert [arg["argumentName"] for arg in definitions["Kernel.rotate"]["arguments"]] == [
        "kernel", "rotations",
    ]
    assert [arg["argumentName"] for arg in definitions["Kernel.add"]["arguments"]] == [
        "kernel1", "kernel2", "normalize",
    ]


def test_gaussian_radius_includes_boundary_samples_and_normalizes():
    kernel = _kernel("Kernel.gaussian", {"radius": 1})
    assert (kernel.width, kernel.height, kernel.x, kernel.y) == (3, 3, 1, 1)
    raw = [[math.exp(-0.5 * (x * x + y * y))
            for x in (-1, 0, 1)] for y in (-1, 0, 1)]
    total = math.fsum(value for row in raw for value in row)
    for actual_row, raw_row in zip(kernel.weights, raw):
        assert actual_row == pytest.approx([value / total for value in raw_row])
    assert math.fsum(value for row in kernel.weights for value in row) == pytest.approx(1.0)

    fractional = _kernel("Kernel.gaussian", {"radius": 1.5})
    assert (fractional.width, fractional.height, fractional.x, fractional.y) == (5, 5, 2, 2)
    assert all(value == 0.0 for row in fractional.weights for value in (row[0], row[-1]))
    assert all(fractional.weights[0][x] == 0.0 for x in range(5))
    assert fractional.weights[2][2] > 0.0


def test_gaussian_sigma_magnitude_and_extreme_finite_inputs_are_stable():
    raw = _kernel("Kernel.gaussian", {
        "radius": 1, "sigma": 1, "normalize": False, "magnitude": 3,
    })
    peak = 3 / (2 * math.pi)
    assert raw.weights[1][1] == pytest.approx(peak)
    assert raw.weights[1][2] == pytest.approx(peak * math.exp(-0.5))
    tiny_sigma = _kernel("Kernel.gaussian", {"radius": 3, "sigma": 5e-324})
    assert (tiny_sigma.width, tiny_sigma.height, tiny_sigma.x, tiny_sigma.y) == (7, 7, 3, 3)
    assert tiny_sigma.weights[3][3] == 1.0
    assert sum(value != 0.0 for row in tiny_sigma.weights for value in row) == 1
    broad = _kernel("Kernel.gaussian", {"radius": 3, "sigma": 1e308})
    assert all(math.isfinite(value) for row in broad.weights for value in row)
    assert all(value == pytest.approx(1 / 49) for row in broad.weights for value in row)
    huge = _kernel("Kernel.fixed", {
        "weights": [[1e308, 1e308]], "normalize": True,
    })
    assert huge.weights == ((0.5, 0.5),)
    scaled = _kernel("Kernel.gaussian", {
        "radius": 3, "sigma": 1, "magnitude": 1e308,
    })
    assert all(math.isfinite(value) for row in scaled.weights for value in row)
    raw = [[math.exp(-0.5 * (x * x + y * y)) for x in range(-3, 4)]
           for y in range(-3, 4)]
    total = math.fsum(value for row in raw for value in row)
    assert scaled.weights[3][3] == pytest.approx(1e308 / total)

    # Log-domain scaling lets a tiny magnitude rescue an otherwise overflowing
    # continuous-density prefactor without evaluating sigma squared as zero.
    rescued = _kernel("Kernel.gaussian", {
        "radius": 1, "sigma": 1e-200, "normalize": False, "magnitude": 1e-100,
    })
    expected_log = -math.log(2 * math.pi) - 2 * math.log(1e-200) + math.log(1e-100)
    assert rescued.weights[1][1] == pytest.approx(math.exp(expected_log))
    underflowed = _kernel("Kernel.gaussian", {
        "radius": 1, "sigma": 1e200, "normalize": False,
    })
    assert underflowed.weights == ((0.0, 0.0, 0.0),) * 3
    with pytest.raises(UnsupportedEEError, match="density weight exceeds"):
        _kernel("Kernel.gaussian", {
            "radius": 1, "sigma": 5e-324, "normalize": False,
        })


@pytest.mark.parametrize("name,weights,focus", [
    ("Kernel.laplacian4", ((0, 1, 0), (1, -4, 1), (0, 1, 0)), (1, 1)),
    ("Kernel.laplacian8", ((1, 1, 1), (1, -8, 1), (1, 1, 1)), (1, 1)),
    ("Kernel.sobel", ((-1, 0, 1), (-2, 0, 2), (-1, 0, 1)), (1, 1)),
    ("Kernel.prewitt", ((1, 0, -1), (1, 0, -1), (1, 0, -1)), (1, 1)),
    ("Kernel.roberts", ((1, 0), (0, -1)), (1, 1)),
])
def test_edge_coefficients_focus_and_magnitude(name, weights, focus):
    kernel = _kernel(name, {})
    assert kernel.weights == tuple(tuple(float(value) for value in row) for row in weights)
    assert (kernel.x, kernel.y) == focus
    scaled = _kernel(name, {"magnitude": 2})
    assert scaled.weights == tuple(tuple(float(2 * value) for value in row) for row in weights)


@pytest.mark.parametrize("name", [
    "Kernel.laplacian4", "Kernel.laplacian8", "Kernel.sobel",
    "Kernel.prewitt", "Kernel.roberts",
])
def test_signed_normalization_is_rejected_when_official_sources_conflict(name):
    with pytest.raises(UnsupportedEEError, match="official method pages say sum to 1"):
        _kernel(name, {"normalize": True})


def test_fixed_signed_normalization_is_rejected_by_the_shared_policy():
    with pytest.raises(UnsupportedEEError, match="negative coefficients"):
        _kernel("Kernel.fixed", {
            "weights": [[1.0, -0.5]], "normalize": True,
        })


@pytest.mark.parametrize("name,args", [
    ("Kernel.gaussian", {}),
    ("Kernel.gaussian", {"radius": -1}),
    ("Kernel.gaussian", {"radius": 1, "sigma": 0}),
    ("Kernel.gaussian", {"radius": 1, "sigma": -1}),
    ("Kernel.gaussian", {"radius": 1, "sigma": float("inf")}),
    ("Kernel.gaussian", {"radius": 1, "sigma": True}),
    ("Kernel.gaussian", {"radius": 1, "units": "meters"}),
    ("Kernel.gaussian", {"radius": 1, "extra": 2}),
    ("Kernel.sobel", {"magnitude": float("nan")}),
    ("Kernel.prewitt", {"normalize": 1}),
    ("Kernel.roberts", {"extra": True}),
])
def test_weighted_constructor_rejects_invalid_inputs(name, args):
    with pytest.raises(UnsupportedEEError):
        _kernel(name, args)


def test_gaussian_and_rotation_work_are_precharged_before_output():
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="33 by 33"):
        invoke_kernel(translator, "Kernel.gaussian", {"radius": 18})
    assert translator.steps == 8  # dispatch and bounded unit-string validation only

    small = _kernel("Kernel.fixed", {"weights": [[1.0]]})
    bounded = Translator([], {}, None)
    bounded.steps = 49_990
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_kernel(bounded, "Kernel.rotate", {"kernel": small, "rotations": 1})
    assert bounded.steps == 49_998


def test_rotate_handles_asymmetric_noncentral_focus_and_composition():
    source = _kernel("Kernel.fixed", {
        "weights": [[1, 2, 3], [4, 5, 6]], "x": 0, "y": 1,
    })
    clockwise = _kernel("Kernel.rotate", {"kernel": source, "rotations": 1})
    assert clockwise.weights == ((4.0, 1.0), (5.0, 2.0), (6.0, 3.0))
    assert (clockwise.width, clockwise.height, clockwise.x, clockwise.y) == (2, 3, 0, 0)
    counterclockwise = _kernel("Kernel.rotate", {"kernel": source, "rotations": -1})
    assert counterclockwise.weights == ((3.0, 6.0), (2.0, 5.0), (1.0, 4.0))
    assert (counterclockwise.x, counterclockwise.y) == (1, 2)
    composed = _kernel("Kernel.rotate", {"kernel": clockwise, "rotations": 3})
    assert composed == source
    assert composed is not source and composed.weights is not source.weights
    assert _kernel("Kernel.rotate", {"kernel": source, "rotations": 5}) == clockwise
    with pytest.raises(UnsupportedEEError):
        _kernel("Kernel.rotate", {"kernel": source, "rotations": True})


def test_add_aligns_focus_and_returns_an_owned_matrix():
    first = _kernel("Kernel.fixed", {
        "weights": [[1, 2, 3], [4, 5, 6]], "x": 0, "y": 1,
    })
    second = _kernel("Kernel.fixed", {
        "weights": [[10, 20], [30, 40], [50, 60]], "x": 1, "y": 1,
    })
    result = _kernel("Kernel.add", {"kernel1": first, "kernel2": second})
    assert result.weights == ((10.0, 21.0, 2.0, 3.0),
                              (30.0, 44.0, 5.0, 6.0),
                              (50.0, 60.0, 0.0, 0.0))
    assert (result.width, result.height, result.x, result.y) == (4, 3, 1, 1)
    assert result is not first and result.weights is not first.weights
    assert all(out_row is not in_row for out_row in result.weights for in_row in first.weights)


def test_add_normalization_cancellation_overflow_and_bounds():
    positive = _kernel("Kernel.fixed", {"weights": [[1, 1]], "x": 0, "y": 0})
    one = _kernel("Kernel.fixed", {"weights": [[1]], "x": 0, "y": 0})
    normalized = _kernel("Kernel.add", {
        "kernel1": positive, "kernel2": one, "normalize": True,
    })
    assert normalized.weights == ((2 / 3, 1 / 3),)

    large = _kernel("Kernel.fixed", {"weights": [[1e308]], "x": 0, "y": 0})
    negative = _kernel("Kernel.fixed", {"weights": [[-1e308]], "x": 0, "y": 0})
    canceled = _kernel("Kernel.add", {"kernel1": large, "kernel2": negative})
    assert canceled.weights == ((0.0,),)
    with pytest.raises(UnsupportedEEError, match="signed weights"):
        _kernel("Kernel.add", {"kernel1": positive, "kernel2": negative, "normalize": True})
    with pytest.raises(UnsupportedEEError, match="finite Float64"):
        _kernel("Kernel.add", {"kernel1": large, "kernel2": large})

    wide_left = _kernel("Kernel.fixed", {"weights": [[1] * 33], "x": 0, "y": 0})
    wide_right = _kernel("Kernel.fixed", {"weights": [[1] * 33], "x": 32, "y": 0})
    with pytest.raises(UnsupportedEEError, match="33 by 33"):
        _kernel("Kernel.add", {"kernel1": wide_left, "kernel2": wide_right})


def test_add_work_is_charged_before_aligned_output_allocation():
    first = _kernel("Kernel.fixed", {"weights": [[1.0]]})
    translator = Translator([], {}, None)
    translator.steps = 49_980
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_kernel(translator, "Kernel.add", {"kernel1": first, "kernel2": first})
    assert translator.steps == 49_995
