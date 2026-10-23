"""Pinned SDK signatures and bounded distance/edge Kernel semantics."""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.kernel_values import (
    KERNEL_FUNCTIONS,
    KernelSpec,
    invoke_kernel,
)
from gee.convolve_spec import decode_convolve_spec
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
NEW_KERNELS = {
    "Kernel.euclidean", "Kernel.manhattan", "Kernel.chebyshev",
    "Kernel.compass", "Kernel.kirsch", "Kernel.inverse",
}


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


def _mask(kernel):
    return tuple(tuple(value != 0.0 for value in row) for row in kernel.weights)


def test_pinned_signatures_sdk_routes_and_omitted_null_defaults(ee):
    metadata = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())
    definitions = {
        item["name"].removeprefix("algorithms/"): item
        for item in metadata["algorithms"]
        if item["name"].removeprefix("algorithms/") in KERNEL_FUNCTIONS
    }
    assert NEW_KERNELS <= set(definitions)
    signatures = {
        "Kernel.euclidean": ("radius", "units", "normalize", "magnitude"),
        "Kernel.manhattan": ("radius", "units", "normalize", "magnitude"),
        "Kernel.chebyshev": ("radius", "units", "normalize", "magnitude"),
        "Kernel.compass": ("magnitude", "normalize"),
        "Kernel.kirsch": ("magnitude", "normalize"),
        "Kernel.inverse": ("kernel",),
    }
    defaults = {
        "Kernel.euclidean": {"units": "pixels", "normalize": False, "magnitude": 1.0},
        "Kernel.manhattan": {"units": "pixels", "normalize": False, "magnitude": 1.0},
        "Kernel.chebyshev": {"units": "pixels", "normalize": False, "magnitude": 1.0},
        "Kernel.compass": {"magnitude": 1.0, "normalize": False},
        "Kernel.kirsch": {"magnitude": 1.0, "normalize": False},
    }
    required = {
        "Kernel.euclidean": ("radius",),
        "Kernel.manhattan": ("radius",),
        "Kernel.chebyshev": ("radius",),
        "Kernel.compass": (),
        "Kernel.kirsch": (),
        "Kernel.inverse": ("kernel",),
    }
    for name, arguments in signatures.items():
        definition = definitions[name]
        assert tuple(arg["argumentName"] for arg in definition["arguments"]) == arguments
        assert tuple(
            arg["argumentName"] for arg in definition["arguments"]
            if not arg.get("optional")
        ) == required[name]
        if name in defaults:
            actual = {
                arg["argumentName"]: arg.get("defaultValue")
                for arg in definition["arguments"] if arg.get("optional")
            }
            assert actual == defaults[name]

    expressions = [
        ee.Kernel.euclidean(2),
        ee.Kernel.manhattan(2),
        ee.Kernel.chebyshev(2),
        ee.Kernel.compass(),
        ee.Kernel.kirsch(),
        ee.Kernel.sobel().inverse(),
    ]
    for expression in expressions:
        assert type(_evaluate(ee, expression)) is KernelSpec

    null_options = ee.serializer.encode(
        ee.Kernel.euclidean(2, units=None, normalize=None, magnitude=None),
        for_cloud_api=False,
    )
    assert null_options["arguments"] == {"radius": 2}


def test_distance_coefficient_matrices_match_official_radius_three_examples():
    euclidean = _kernel("Kernel.euclidean", {"radius": 3})
    expected_euclidean = (
        (4.242, 3.605, 3.162, 3.000, 3.162, 3.605, 4.242),
        (3.605, 2.828, 2.236, 2.000, 2.236, 2.828, 3.605),
        (3.162, 2.236, 1.414, 1.000, 1.414, 2.236, 3.162),
        (3.000, 2.000, 1.000, 0.000, 1.000, 2.000, 3.000),
        (3.162, 2.236, 1.414, 1.000, 1.414, 2.236, 3.162),
        (3.605, 2.828, 2.236, 2.000, 2.236, 2.828, 3.605),
        (4.242, 3.605, 3.162, 3.000, 3.162, 3.605, 4.242),
    )
    assert (euclidean.width, euclidean.height, euclidean.x, euclidean.y) == (7, 7, 3, 3)
    for row, expected in zip(euclidean.weights, expected_euclidean):
        assert row == pytest.approx(expected, rel=2e-4)

    manhattan = _kernel("Kernel.manhattan", {"radius": 3})
    expected_manhattan = (
        (6, 5, 4, 3, 4, 5, 6), (5, 4, 3, 2, 3, 4, 5),
        (4, 3, 2, 1, 2, 3, 4), (3, 2, 1, 0, 1, 2, 3),
        (4, 3, 2, 1, 2, 3, 4), (5, 4, 3, 2, 3, 4, 5),
        (6, 5, 4, 3, 4, 5, 6),
    )
    chebyshev = _kernel("Kernel.chebyshev", {"radius": 3})
    expected_chebyshev = (
        (3, 3, 3, 3, 3, 3, 3), (3, 2, 2, 2, 2, 2, 3),
        (3, 2, 1, 1, 1, 2, 3), (3, 2, 1, 0, 1, 2, 3),
        (3, 2, 1, 1, 1, 2, 3), (3, 2, 2, 2, 2, 2, 3),
        (3, 3, 3, 3, 3, 3, 3),
    )
    assert manhattan.weights == tuple(tuple(float(value) for value in row)
                                      for row in expected_manhattan)
    assert chebyshev.weights == tuple(tuple(float(value) for value in row)
                                      for row in expected_chebyshev)


@pytest.mark.parametrize("name,expected", [
    ("Kernel.compass", ((1, 1, -1), (1, -2, -1), (1, 1, -1))),
    ("Kernel.kirsch", ((5, -3, -3), (5, 0, -3), (5, -3, -3))),
])
def test_compass_edge_matrices_focus_and_magnitude(name, expected):
    kernel = _kernel(name, {})
    assert kernel.weights == tuple(tuple(float(value) for value in row)
                                   for row in expected)
    assert (kernel.x, kernel.y) == (1, 1)
    scaled = _kernel(name, {"magnitude": -2.0})
    assert scaled.weights == tuple(tuple(float(-2 * value) for value in row)
                                   for row in expected)
    with pytest.raises(UnsupportedEEError, match="official method pages say sum to 1"):
        _kernel(name, {"normalize": True})


def test_distance_normalization_magnitude_zero_and_fractional_radius_policy():
    normalized = _kernel("Kernel.manhattan", {
        "radius": 1, "normalize": True, "magnitude": 2.0,
    })
    raw = ((2, 1, 2), (1, 0, 1), (2, 1, 2))
    assert normalized.weights == tuple(tuple(value / 12 * 2 for value in row)
                                       for row in raw)
    assert math.fsum(value for row in normalized.weights for value in row) == pytest.approx(2.0)

    zero = _kernel("Kernel.euclidean", {"radius": 0})
    assert zero.weights == ((0.0,),)
    with pytest.raises(UnsupportedEEError, match="sum is zero"):
        _kernel("Kernel.euclidean", {"radius": 0, "normalize": True})

    fractional = _kernel("Kernel.euclidean", {"radius": 1.5})
    assert (fractional.width, fractional.height, fractional.x, fractional.y) == (5, 5, 2, 2)
    assert fractional.weights[0][0] == pytest.approx(math.hypot(2, 2))
    assert fractional.weights[2][4] == 2.0
    assert _mask(fractional)[0][0]  # Corners are distances, not radius-clipped support.


@pytest.mark.parametrize("name,arguments", [
    ("Kernel.euclidean", {}),
    ("Kernel.manhattan", {"radius": None}),
    ("Kernel.chebyshev", {"radius": -0.1}),
    ("Kernel.euclidean", {"radius": True}),
    ("Kernel.manhattan", {"radius": float("inf")}),
    ("Kernel.chebyshev", {"radius": 1, "units": "meters"}),
    ("Kernel.euclidean", {"radius": 1, "units": "pixel"}),
    ("Kernel.euclidean", {"radius": 1, "units": None}),
    ("Kernel.euclidean", {"radius": 1, "normalize": 1}),
    ("Kernel.euclidean", {"radius": 1, "normalize": None}),
    ("Kernel.euclidean", {"radius": 1, "magnitude": float("nan")}),
    ("Kernel.euclidean", {"radius": 1, "magnitude": None}),
    ("Kernel.euclidean", {"radius": 1, "other": 0}),
    ("Kernel.compass", {"normalize": 1}),
    ("Kernel.compass", {"normalize": None}),
    ("Kernel.kirsch", {"magnitude": True}),
    ("Kernel.kirsch", {"magnitude": None}),
])
def test_distance_and_compass_constructors_reject_invalid_inputs(name, arguments):
    with pytest.raises(UnsupportedEEError):
        _kernel(name, arguments)


def test_distance_kernel_dimensions_and_generation_work_budget():
    maximum = _kernel("Kernel.euclidean", {"radius": 16})
    assert (maximum.width, maximum.height, maximum.x, maximum.y) == (33, 33, 16, 16)
    assert len(maximum.weights) == 33 and sum(map(len, maximum.weights)) == 1089
    for arguments in ({"radius": 16.0001}, {"radius": 17}):
        with pytest.raises(UnsupportedEEError, match="33 by 33"):
            _kernel("Kernel.manhattan", arguments)

    rejected = Translator([], {}, None)
    rejected.steps = 49_980
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_kernel(rejected, "Kernel.euclidean", {"radius": 1})
    assert rejected.steps == 49_988  # Dispatch and units are charged; matrix not allocated.

    exact_limit = Translator([], {}, None)
    exact_limit.steps = 49_916
    invoke_kernel(exact_limit, "Kernel.chebyshev", {"radius": 1})
    assert exact_limit.steps == 50_000

    output_limit = Translator([], {}, None)
    output_limit.steps = 49_917
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_kernel(output_limit, "Kernel.chebyshev", {"radius": 1})
    assert output_limit.steps == 49_954  # Generation was charged; finish allocation was refused.


def test_inverse_reciprocals_zero_focus_ownership_and_float64_overflow():
    source = _kernel("Kernel.fixed", {
        "weights": [[2.0, 0.0, -4.0], [0.5, -0.0, 1.0]],
        "x": 0, "y": 1,
    })
    inverse = _kernel("Kernel.inverse", {"kernel": source})
    assert type(inverse) is KernelSpec
    assert inverse.weights == ((0.5, 0.0, -0.25), (2.0, -0.0, 1.0))
    assert (inverse.x, inverse.y) == (source.x, source.y)
    assert inverse is not source and inverse.weights is not source.weights
    assert all(out_row is not in_row for out_row in inverse.weights for in_row in source.weights)
    assert math.copysign(1.0, inverse.weights[1][1]) == -1.0

    largest = _kernel("Kernel.inverse", {
        "kernel": _kernel("Kernel.fixed", {"weights": [[float.fromhex("0x1.fffffffffffffp+1023")]]}),
    })
    assert 0.0 < largest.weights[0][0] < 1e-307
    smallest = float.fromhex("0x0.0000000000001p-1022")
    with pytest.raises(UnsupportedEEError, match="reciprocal exceeds the finite Float64"):
        _kernel("Kernel.inverse", {
            "kernel": _kernel("Kernel.fixed", {"weights": [[smallest]]}),
        })


def test_inverse_arguments_and_work_are_bounded():
    source = _kernel("Kernel.fixed", {"weights": [[2.0]]})
    for arguments in ({}, {"kernel": None}, {"kernel": source, "extra": 1}):
        with pytest.raises(UnsupportedEEError):
            _kernel("Kernel.inverse", arguments)

    exact_limit = Translator([], {}, None)
    exact_limit.steps = 49_987
    inverse = invoke_kernel(exact_limit, "Kernel.inverse", {"kernel": source})
    assert inverse.weights == ((0.5,),)
    assert exact_limit.steps == 50_000

    over_limit = Translator([], {}, None)
    over_limit.steps = 49_988
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_kernel(over_limit, "Kernel.inverse", {"kernel": source})
    assert over_limit.steps == 49_996


def test_distance_kernel_compiles_into_the_existing_convolve_consumer(ee):
    metadata, items, _ = synthetic_inputs()
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    kernel = ee.Kernel.euclidean(1)
    expression = ee.Image(image).convolve(kernel)
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    result = compile_expression(encoded, [metadata], items)
    nodes = [node for node in result["process_graph"].values()
             if node["process_id"] == "local_ee_convolve"]
    assert len(nodes) == 1

    decoded = decode_convolve_spec(nodes[0]["arguments"]["spec"])
    expected = []
    for y, row in enumerate(_kernel("Kernel.euclidean", {"radius": 1}).weights):
        for x, weight in enumerate(row):
            if weight != 0.0:
                expected.append([x - 1, y - 1, struct.pack(">d", weight).hex()])
    assert decoded["coefficients"] == expected
