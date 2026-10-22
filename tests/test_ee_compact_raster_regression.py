"""Complete multiresponse outputs through the pinned Earth Engine client."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_regression_workflow import independent_reference
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-raster-regression-v1.json"
EXAMPLE = ROOT / "examples/16_GEE_python_raster_multiresponse_regression.py"


def load_example():
    spec = importlib.util.spec_from_file_location("compact_raster_regression_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def data():
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def example():
    return load_example()


@pytest.fixture
def ee():
    guard = OfflineGuard()
    with guard:
        client = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert client.__version__ == "1.7.49"
        yield client
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def local(data):
    items = [{
        "id": row["id"], "bbox": data["extent"],
        "geometry": data[row["geometry"]],
        "properties": {"system:index": row["id"], "system:time_start": row["time_millis"]},
    } for row in data["rows"]]
    arrays = {row["id"]: {
        name: np.asarray([np.nan if value is None else value for value in row[name]],
                         dtype=np.float64)
        for name in ("x", "signal", "temperature")
    } for row in data["rows"]}
    geometries = {row["id"]: data[row["geometry"]] for row in data["rows"]}
    catalog = [{"id": data["collection_id"], "cube:dimensions": {
        "bands": {"values": ["x", "signal", "temperature"]},
    }}]
    return catalog, {data["collection_id"]: items}, arrays, geometries


def complete_outputs(ee, example, source, target_x):
    fit = example.fit_source(ee, source)
    coefficients = fit.select("coefficients").arrayFlatten([
        ["offset", "scale"], ["signal", "temperature"],
    ])
    residuals = fit.select("residuals").arrayFlatten([
        ["signal_rms", "temperature_rms"],
    ])
    signal = coefficients.select("offset_signal").add(
        coefficients.select("scale_signal").multiply(target_x)
    ).rename("predicted_signal")
    temperature = coefficients.select("offset_temperature").add(
        coefficients.select("scale_temperature").multiply(target_x)
    ).rename("predicted_temperature")
    prediction = signal.addBands(temperature).set({
        "fixtureVersion": example.SYNTHETIC_VERSION, "target_x": target_x,
    })
    return coefficients, residuals, prediction


def signal_coefficients(ee, example, source):
    return example.fit_source(ee, source).select("coefficients").arrayFlatten([
        ["offset", "scale"], ["signal", "temperature"],
    ]).select(["offset_signal", "scale_signal"])


def compile_output(ee, value, local):
    catalog, items, _, _ = local
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, catalog, items)


def evaluate_output(result, local, data):
    _, _, arrays, geometries = local
    validate(result["process_graph"])
    values, names, timed = evaluate_graph(
        result, arrays, grid=data["pixel_centers"], source_geometries=geometries,
    )
    assert timed is False
    return values, names


def test_full_multiband_outputs_compile_and_residual_and_combined_limits_are_explicit(
        ee, data, example, local):
    assert example.SYNTHETIC_VERSION == data["schema"]
    reference = independent_reference(data)
    outputs = complete_outputs(
        ee, example, ee.ImageCollection(data["collection_id"]), data["target_x"],
    )
    full_names = {
        "coefficients": ["offset_signal", "offset_temperature",
                         "scale_signal", "scale_temperature"],
        "residuals": ["signal_rms", "temperature_rms"],
        "prediction": ["predicted_signal", "predicted_temperature"],
    }
    full_values = {
        "coefficients": reference["coefficients"],
        "residuals": reference["residuals"],
        "prediction": reference["prediction"],
    }
    full_results, graph_limited = {}, {}
    for name, value in zip(full_names, outputs):
        try:
            full_results[name] = compile_output(ee, value, local)
        except UnsupportedEEError as exc:
            if "500 nodes" not in str(exc):
                raise
            graph_limited[name] = str(exc)

    assert set(full_results) == {"coefficients", "prediction"}
    assert set(graph_limited) == {"residuals"}
    for name, result in full_results.items():
        assert result["bands"] == full_names[name]
        assert result["source_item_ids"] == [row["id"] for row in data["rows"]]
        assert result["properties"] == (
            {"fixtureVersion": data["schema"], "target_x": data["target_x"]}
            if name == "prediction" else {}
        )
        actual, names = evaluate_output(result, local, data)
        assert names == full_names[name]
        np.testing.assert_allclose(
            actual, full_values[name], rtol=2e-6, atol=2e-6, equal_nan=True,
        )

    combined = outputs[0].addBands(outputs[1]).addBands(outputs[2])
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compile_output(ee, combined, local)


def test_six_split_outputs_match_fixture_values_and_share_all_three_masks(
        ee, data, example, local):
    reference = independent_reference(data)
    outputs = example.build_prediction(
        ee, ee.ImageCollection(data["collection_id"]), data["target_x"],
    )
    expected = {
        "coefficients_signal": (["offset_signal", "scale_signal"],
                                reference["coefficients"][[0, 2]], {}),
        "coefficients_temperature": (
            ["offset_temperature", "scale_temperature"],
            reference["coefficients"][[1, 3]], {},
        ),
        "residual_signal": (["signal_rms"], reference["residuals"][[0]], {}),
        "residual_temperature": (
            ["temperature_rms"], reference["residuals"][[1]], {},
        ),
        "prediction_signal": (
            ["predicted_signal"], reference["prediction"][[0]],
            {"fixtureVersion": data["schema"], "target_x": data["target_x"]},
        ),
        "prediction_temperature": (
            ["predicted_temperature"], reference["prediction"][[1]],
            {"fixtureVersion": data["schema"], "target_x": data["target_x"]},
        ),
    }
    assert set(outputs) == set(expected)
    results = {}
    for name, value in outputs.items():
        result = results[name] = compile_output(ee, value, local)
        bands, values, properties = expected[name]
        assert result["bands"] == bands
        assert result["properties"] == properties
        assert result["source_item_ids"] == [row["id"] for row in data["rows"]]
        actual, names = evaluate_output(result, local, data)
        assert names == bands
        np.testing.assert_allclose(actual, values, rtol=2e-6, atol=2e-6, equal_nan=True)

    expected_mask = np.array([False, False, True, True, True])
    for result in results.values():
        actual, _ = evaluate_output(result, local, data)
        np.testing.assert_array_equal(np.isnan(actual).all(axis=0), expected_mask)
    assert reference["valid_row_counts"] == data["valid_row_counts"]


def test_same_day_items_and_duplicate_frames_keep_separate_observation_weight(
        ee, data, example, local):
    assert data["rows"][0]["time_millis"] == data["rows"][1]["time_millis"]
    baseline_source = ee.ImageCollection.fromImages([
        ee.Image(row["id"]) for row in data["rows"]
    ])
    baseline_result = compile_output(
        ee, signal_coefficients(ee, example, baseline_source), local,
    )
    baseline, names = evaluate_output(baseline_result, local, data)
    assert names == ["offset_signal", "scale_signal"]
    assert baseline_result["source_item_ids"] == [row["id"] for row in data["rows"]]
    full_reference = independent_reference(data)
    np.testing.assert_allclose(
        baseline, full_reference["coefficients"][[0, 2]],
        rtol=2e-6, atol=2e-6, equal_nan=True,
    )

    without_same_day = deepcopy(data)
    without_same_day["rows"] = [row for row in data["rows"] if row["id"] != "reg-b"]
    without_same_day_source = ee.ImageCollection.fromImages([
        ee.Image(row["id"]) for row in without_same_day["rows"]
    ])
    without_same_day_result = compile_output(
        ee, signal_coefficients(ee, example, without_same_day_source), local,
    )
    without_same_day_values, _ = evaluate_output(without_same_day_result, local, data)
    without_same_day_reference = independent_reference(without_same_day)
    np.testing.assert_allclose(
        without_same_day_values, without_same_day_reference["coefficients"][[0, 2]],
        rtol=2e-6, atol=2e-6, equal_nan=True,
    )
    assert not np.allclose(without_same_day_values[:, 0], baseline[:, 0])

    repeated_data = deepcopy(data)
    repeated_data["rows"].append(deepcopy(data["rows"][0]))
    repeated_source = ee.ImageCollection.fromImages([
        ee.Image(row["id"]) for row in repeated_data["rows"]
    ])
    repeated_result = compile_output(
        ee, signal_coefficients(ee, example, repeated_source), local,
    )
    repeated_values, _ = evaluate_output(repeated_result, local, data)
    repeated_reference = independent_reference(repeated_data)
    assert repeated_result["source_item_ids"] == [row["id"] for row in data["rows"]]
    np.testing.assert_allclose(
        repeated_values, repeated_reference["coefficients"][[0, 2]],
        rtol=2e-6, atol=2e-6, equal_nan=True,
    )
    assert not np.allclose(repeated_values[:, 0], baseline[:, 0])


def test_real_arithmetic_expression_over_500_nodes_remains_rejected(ee, local):
    base = ee.Image("reg-a").select("x")
    terms = [base.add(index + 1).multiply(2) for index in range(260)]
    while len(terms) > 1:
        terms = [terms[index].add(terms[index + 1])
                 if index + 1 < len(terms) else terms[index]
                 for index in range(0, len(terms), 2)]
    expression = ee.serializer.encode(terms[0], for_cloud_api=False)
    with pytest.raises(UnsupportedEEError, match="500 nodes"):
        compile_expression(expression, local[0], local[1])
