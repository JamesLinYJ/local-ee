"""Harmonic amplitude through official EE objects and the local compiler."""
from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, shape

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples/20_GEE_python_harmonic_amplitude.py"
PHASE = {
    0: (Fraction(1), Fraction(0)),
    90: (Fraction(0), Fraction(1)),
    180: (Fraction(-1), Fraction(0)),
    270: (Fraction(0), Fraction(-1)),
}


def fixture():
    return json.loads((ROOT / "tests/fixtures/ee-harmonic-amplitude-v1.json").read_text())


def example_module():
    spec = importlib.util.spec_from_file_location("harmonic_amplitude_example", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def local_data(data):
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["bands"]}},
    }]
    items = [{
        "id": frame,
        "bbox": data["bbox"],
        "geometry": data["scene_geometry"],
        "properties": {
            "system:index": frame,
            "system:time_start": data["origin_millis"] + data["frame_days"][frame] * 86_400_000,
        },
    } for frame in data["frame_order"]]
    arrays = {
        frame: {
            band: np.asarray([
                np.nan if value is None else value
                for value in data["pixel_values_by_frame"][frame][band]
            ], dtype=np.float64)
            for band in data["bands"]
        }
        for frame in data["frame_order"]
    }
    return {
        "catalog": catalog,
        "items": {data["collection_id"]: items},
        "arrays": arrays,
        "geometries": {frame: data["scene_geometry"] for frame in data["frame_order"]},
        "grid": np.asarray(data["pixel_centers"], dtype=float),
    }


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, local):
    return compile_expression(encode(ee, value), local["catalog"], local["items"])


def find_invocations(value, function_name):
    found = []
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == function_name:
            found.append(value)
        for child in value.values():
            found.extend(find_invocations(child, function_name))
    elif isinstance(value, (list, tuple)):
        for child in value:
            found.extend(find_invocations(child, function_name))
    return found


def rational_fit(days, observations):
    rows = [[Fraction(1), *PHASE[day % 360]] for day in days]
    gram = [[sum(row[i] * row[j] for row in rows) for j in range(3)] for i in range(3)]
    rhs = [sum(row[i] * y for row, y in zip(rows, observations)) for i in range(3)]
    augmented = [gram[row] + [rhs[row]] for row in range(3)]
    for column in range(3):
        pivot = next(row for row in range(column, 3) if augmented[row][column])
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            multiplier = augmented[row][column]
            augmented[row] = [value - multiplier * pivot_value
                              for value, pivot_value in zip(augmented[row], augmented[column])]
    return [augmented[row][3] for row in range(3)]


def independent_reference(data):
    days = [data["frame_days"][frame] for frame in data["sorted_frame_order"]]
    count = len(data["pixel_centers"])
    coefficients = np.full((3, count), np.nan)
    amplitude = np.full((1, count), np.nan)
    intercept = np.full((1, count), np.nan)
    prediction = np.full((1, count), np.nan)
    geometry = shape(data["scene_geometry"])
    for pixel, point in enumerate(data["pixel_centers"]):
        if not geometry.covers(Point(*point)):
            continue
        raw = [data["pixel_values_by_frame"][frame]["ndvi"][pixel]
               for frame in data["sorted_frame_order"]]
        if any(value is None for value in raw):
            continue
        beta = rational_fit(days, [Fraction(str(value)) for value in raw])
        coefficients[:, pixel] = [float(value) for value in beta]
        amplitude[0, pixel] = math.sqrt(float(beta[1] ** 2 + beta[2] ** 2))
        intercept[0, pixel] = float(beta[0])
        prediction[0, pixel] = float(beta[0] - beta[1])
    return {"coefficients": coefficients, "amplitude": amplitude,
            "intercept": intercept, "target_prediction": prediction}


def test_exact_references_cover_clean_zero_negative_and_noisy_amplitudes():
    data = fixture()
    assert data["schema"] == example_module().SYNTHETIC_VERSION
    reference = independent_reference(data)
    for sample in data["hand_reference"]["samples"]:
        pixel = sample["pixel_index"]
        assert reference["coefficients"][:, pixel].tolist() == pytest.approx(
            [float(Fraction(value)) for value in sample["coefficients"]], abs=0,
        )
        expected_amplitude = (
            math.sqrt(54641) / 1000 if sample["amplitude"] == "sqrt(54641)/1000"
            else float(Fraction(sample["amplitude"]))
        )
        assert reference["amplitude"][0, pixel] == pytest.approx(expected_amplitude, abs=1e-15)
        assert reference["target_prediction"][0, pixel] == pytest.approx(
            float(Fraction(sample["target_prediction"])), abs=0,
        )
    assert reference["coefficients"][1, 0] == pytest.approx(0.3)
    assert reference["coefficients"][2, 0] == pytest.approx(0.4)
    assert reference["amplitude"][0, 0] == pytest.approx(0.5)
    assert reference["amplitude"][0, 1] == 0
    assert reference["coefficients"][1, 2] < 0 and reference["coefficients"][2, 2] < 0
    assert reference["amplitude"][0, 2] == pytest.approx(0.5)

    outside = data["pixel_centers"][data["hand_reference"]["outside_geometry_pixel_index"]]
    west, south, east, north = data["bbox"]
    assert west <= outside[0] <= east and south <= outside[1] <= north
    assert not shape(data["scene_geometry"]).covers(Point(*outside))


def test_sdk_hypot_signatures_and_harmonic_amplitude_workflow_compile_and_evaluate():
    data = fixture()
    local = local_data(data)
    module = example_module()
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = module.build_harmonic_amplitude(
            ee, ee.ImageCollection(data["collection_id"]),
            data["origin_millis"], data["target_day"],
        )
        compiled = {name: compile_value(ee, value, local) for name, value in outputs.items()}
        number_expression = encode(ee, ee.Number(-3).hypot(4))
        array_expression = encode(ee, ee.Array([-3, 4]).hypot(ee.Array([4, 3])))
        amplitude_expression = encode(ee, outputs["amplitude"])
        number_result = compile_expression(number_expression, local["catalog"], local["items"])
        array_result = compile_expression(array_expression, local["catalog"], local["items"])
        large_array_result = compile_expression(
            encode(ee, ee.Array([1e308, 3]).hypot(ee.Array([1e308, 4]))),
            local["catalog"], local["items"],
        )
        large_number_result = compile_expression(
            encode(ee, ee.Number(1e308).hypot(1e308)), local["catalog"], local["items"]
        )
    assert guard.evidence()["attempt_count"] == 0

    assert number_result["value"] == 5
    assert large_number_result["value"] == pytest.approx(math.sqrt(2) * 1e308, rel=2e-16)
    assert array_result["value"] == [5, 5]
    assert large_array_result["value"][0] == pytest.approx(math.sqrt(2) * 1e308, rel=2e-16)
    assert large_array_result["value"][1] == 5
    assert number_expression["functionName"] == "Number.hypot"
    assert number_expression["arguments"] == {"left": -3, "right": 4}
    array_hypot = find_invocations(array_expression, "Array.hypot")
    assert len(array_hypot) == 1 and set(array_hypot[0]["arguments"]) == {"left", "right"}
    assert compiled["amplitude"]["bands"] == ["amplitude"]
    assert compiled["coefficients"]["bands"] == ["intercept", "cosine", "sine"]
    assert compiled["intercept"]["bands"] == ["intercept"]
    assert compiled["target_prediction"]["bands"] == ["target_ndvi"]
    assert compiled["amplitude"]["source_item_ids"] == data["sorted_frame_order"]
    for result in compiled.values():
        validate(result["process_graph"])
        assert len(result["process_graph"]) <= 500
    hypot = find_invocations(amplitude_expression, "Image.hypot")
    assert len(hypot) == 1
    assert set(hypot[0]["arguments"]) == {"image1", "image2"}

    expected = independent_reference(data)
    actual = {}
    for name in ("amplitude", "coefficients", "intercept", "target_prediction"):
        values, names, timed = evaluate_graph(
            compiled[name], local["arrays"], grid=local["grid"],
            source_geometries=local["geometries"],
        )
        assert timed is False and names == compiled[name]["bands"]
        actual[name] = values
        np.testing.assert_allclose(values, expected[name], atol=2e-6, rtol=2e-6, equal_nan=True)

    np.testing.assert_allclose(actual["amplitude"][0, :4],
                               [0.5, 0, 0.5, math.sqrt(54641) / 1000], atol=2e-6)
    assert np.isnan(actual["amplitude"][0, 4:]).all()
    assert np.isnan(actual["coefficients"][:, 4:]).all()
    assert np.isnan(actual["target_prediction"][0, 4:]).all()

