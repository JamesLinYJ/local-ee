"""Static two-response raster regression through typed array images."""
from fractions import Fraction
import importlib.util
import json
from pathlib import Path

import numpy as np
from shapely.geometry import Point, shape

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples/21_GEE_python_multi_response_arrays.py"
COEFFICIENT_BANDS = [
    "intercept_signal", "intercept_temperature", "slope_signal", "slope_temperature",
]
SAMPLE_BANDS = [f"x{x}_{band}" for x in range(4) for band in ("signal", "temperature")]


def fixture():
    return json.loads((ROOT / "tests/fixtures/ee-multi-response-arrays-v1.json").read_text())


def example_module():
    spec = importlib.util.spec_from_file_location("multi_response_array_example", EXAMPLE_PATH)
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
            "system:time_start": 1_680_000_000_000
                + data["frame_x"][frame] * 86_400_000,
        },
    } for frame in data["frame_order"]]
    arrays = {
        frame: {
            band: np.asarray([
                np.nan if value is None else value
                for value in data["frame_values"][frame][band]
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


def exact_coefficients(xs, ys):
    count = Fraction(len(xs))
    sum_x = sum(xs, Fraction(0))
    sum_y = sum(ys, Fraction(0))
    sum_xx = sum((x * x for x in xs), Fraction(0))
    sum_xy = sum((x * y for x, y in zip(xs, ys)), Fraction(0))
    determinant = count * sum_xx - sum_x * sum_x
    offset = (sum_y * sum_xx - sum_x * sum_xy) / determinant
    slope = (count * sum_xy - sum_x * sum_y) / determinant
    return offset, slope


def independent_fraction_reference(data):
    xs = [Fraction(row[1]) for row in data["hand_reference"]["design"]]
    pixel_count = len(data["pixel_centers"])
    coefficients = np.full((4, pixel_count), np.nan)
    fitted = np.full((8, pixel_count), np.nan)
    residuals = np.full((8, pixel_count), np.nan)
    geometry = shape(data["scene_geometry"])
    for pixel, point in enumerate(data["pixel_centers"]):
        if not geometry.covers(Point(*point)):
            continue
        y_by_band = [[data["frame_values"][frame][band][pixel]
                      for frame in data["sorted_frame_order"]]
                     for band in data["bands"]]
        if any(value is None for values in y_by_band for value in values):
            continue
        beta = [exact_coefficients(
            xs, [Fraction(str(value)) for value in values]
        ) for values in y_by_band]
        coefficients[:, pixel] = [float(beta[0][0]), float(beta[1][0]),
                                   float(beta[0][1]), float(beta[1][1])]
        for row, x in enumerate(xs):
            for response, values in enumerate(y_by_band):
                fitted_value = beta[response][0] + beta[response][1] * x
                residual_value = Fraction(str(values[row])) - fitted_value
                output_index = row * 2 + response
                fitted[output_index, pixel] = float(fitted_value)
                residuals[output_index, pixel] = float(residual_value)
    return {"coefficients": coefficients, "fitted": fitted, "residuals": residuals}


def independent_svd_reference(data):
    """NumPy SVD check after the workflow's explicit Float32 conversions."""
    design = np.asarray(data["hand_reference"]["design"], dtype=np.float32).astype(np.float64)
    u, singular, vt = np.linalg.svd(design, full_matrices=False)
    count = len(data["pixel_centers"])
    coefficients = np.full((4, count), np.nan)
    fitted = np.full((8, count), np.nan)
    residuals = np.full((8, count), np.nan)
    geometry = shape(data["scene_geometry"])
    for pixel, point in enumerate(data["pixel_centers"]):
        if not geometry.covers(Point(*point)):
            continue
        raw = np.asarray([
            [data["frame_values"][frame][band][pixel]
             for band in data["bands"]]
            for frame in data["sorted_frame_order"]
        ], dtype=object)
        if any(value is None for value in raw.flat):
            continue
        y = raw.astype(np.float32).astype(np.float64)
        beta = vt.T @ ((u.T @ y) / singular[:, None])
        prediction = design @ beta
        error = y - prediction
        coefficients[:, pixel] = [beta[0, 0], beta[0, 1], beta[1, 0], beta[1, 1]]
        fitted[:, pixel] = prediction.reshape(-1)
        residuals[:, pixel] = error.reshape(-1)
    return {"coefficients": coefficients, "fitted": fitted, "residuals": residuals}


def test_fraction_reference_and_fixture_cover_noise_independent_responses_and_geometry():
    data = fixture()
    assert data["schema"] == example_module().SYNTHETIC_VERSION
    assert data["frame_order"] != data["sorted_frame_order"]
    assert data["hand_reference"]["normal_matrix"] == [[4, 6], [6, 14]]
    exact = independent_fraction_reference(data)
    for pixel, reference in enumerate(data["hand_reference"]["coefficients_by_pixel"]):
        for response, expected in enumerate(reference):
            observed = exact["coefficients"][[response, response + 2], pixel]
            assert observed.tolist() == [float(Fraction(value)) for value in expected]
    assert exact["residuals"][:8, 1].tolist() == [1, 2, -1, -2, -1, -2, 1, 2]
    assert exact["coefficients"][0, 0] != exact["coefficients"][0, 1]
    assert np.isnan(exact["coefficients"][:, 3]).all()
    assert np.isnan(exact["coefficients"][:, 4]).all()

    outside = data["pixel_centers"][data["hand_reference"]["outside_geometry_pixel_index"]]
    west, south, east, north = data["bbox"]
    assert west <= outside[0] <= east and south <= outside[1] <= north
    assert not shape(data["scene_geometry"]).covers(Point(*outside))


def test_sdk_multi_response_arrays_compile_and_match_fraction_and_svd_references():
    data = fixture()
    local = local_data(data)
    module = example_module()
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = module.build_multi_response_fit(
            ee, ee.ImageCollection(data["collection_id"]),
        )
        compiled = {name: compile_value(ee, value, local) for name, value in outputs.items()}
        encoded = encode(ee, outputs["coefficients"])
    assert guard.evidence()["attempt_count"] == 0

    assert compiled["source_ids"]["value"] == data["sorted_frame_order"]
    assert compiled["design_matrix"]["value"] == data["hand_reference"]["design"]
    assert compiled["coefficients"]["bands"] == COEFFICIENT_BANDS
    assert compiled["fitted"]["bands"] == SAMPLE_BANDS
    assert compiled["residuals"]["bands"] == SAMPLE_BANDS
    for result in compiled.values():
        if result["kind"] == "image":
            validate(result["process_graph"])
            assert len(result["process_graph"]) <= 500

    invocations = {
        name: find_invocations(encoded, name)
        for name in (
            "Image.arrayRepeat", "Image.arrayCat", "ImageCollection.toArrayPerBand",
            "Image.arrayReshape", "Image.matrixSolve",
        )
    }
    assert all(invocations.values()), invocations
    repeat = invocations["Image.arrayRepeat"][0]
    assert repeat["arguments"]["axis"] == 0
    assert set(repeat["arguments"]) == {"input", "axis", "copies"}
    assert len(invocations["Image.arrayCat"]) == 2
    assert all(call["arguments"]["axis"] == 1 for call in invocations["Image.arrayCat"])
    assert invocations["ImageCollection.toArrayPerBand"][0]["arguments"]["dropMasked"] is False
    assert len(invocations["Image.arrayReshape"]) == 2
    assert len(invocations["Image.matrixSolve"]) == 1

    fraction = independent_fraction_reference(data)
    svd = independent_svd_reference(data)
    for name, expected_bands in (
        ("coefficients", COEFFICIENT_BANDS),
        ("fitted", SAMPLE_BANDS),
        ("residuals", SAMPLE_BANDS),
    ):
        result = compiled[name]
        assert result["source_item_ids"] == data["sorted_frame_order"]
        actual, names, timed = evaluate_graph(
            result, local["arrays"], grid=local["grid"],
            source_geometries=local["geometries"],
        )
        assert names == expected_bands and timed is False
        np.testing.assert_allclose(actual, fraction[name], atol=2e-6, rtol=2e-6, equal_nan=True)
        np.testing.assert_allclose(actual, svd[name], atol=2e-6, rtol=2e-6, equal_nan=True)

    coefficients = evaluate_graph(
        compiled["coefficients"], local["arrays"], grid=local["grid"],
        source_geometries=local["geometries"],
    )[0]
    np.testing.assert_allclose(coefficients[:, 0], [2, -1, 3, 0.5], atol=2e-6)
    np.testing.assert_allclose(coefficients[:, 1], [1, -2, 2, 0.5], atol=2e-6)
    np.testing.assert_allclose(coefficients[:, 2], [-1, 4, 0.5, -2], atol=2e-6)
    assert np.isnan(coefficients[:, 3]).all()  # One missing response masks both columns.
    assert np.isnan(coefficients[:, 4]).all()  # Bbox-contained but polygon-excluded.

