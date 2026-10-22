"""SDK serialization through a timestamp-driven per-pixel linear trend."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
from shapely.geometry import Point, box

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-raster-linear-trend-v1.json"


def _fixture_data(fixture):
    west, south, east, north = fixture["extent"]
    geometry = {
        "type": "Polygon",
        "coordinates": [[
            [west, south], [east, south], [east, north], [west, north], [west, south]
        ]],
    }
    items = [{
        "id": row["id"],
        "bbox": fixture["extent"],
        "geometry": geometry,
        "properties": {
            "system:index": row["id"],
            "system:time_start": fixture["base_millis"] + row["day"] * fixture["day_millis"],
            "fixture_role": "observation",
        },
    } for row in fixture["rows"]]
    arrays = {
        row["id"]: {"signal": np.array([
            np.nan if value is None else value for value in row["signal"]
        ], dtype=np.float64)}
        for row in fixture["rows"]
    }
    return geometry, items, arrays


def _load_example():
    spec = importlib.util.spec_from_file_location(
        "linear_trend_example", ROOT / "examples/12_GEE_python_synthetic_linear_trend.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lstsq_reference(fixture):
    """Compute pixel fits with an independent SVD least-squares solver."""
    footprint = box(*fixture["extent"])
    values = {key: [] for key in ("valid_row_counts", "scale", "offset", "prediction")}
    target_day = fixture["independent_reference"]["target_day"]
    for index, center in enumerate(fixture["pixel_centers"]):
        rows = []
        if footprint.covers(Point(*center)):
            for frame in fixture["rows"]:
                signal = frame["signal"][index]
                if signal is not None and np.isfinite(signal):
                    rows.append((frame["day"], signal))
        values["valid_row_counts"].append(len(rows))
        if len(rows) < 2:
            values["scale"].append(None)
            values["offset"].append(None)
            values["prediction"].append(None)
            continue

        observations = np.asarray(rows, dtype=np.float64)
        design = np.column_stack((observations[:, 0], np.ones(len(rows))))
        coefficients, _, rank, _ = np.linalg.lstsq(design, observations[:, 1], rcond=None)
        if rank < 2:
            values["scale"].append(None)
            values["offset"].append(None)
            values["prediction"].append(None)
            continue
        scale, offset = coefficients
        values["scale"].append(float(scale))
        values["offset"].append(float(offset))
        values["prediction"].append(float(scale * target_day + offset))
    return values


def test_fixture_rational_reference_matches_independent_numpy_lstsq():
    fixture = json.loads(FIXTURE_PATH.read_text())
    expected = fixture["independent_reference"]
    actual = _lstsq_reference(fixture)
    assert actual["valid_row_counts"] == expected["valid_row_counts"]
    for key in ("scale", "offset", "prediction"):
        actual_values = np.array([
            np.nan if value is None else value for value in actual[key]
        ])
        expected_values = np.array([
            np.nan if value is None else value for value in expected[key]
        ])
        np.testing.assert_allclose(actual_values, expected_values, rtol=1e-12, atol=1e-12,
                                   equal_nan=True)


def test_synthetic_timestamp_fit_and_prediction_keep_real_scene_and_pixel_masks():
    fixture = json.loads(FIXTURE_PATH.read_text())
    _, items, arrays = _fixture_data(fixture)
    catalog = [{"id": fixture["collection_id"],
                "cube:dimensions": {"bands": {"values": ["signal"]}}}]
    module = _load_example()
    target_millis = fixture["base_millis"] + fixture["target_day"] * fixture["day_millis"]

    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        source = ee.ImageCollection(fixture["collection_id"])
        outputs = module.build_linear_trend(
            ee, source, fixture["base_millis"], target_millis
        )
        encoded = {
            name: ee.serializer.encode(value, for_cloud_api=False)
            for name, value in outputs.items()
        }
        coefficients = compile_expression(encoded["coefficients"], catalog,
                                          {fixture["collection_id"]: items})
        prediction = compile_expression(encoded["prediction"], catalog,
                                        {fixture["collection_id"]: items})
        target_day = compile_expression(encoded["target_day"], catalog,
                                        {fixture["collection_id"]: items})["value"]

    expected = fixture["independent_reference"]
    assert coefficients["bands"] == ["scale", "offset"]
    assert coefficients["source_item_ids"] == expected["source_item_ids"]
    assert coefficients["properties"] == {}
    assert prediction["bands"] == ["predicted_signal"]
    assert prediction["properties"] == {
        "fixtureVersion": module.SYNTHETIC_VERSION,
        "target_time_millis": expected["target_millis"],
    }
    assert prediction["source_item_ids"] == expected["source_item_ids"]
    assert target_day == expected["target_day"]

    grid = fixture["pixel_centers"]
    fitted, fit_bands, fit_timed = evaluate_graph(coefficients, arrays, grid=grid)
    predicted, prediction_bands, prediction_timed = evaluate_graph(prediction, arrays, grid=grid)
    assert fit_bands == ["scale", "offset"] and fit_timed is False
    assert prediction_bands == ["predicted_signal"] and prediction_timed is False
    scale = np.array([np.nan if value is None else value for value in expected["scale"]])
    offset = np.array([np.nan if value is None else value for value in expected["offset"]])
    prediction_reference = np.array([
        np.nan if value is None else value for value in expected["prediction"]
    ])
    np.testing.assert_allclose(fitted[0], scale, rtol=1e-6, atol=1e-6,
                               equal_nan=True)
    np.testing.assert_allclose(fitted[1], offset, rtol=1e-6, atol=1e-6,
                               equal_nan=True)
    np.testing.assert_allclose(predicted[0], prediction_reference, rtol=1e-6, atol=1e-6,
                               equal_nan=True)
    assert guard.evidence()["attempt_count"] == 0
