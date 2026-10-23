"""Pinned SDK invocation shapes and independent bounded Kernel matrices."""
import json
from pathlib import Path

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.kernel_values import (
    KERNEL_FUNCTIONS,
    KernelSpec,
    invoke_kernel,
    validate_kernel,
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


def _sdk_call(ee, expression, translator=None):
    encoded = ee.serializer.encode(expression, for_cloud_api=False)
    if encoded["type"] == "CompoundValue":
        scope = dict(encoded["scope"])
        if translator is not None:
            translator.scope.update(scope)
        encoded = encoded["value"]
        while encoded["type"] == "ValueRef":
            encoded = scope[encoded["value"]]
    assert encoded["type"] == "Invocation"
    arguments = encoded["arguments"]
    if translator is not None:
        arguments = {key: translator.evaluate(value)
                     for key, value in arguments.items()}
    return encoded["functionName"], arguments


def _kernel(name, arguments, translator=None):
    return invoke_kernel(translator or Translator([], {}, None), name, arguments)


def _mask(kernel):
    return tuple(tuple(value != 0.0 for value in row) for row in kernel.weights)


def test_pinned_algorithm_signatures_and_official_sdk_invocations_match(ee):
    metadata = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())
    definitions = {
        item["name"].removeprefix("algorithms/"): item
        for item in metadata["algorithms"]
        if item["name"].removeprefix("algorithms/") in KERNEL_FUNCTIONS
    }
    assert set(definitions) == KERNEL_FUNCTIONS
    expressions = [
        ee.Kernel.fixed(weights=[[1, 2], [3, 4]]),
        ee.Kernel.circle(3),
        ee.Kernel.square(1, normalize=False),
        ee.Kernel.rectangle(2, 1),
        ee.Kernel.plus(1),
        ee.Kernel.cross(1),
        ee.Kernel.diamond(1),
        ee.Kernel.octagon(3),
    ]
    for expression in expressions:
        translator = Translator([], {}, None)
        name, arguments = _sdk_call(ee, expression, translator)
        assert name in KERNEL_FUNCTIONS
        spec = invoke_kernel(translator, name, arguments)
        assert type(spec) is KernelSpec
        assert 1 <= spec.width <= 33 and 1 <= spec.height <= 33
        metadata_args = {
            item["argumentName"]: item for item in definitions[name]["arguments"]
        }
        assert set(arguments) <= set(metadata_args)
    assert definitions["Kernel.fixed"]["arguments"][0]["defaultValue"] == -1.0
    assert definitions["Kernel.fixed"]["arguments"][1]["defaultValue"] == -1.0
    assert definitions["Kernel.fixed"]["arguments"][3]["defaultValue"] == -1.0
    assert definitions["Kernel.fixed"]["arguments"][4]["defaultValue"] == -1.0
    assert definitions["Kernel.fixed"]["arguments"][5]["defaultValue"] is False
    for name in KERNEL_FUNCTIONS - {"Kernel.fixed"}:
        defaults = {arg["argumentName"]: arg.get("defaultValue")
                    for arg in definitions[name]["arguments"] if arg.get("optional")}
        assert defaults == {"units": "pixels", "normalize": True, "magnitude": 1.0}


def test_focal_default_radius_is_present_in_the_pinned_sdk_serialization(ee):
    name, arguments = _sdk_call(ee, ee.Image.constant(1).focalMean())
    assert name == "Image.focalMean"
    assert set(arguments) == {"image"}
    metadata = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())
    signature = next(item for item in metadata["algorithms"]
                     if item["name"] == "algorithms/Image.focalMean")
    defaults = {arg["argumentName"]: arg.get("defaultValue")
                for arg in signature["arguments"]}
    assert defaults["radius"] == 1.5
    assert defaults["kernelType"] == "circle"
    assert defaults["units"] == "pixels"


def test_shape_masks_match_published_radius_three_examples():
    circle = _kernel("Kernel.circle", {"radius": 3, "normalize": False})
    assert _mask(circle) == (
        (0, 0, 0, 1, 0, 0, 0),
        (0, 1, 1, 1, 1, 1, 0),
        (0, 1, 1, 1, 1, 1, 0),
        (1, 1, 1, 1, 1, 1, 1),
        (0, 1, 1, 1, 1, 1, 0),
        (0, 1, 1, 1, 1, 1, 0),
        (0, 0, 0, 1, 0, 0, 0),
    )
    assert sum(map(sum, _mask(circle))) == 29
    assert sum(map(sum, _mask(_kernel("Kernel.diamond", {
        "radius": 3, "normalize": False,
    })))) == 25
    assert _mask(_kernel("Kernel.plus", {"radius": 3, "normalize": False})) == (
        (0, 0, 0, 1, 0, 0, 0),
        (0, 0, 0, 1, 0, 0, 0),
        (0, 0, 0, 1, 0, 0, 0),
        (1, 1, 1, 1, 1, 1, 1),
        (0, 0, 0, 1, 0, 0, 0),
        (0, 0, 0, 1, 0, 0, 0),
        (0, 0, 0, 1, 0, 0, 0),
    )
    assert _mask(_kernel("Kernel.cross", {"radius": 3, "normalize": False})) == (
        (1, 0, 0, 0, 0, 0, 1),
        (0, 1, 0, 0, 0, 1, 0),
        (0, 0, 1, 0, 1, 0, 0),
        (0, 0, 0, 1, 0, 0, 0),
        (0, 0, 1, 0, 1, 0, 0),
        (0, 1, 0, 0, 0, 1, 0),
        (1, 0, 0, 0, 0, 0, 1),
    )
    assert _mask(_kernel("Kernel.octagon", {"radius": 3, "normalize": False})) == (
        (0, 0, 1, 1, 1, 0, 0),
        (0, 1, 1, 1, 1, 1, 0),
        (1, 1, 1, 1, 1, 1, 1),
        (1, 1, 1, 1, 1, 1, 1),
        (1, 1, 1, 1, 1, 1, 1),
        (0, 1, 1, 1, 1, 1, 0),
        (0, 0, 1, 1, 1, 0, 0),
    )


def test_fixed_infers_shape_and_center_focus_normalizes_signed_weights():
    source = [[1, 1], [1, 1]]
    kernel = _kernel("Kernel.fixed", {"weights": source, "normalize": True})
    source[0][0] = 100
    assert kernel.width == kernel.height == 2
    assert (kernel.x, kernel.y) == (1, 1)
    assert kernel.weights == ((0.25, 0.25), (0.25, 0.25))
    signed = _kernel("Kernel.fixed", {"weights": [[-2, 1]], "x": 0})
    assert signed.weights == ((-2.0, 1.0),)
    assert (signed.x, signed.y) == (0, 0)
    assert _kernel("Kernel.fixed", {
        "weights": [[1, 1], [1, 1]], "normalize": True,
    }).weights == ((0.25, 0.25), (0.25, 0.25))


def test_fractional_radii_and_independent_rectangular_axes():
    circle = _kernel("Kernel.circle", {"radius": 1.5})
    assert (circle.width, circle.height, circle.x, circle.y) == (5, 5, 2, 2)
    assert _mask(circle) == (
        (0, 0, 0, 0, 0),
        (0, 1, 1, 1, 0),
        (0, 1, 1, 1, 0),
        (0, 1, 1, 1, 0),
        (0, 0, 0, 0, 0),
    )
    rectangle = _kernel("Kernel.rectangle", {
        "xRadius": 0.5, "yRadius": 1.5, "normalize": False,
    })
    assert (rectangle.width, rectangle.height, rectangle.x, rectangle.y) == (3, 5, 1, 2)
    assert _mask(rectangle) == (
        (0, 0, 0), (0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 0, 0),
    )
    assert all(value == pytest.approx(1 / 9) for row in circle.weights for value in row if value)


def test_normalization_magnitude_and_fixed_dimension_focus_arguments():
    shape = _kernel("Kernel.square", {
        "radius": 1, "magnitude": 2,
    })
    assert all(value == pytest.approx(2 / 9) for row in shape.weights for value in row)
    fixed = _kernel("Kernel.fixed", {
        "width": 3, "height": 2, "weights": [[1, 2, 3], [4, 5, 6]],
        "x": 0, "y": 1,
    })
    assert (fixed.width, fixed.height, fixed.x, fixed.y) == (3, 2, 0, 1)
    assert fixed.weights == ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0))
    negative = _kernel("Kernel.circle", {
        "radius": 0, "magnitude": -3, "normalize": False,
    })
    assert negative.weights == ((-3.0,),)


@pytest.mark.parametrize("name,args", [
    ("Kernel.fixed", {"weights": []}),
    ("Kernel.fixed", {"weights": [[1], [1, 2]]}),
    ("Kernel.fixed", {"weights": [[1, 2]], "width": 3}),
    ("Kernel.fixed", {"weights": [[True]]}),
    ("Kernel.fixed", {"weights": [[2**53 + 1]]}),
    ("Kernel.fixed", {"weights": [[float("inf")]]}),
    ("Kernel.fixed", {"weights": [[1, -1]], "normalize": True}),
    ("Kernel.fixed", {"weights": [[1]], "x": -2}),
    ("Kernel.fixed", {"weights": [[1]], "extra": 1}),
    ("Kernel.circle", {"radius": -1}),
    ("Kernel.square", {"radius": 17}),
    ("Kernel.circle", {"radius": 1, "units": "meters"}),
    ("Kernel.circle", {"radius": 1, "units": "pixel"}),
    ("Kernel.rectangle", {"xRadius": 1}),
    ("Kernel.circle", {"radius": True}),
    ("Kernel.circle", {"radius": 1, "normalize": 1}),
    ("Kernel.circle", {"radius": 1, "magnitude": float("nan")}),
])
def test_malformed_or_unsupported_constructor_inputs_fail(name, args):
    with pytest.raises(UnsupportedEEError):
        _kernel(name, args)


def test_maximum_fixed_kernel_is_accepted_and_dimensions_are_bounded():
    values = [[1] * 33 for _ in range(33)]
    spec = _kernel("Kernel.fixed", {"weights": values})
    assert (spec.width, spec.height, spec.x, spec.y) == (33, 33, 16, 16)
    with pytest.raises(UnsupportedEEError, match="33"):
        _kernel("Kernel.fixed", {"weights": [[1] * 34]})


def test_kernel_validation_requires_exact_frozen_owned_finite_structure():
    source = _kernel("Kernel.cross", {"radius": 1, "normalize": False})
    snapshot = validate_kernel(Translator([], {}, None), source)
    assert snapshot == source and snapshot is not source
    assert snapshot.weights is not source.weights
    with pytest.raises(UnsupportedEEError, match="exact frozen"):
        validate_kernel(Translator([], {}, None), object())
    object.__setattr__(source, "weights", ((1.0,), [2.0]))
    with pytest.raises(UnsupportedEEError, match="exact tuples"):
        validate_kernel(Translator([], {}, None), source)
    object.__setattr__(source, "weights", ((float("nan"),),))
    object.__setattr__(source, "x", 0)
    object.__setattr__(source, "y", 0)
    with pytest.raises(UnsupportedEEError, match="finite floats"):
        validate_kernel(Translator([], {}, None), source)


def test_kernel_work_is_reserved_before_weight_and_output_scans():
    translator = Translator([], {}, None)
    translator.steps = 49_984
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_kernel(translator, "Kernel.fixed", {"weights": [[1] * 4 for _ in range(4)]})
    assert translator.steps == 49_994  # dispatch + row scan reserved, cell scan refused
    at_limit = Translator([], {}, None)
    at_limit.steps = 50_000 - (1 + 1 + 1 + 2 + 2)
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_kernel(at_limit, "Kernel.circle", {"radius": 1})


def test_kernel_revalidation_charges_before_copying_weight_rows():
    kernel = _kernel("Kernel.square", {"radius": 1, "normalize": False})
    translator = Translator([], {}, None)
    translator.steps = 49_950
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        validate_kernel(translator, kernel)
    assert translator.steps == 49_956  # the bounded row-shape scan was reserved
