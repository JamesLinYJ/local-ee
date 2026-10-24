"""Exact pinned API names, consumable raster outputs and empty-map contracts."""
from pathlib import Path

import numpy as np
import pytest

from ee_float64_graph_reference import evaluate_float64_graph
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_map_preflight import preflight_empty_feature_map
from gee.compat.earthengine.ir import Function, UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "Image.unmix", "Image.rgbToHsv", "Image.hsvToRgb", "Image.interpolate",
    "Image.polynomial", "Image.regexpRename", "Image.slice", "Image.cat",
    "Image.float", "Image.double", "Image.id", "Image.metadata",
    "Image.arrayDimensions", "Image.arrayDotProduct", "Image.arrayPad",
)


@pytest.fixture
def sdk():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert ee.__version__ == "1.7.49"
        yield ee
    assert guard.evidence()["attempt_count"] == 0


def cases(ee):
    image = ee.Image("scene-a")
    pair = image.select(["red", "nir"]).toDouble()
    rgb = image.select(["red", "green", "blue"]).toDouble()
    array = pair.toArray()
    return {
        "Image.unmix": (
            {"image": pair, "endmembers": [[1, 0], [0, 1]],
             "sumToOne": False, "nonNegative": False}, None,
        ),
        "Image.rgbToHsv": ({"image": rgb}, [7 / 12, 2 / 3, 0.75]),
        "Image.hsvToRgb": ({"image": rgb}, [0.5625, 0.75, 0.375]),
        "Image.interpolate": (
            {"image": pair, "x": [0, 1], "y": [1, 3], "behavior": "clamp"}, [1.5],
        ),
        "Image.polynomial": ({"image": pair, "coefficients": [1, 2, 3]}, [1.6875, 10.75]),
        "Image.regexpRename": (
            {"input": pair, "regex": "^red$", "replacement": "R", "all": True}, [0.25, 1.5],
        ),
        "Image.slice": ({"image": pair, "start": 0, "end": 1}, [0.25]),
        "Image.cat": ({"images": [image.select("red"), image.select("nir")]}, [0.25, 1.5]),
        "Image.float": ({"value": pair}, [0.25, 1.5]),
        "Image.double": ({"value": pair}, [0.25, 1.5]),
        "Image.id": ({"element": image}, "scene-a"),
        "Image.metadata": ({"image": image, "property": "cloud", "name": "cloud"}, [10.0]),
        "Image.arrayDimensions": ({"input": array}, [1.0]),
        "Image.arrayDotProduct": ({"image1": array, "image2": array}, [2.3125]),
        "Image.arrayPad": ({"image": array, "lengths": [3], "pad": 0}, [0.0]),
    }


def invocations(value):
    if type(value) is dict:
        if value.get("type") == "Invocation":
            yield value.get("functionName")
        for child in value.values():
            yield from invocations(child)
    elif type(value) in (list, tuple):
        for child in value:
            yield from invocations(child)


@pytest.mark.parametrize("name", NAMES)
def test_exact_sdk_entry_compiles_and_has_a_consumable_result(sdk, name):
    arguments, expected = cases(sdk)[name]
    # lookup.apply avoids call_'s own `name` parameter colliding with the
    # Image.metadata output-name keyword. Aliases remain exact wire names.
    expression = sdk.ApiFunction.lookup(name).apply(arguments)
    if name == "Image.arrayPad":
        # Typed arrays require an explicit scalar consumer at the existing
        # raster export boundary; merely advertising an array is insufficient.
        expression = sdk.Image(expression).arrayGet([2])
    encoded = sdk.serializer.encode(expression, for_cloud_api=False)
    assert name in set(invocations(encoded))
    metadata, items, _options = synthetic_inputs()
    result = compile_expression(encoded, [metadata], items)
    if name == "Image.id":
        assert result["kind"] == "value" and result["value"] == expected
        return
    validate(result["process_graph"])
    if name == "Image.unmix":
        # Actual native values are checked by the separate trusted GeoTrellis
        # probe/workflow. Do not substitute a Python solver for this producer.
        assert sum(node["process_id"] == "local_ee_unmix"
                   for node in result["process_graph"].values()) == 1
        assert result["bands"] == ["unmix_0", "unmix_1"]
        return
    samples = {"scene-a": {
        "red": np.array([0.25]), "nir": np.array([1.5]),
        "green": np.array([0.5]), "blue": np.array([0.75]), "SCL": np.array([1.0]),
    }}
    actual, names, timed = evaluate_float64_graph(result, samples, grid=[[100.5, 30.5]])
    assert names == result["bands"] and not timed
    np.testing.assert_allclose(actual, np.asarray(expected)[:, None], rtol=0, atol=1e-14)


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("problem", ["missing", "unknown"])
def test_empty_map_checks_new_signatures_without_evaluating_a_row(sdk, name, problem, monkeypatch):
    arguments, _expected = cases(sdk)[name]
    encoded = sdk.serializer.encode(
        sdk.ApiFunction.lookup(name).apply(arguments), for_cloud_api=False,
    )
    # Signature validation is independent of the absent row's value/type.
    # Use literal placeholders so this focused check does not fetch data or
    # depend on some unrelated callback operator's contract.
    keys = {} if problem == "missing" else {key: None for key in arguments}
    if problem == "unknown":
        keys["unexpected"] = True
    body = {"type": "Invocation", "functionName": name, "arguments": keys}
    assert name in set(invocations(encoded))
    translator = Translator([], {}, {})
    monkeypatch.setattr(translator, "evaluate", lambda *_args: pytest.fail("invented a row"))
    message = "missing required" if problem == "missing" else "Unsupported algorithm arguments"
    with pytest.raises(UnsupportedEEError, match=message):
        preflight_empty_feature_map(translator, Function(["row"], body, {}))
