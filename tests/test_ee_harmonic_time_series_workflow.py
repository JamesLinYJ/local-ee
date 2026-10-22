"""Pinned-SDK harmonic workflow with synthetic dates, masks and exact checks."""
from fractions import Fraction
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, shape

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "examples/19_GEE_python_harmonic_time_series.py"
FRAME_LABELS = [
    "day_000", "day_090", "day_180_a", "day_180_b",
    "day_270", "day_360", "day_450",
]
COEFFICIENT_LABELS = ["intercept", "cosine", "sine"]


def fixture():
    return json.loads((ROOT / "tests/fixtures/ee-harmonic-time-series-v1.json").read_text())


def example_module():
    spec = importlib.util.spec_from_file_location("harmonic_time_series_example", EXAMPLE_PATH)
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
        "id": scene_id,
        "bbox": data["bbox"],
        "geometry": data["scene_geometry"],
        "properties": {
            "system:index": scene_id,
            "system:time_start": data["origin_millis"]
                + data["frame_days"][scene_id] * 86_400_000,
        },
    } for scene_id in data["frame_order"]]
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
    geometries = {frame: data["scene_geometry"] for frame in data["frame_order"]}
    return {
        "catalog": catalog,
        "items": {data["collection_id"]: items},
        "arrays": arrays,
        "geometries": geometries,
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


def hand_reference(data):
    """Closed-form rational OLS for the exact quadrant design and day-540 target."""
    phases = [Fraction(1), Fraction(0), Fraction(-1), Fraction(-1),
              Fraction(0), Fraction(1), Fraction(0)]
    sines = [Fraction(0), Fraction(1), Fraction(0), Fraction(0),
             Fraction(-1), Fraction(0), Fraction(1)]
    rows = [[Fraction(1), c, s] for c, s in zip(phases, sines)]
    gram = [[sum(row[i] * row[j] for row in rows) for j in range(3)]
            for i in range(3)]
    assert gram == data["hand_reference"]["matrix"]
    y = [Fraction(value) for value in data["hand_reference"]["p0_actual"]]
    rhs = [sum(row[column] * observed for row, observed in zip(rows, y))
           for column in range(3)]
    # Solve the 2x2 intercept/sine block and independent cosine coefficient.
    determinant = gram[0][0] * gram[2][2] - gram[0][2] * gram[2][0]
    intercept = (rhs[0] * gram[2][2] - rhs[2] * gram[0][2]) / determinant
    sine = (gram[0][0] * rhs[2] - gram[2][0] * rhs[0]) / determinant
    cosine = rhs[1] / gram[1][1]
    beta = [intercept, cosine, sine]
    residuals = [observed - sum(a * b for a, b in zip(row, beta))
                 for row, observed in zip(rows, y)]
    prediction = beta[0] - beta[1]
    return rows, beta, residuals, prediction


def independent_svd_reference(data):
    """Float32-input SVD reference, independent from the local solver kernel."""
    days = [data["frame_days"][name] for name in data["sorted_frame_order"]]
    angles = np.asarray(days, dtype=np.float64) * (2 * np.pi / 360)
    design = np.column_stack([np.ones(len(days)), np.cos(angles), np.sin(angles)])
    design = design.astype(np.float32).astype(np.float64)
    pixel_count = len(data["pixel_centers"])
    coefficients = np.full((3, pixel_count), np.nan)
    fitted = np.full((len(days), pixel_count), np.nan)
    residuals = np.full((len(days), pixel_count), np.nan)
    geometry = shape(data["scene_geometry"])
    for pixel, point in enumerate(data["pixel_centers"]):
        if not geometry.covers(Point(*point)):
            continue
        observations = [data["pixel_values_by_frame"][frame]["ndvi"][pixel]
                       for frame in data["sorted_frame_order"]]
        if any(value is None for value in observations):
            continue
        y = np.asarray(observations, dtype=np.float32).astype(np.float64)
        u, singular, vt = np.linalg.svd(design, full_matrices=False)
        beta = vt.T @ ((u.T @ y) / singular)
        prediction = design @ beta
        coefficients[:, pixel] = beta
        fitted[:, pixel] = prediction
        residuals[:, pixel] = y - prediction
    target_angle = (data["target_day"] % 360) * (2 * np.pi / 360)
    target_row = np.asarray([1, np.cos(target_angle), np.sin(target_angle)], dtype=np.float32)
    target = (target_row @ coefficients)[None, :]
    return {"coefficients": coefficients, "fitted": fitted,
            "residuals": residuals, "target_prediction": target}


def test_exact_hand_reference_captures_repeated_phase_noise_and_target():
    data = fixture()
    module = example_module()
    assert data["schema"] == module.SYNTHETIC_VERSION
    assert data["frame_order"] != data["sorted_frame_order"]
    assert data["sorted_frame_order"].count("frame-d180-a") == 1
    assert data["sorted_frame_order"].count("frame-d180-b") == 1
    assert data["frame_days"]["frame-d180-a"] == data["frame_days"]["frame-d180-b"]

    rows, beta, residuals, target = hand_reference(data)
    expected = data["hand_reference"]
    assert beta == [Fraction(value) for value in expected["p0_coefficients"]]
    assert residuals == [Fraction(value) for value in expected["p0_residuals"]]
    assert target == Fraction(expected["p0_target_prediction"])
    assert beta == [Fraction(407, 1000), Fraction(1, 5), Fraction(121, 1000)]
    assert sum(residuals) == 0
    assert sum(row[1] * residual for row, residual in zip(rows, residuals)) == 0
    assert sum(row[2] * residual for row, residual in zip(rows, residuals)) == 0
    assert Fraction(str(data["pixel_values_by_frame"]["frame-d450"]["ndvi"][0])) == Fraction(57, 100)
    outside_point = data["pixel_centers"][-1]
    west, south, east, north = data["bbox"]
    assert west <= outside_point[0] <= east and south <= outside_point[1] <= north
    assert not shape(data["scene_geometry"]).covers(Point(*outside_point))


def test_official_sdk_date_driven_design_compiles_and_keeps_sorted_scene_order():
    data = fixture()
    module = example_module()
    local = local_data(data)
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = module.build_harmonic_series(
            ee, ee.ImageCollection(data["collection_id"]),
            data["origin_millis"], data["target_day"],
        )
        compiled = {
            name: compile_value(ee, value, local)
            for name, value in outputs.items()
        }
        encoded = encode(ee, outputs["coefficients"])
    assert guard.evidence()["attempt_count"] == 0

    for result in compiled.values():
        if result["kind"] == "image":
            validate(result["process_graph"])
    assert compiled["source_ids"]["value"] == data["sorted_frame_order"]
    assert compiled["sample_days"]["value"] == [0, 90, 180, 180, 270, 360, 450]
    design = np.asarray(compiled["design_matrix"]["value"], dtype=float)
    expected_rows = np.asarray(hand_reference(data)[0], dtype=float)
    np.testing.assert_allclose(design, expected_rows, atol=2e-15, rtol=2e-15)
    assert design.shape == (7, 3)
    np.testing.assert_allclose(design[2], design[3], atol=0, rtol=0)

    calls = {
        name: find_invocations(encoded, name)
        for name in (
            "Collection.limit", "AggregateFeatureCollection.array", "Date.difference",
            "Number.sin", "Number.cos", "ImageCollection.toArrayPerBand",
            "Image.arrayReshape", "Image.matrixSolve",
        )
    }
    assert all(calls.values()), calls
    assert calls["Collection.limit"][0]["arguments"]["key"] == "system:time_start"
    packing = calls["ImageCollection.toArrayPerBand"][0]
    assert packing["arguments"]["axis"] == 0
    assert packing["arguments"]["dropMasked"] is False
    assert calls["Image.arrayReshape"][0]["arguments"]["dimensions"] == 2
    assert len(calls["Image.matrixSolve"]) == 1


def test_harmonic_outputs_match_independent_svd_and_keep_band_specific_masks():
    data = fixture()
    local = local_data(data)
    module = example_module()
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = module.build_harmonic_series(
            ee, ee.ImageCollection(data["collection_id"]),
            data["origin_millis"], data["target_day"],
        )
        compiled = {
            name: compile_value(ee, value, local)
            for name, value in outputs.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    expected_names = {
        "ndvi_series": FRAME_LABELS,
        "quality_series": FRAME_LABELS,
        "coefficients": [f"{label}" for label in COEFFICIENT_LABELS],
        "fitted": [f"{label}" for label in FRAME_LABELS],
        "residuals": [f"{label}" for label in FRAME_LABELS],
        "target_prediction": ["target_ndvi"],
    }
    reference = independent_svd_reference(data)
    evaluated = {}
    for name, expected_bands in expected_names.items():
        result = compiled[name]
        assert result["kind"] == "image"
        assert result["bands"] == expected_bands
        assert result["source_item_ids"] == data["sorted_frame_order"]
        values, names, timed = evaluate_graph(
            result, local["arrays"], grid=local["grid"],
            source_geometries=local["geometries"],
        )
        assert names == expected_bands and timed is False
        evaluated[name] = values
    for name in ("coefficients", "fitted", "residuals", "target_prediction"):
        np.testing.assert_allclose(
            evaluated[name], reference[name], atol=2e-6, rtol=2e-6, equal_nan=True,
        )

    # p0 is the noisy exact-reference sample; p1 is missing one NDVI frame,
    # while p2 has a missing quality frame but a complete NDVI fit.
    np.testing.assert_allclose(
        evaluated["coefficients"][:, 0], [407 / 1000, 1 / 5, 121 / 1000], atol=2e-6,
    )
    np.testing.assert_allclose(evaluated["target_prediction"][0, 0], 207 / 1000, atol=2e-6)
    ordered_signal = [
        data["pixel_values_by_frame"][frame]["ndvi"][0]
        for frame in data["sorted_frame_order"]
    ]
    np.testing.assert_allclose(
        evaluated["ndvi_series"][:, 0], np.asarray(ordered_signal, dtype=np.float32),
        atol=0, rtol=0,
    )
    assert np.isnan(evaluated["coefficients"][:, 1]).all()
    assert np.isnan(evaluated["fitted"][:, 1]).all()
    assert np.isnan(evaluated["residuals"][:, 1]).all()
    assert np.isnan(evaluated["ndvi_series"][:, 1]).all()
    assert np.isfinite(evaluated["quality_series"][:, 1]).all()
    assert np.isfinite(evaluated["coefficients"][:, 2]).all()
    assert np.isfinite(evaluated["fitted"][:, 2]).all()
    assert np.isnan(evaluated["quality_series"][:, 2]).all()
    np.testing.assert_allclose(evaluated["coefficients"][:, 2], [0.1, 0.03, -0.02], atol=2e-6)
    assert np.isnan(evaluated["ndvi_series"][4, 1])
    assert evaluated["coefficients"][0, 3] < 0  # The fit does not clamp negative values.
    assert np.isnan(evaluated["coefficients"][:, 4]).all()  # Outside the nonrectangular footprint.

