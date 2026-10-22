"""Versioned multiresponse fit, real scene coverage and target prediction."""
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


def load_fixture():
    return json.loads((ROOT / "tests/fixtures/ee-raster-regression-v1.json").read_text())


def as_numbers(value):
    return np.array(value, dtype=np.float64)


def independent_reference(data):
    coefficients, residuals, predictions, counts = [], [], [], []
    for index, center in enumerate(data["pixel_centers"]):
        complete = []
        for row in data["rows"]:
            values = [row[name][index] for name in ("x", "signal", "temperature")]
            if (shape(data[row["geometry"]]).covers(Point(*center))
                    and all(value is not None for value in values)):
                complete.append(values)
        counts.append(len(complete))
        if len(complete) <= 2:
            coefficients.append([np.nan]*4)
            residuals.append([np.nan]*2)
            predictions.append([np.nan]*2)
            continue
        values = np.array(complete, dtype=np.float64)
        design = np.column_stack([np.ones(len(values)), values[:, 0]])
        beta, _, rank, _ = np.linalg.lstsq(design, values[:, 1:], rcond=None)
        if rank < 2:
            coefficients.append([np.nan]*4)
            residuals.append([np.nan]*2)
            predictions.append([np.nan]*2)
            continue
        coefficients.append(beta.reshape(-1))
        residuals.append(np.sqrt(np.mean((values[:, 1:]-design@beta)**2, axis=0)))
        predictions.append(np.array([1, data["target_x"]])@beta)
    return {"coefficients": np.array(coefficients).T,
            "residuals": np.array(residuals).T,
            "prediction": np.array(predictions).T,
            "valid_row_counts": counts}


def test_hand_fractions_and_joint_complete_cases_match_independent_svd():
    data = load_fixture()
    reference = independent_reference(data)
    assert reference["valid_row_counts"] == data["valid_row_counts"]
    for name in ("coefficients", "residuals", "prediction"):
        np.testing.assert_allclose(reference[name], as_numbers(data[name]),
            atol=1e-12, rtol=1e-12, equal_nan=True)
    # All raw data are finite here, and the center is strictly inside every
    # bbox; only the real corner polygons remove the final two observations.
    assert all(row[name][4] is not None for row in data["rows"]
               for name in ("x", "signal", "temperature"))
    assert shape(data["geometry_full"]).contains(Point(*data["pixel_centers"][4]))
    assert not shape(data["geometry_cut_corner"]).covers(Point(*data["pixel_centers"][4]))


def test_multiresponse_raster_workflow_keeps_source_masks_and_output_types():
    data = load_fixture()
    spec = importlib.util.spec_from_file_location("raster_regression_example",
        ROOT / "examples/16_GEE_python_raster_multiresponse_regression.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SYNTHETIC_VERSION == data["schema"]
    items = [{"id": row["id"], "bbox": data["extent"],
        "geometry": data[row["geometry"]],
        "properties": {"system:index": row["id"], "system:time_start": row["time_millis"]}}
        for row in data["rows"]]
    arrays = {row["id"]: {name: as_numbers(row[name])
        for name in ("x", "signal", "temperature")} for row in data["rows"]}
    catalog = [{"id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": ["x", "signal", "temperature"]}}}]
    geometries = {row["id"]: data[row["geometry"]] for row in data["rows"]}
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a"*48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        outputs = module.build_prediction(ee, ee.ImageCollection(data["collection_id"]), data["target_x"])
        results = {name: compile_expression(ee.serializer.encode(value, for_cloud_api=False),
            catalog, {data["collection_id"]: items}) for name,value in outputs.items()}
    expected_names = {
        "coefficients_signal": ["offset_signal", "scale_signal"],
        "coefficients_temperature": ["offset_temperature", "scale_temperature"],
        "residual_signal": ["signal_rms"],
        "residual_temperature": ["temperature_rms"],
        "prediction_signal": ["predicted_signal"],
        "prediction_temperature": ["predicted_temperature"],
    }
    expected_values = {
        "coefficients_signal": as_numbers(data["coefficients"])[[0,2]],
        "coefficients_temperature": as_numbers(data["coefficients"])[[1,3]],
        "residual_signal": as_numbers(data["residuals"])[[0]],
        "residual_temperature": as_numbers(data["residuals"])[[1]],
        "prediction_signal": as_numbers(data["prediction"])[[0]],
        "prediction_temperature": as_numbers(data["prediction"])[[1]],
    }
    for name, result in results.items():
        validate(result["process_graph"])
        assert result["source_item_ids"] == [row["id"] for row in data["rows"]]
        assert result["bands"] == expected_names[name]
        assert result["properties"] == ({"fixtureVersion": data["schema"], "target_x": data["target_x"]}
            if name.startswith("prediction_") else {})
        actual, names, timed = evaluate_graph(result, arrays,
            grid=data["pixel_centers"], source_geometries=geometries)
        assert names == expected_names[name] and timed is False
        np.testing.assert_allclose(actual, expected_values[name], atol=2e-6, rtol=2e-6, equal_nan=True)
    assert guard.evidence()["attempt_count"] == 0
