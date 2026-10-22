"""Bounded cumulative-anomaly workflow over synthetic satellite scenes."""
from decimal import Decimal, localcontext
from datetime import datetime, timezone
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
EXAMPLE_PATH = ROOT / "examples/23_GEE_python_cumulative_anomaly.py"
FRAME_LABELS = ["day_000", "day_180_a", "day_180_b", "day_366"]


def fixture():
    return json.loads((ROOT / "tests/fixtures/ee-cumulative-anomaly-v1.json").read_text())


def example_module():
    spec = importlib.util.spec_from_file_location("cumulative_anomaly_example", EXAMPLE_PATH)
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
            "system:time_start": data["origin_millis"]
                + data["frame_days"][frame] * 86_400_000,
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


def exact_references(data):
    frames = data["sorted_frame_order"]
    pixel_count = len(data["pixel_centers"])
    expected = {
        name: np.full((len(frames), pixel_count), np.nan)
        for name in ("anomalies", "cumulative", "cumulative_sum", "prefix_min", "prefix_max")
    }
    norms = np.full((1, pixel_count), np.nan)
    exact_by_name = {name: [None] * pixel_count for name in expected}
    exact_squared_norms = [None] * pixel_count
    decimal_norms = [None] * pixel_count
    baseline = [Fraction(str(value)) for value in data["baseline"]]
    geometry = shape(data["scene_geometry"])
    for pixel, point in enumerate(data["pixel_centers"]):
        if not geometry.covers(Point(*point)):
            continue
        values = [data["frame_values"][frame]["ndvi"][pixel] for frame in frames]
        if any(value is None for value in values):
            continue
        anomaly = [Fraction(str(value)) - center
                   for value, center in zip(values, baseline)]
        cumulative = []
        prefix_min = []
        prefix_max = []
        running = Fraction(0)
        for value in anomaly:
            running += value
            cumulative.append(running)
            prefix_min.append(min(prefix_min[-1], value) if prefix_min else value)
            prefix_max.append(max(prefix_max[-1], value) if prefix_max else value)
        vectors = {
            "anomalies": anomaly,
            "cumulative": cumulative,
            "cumulative_sum": cumulative,
            "prefix_min": prefix_min,
            "prefix_max": prefix_max,
        }
        for name, vector in vectors.items():
            expected[name][:, pixel] = [float(value) for value in vector]
            exact_by_name[name][pixel] = [str(value) for value in vector]
        squared_norm = sum((value * value for value in anomaly), Fraction(0))
        exact_squared_norms[pixel] = str(squared_norm)
        with localcontext() as context:
            context.prec = 40
            decimal_values = [Decimal(str(value)) - Decimal(str(center))
                              for value, center in zip(values, data["baseline"])]
            norm = sum((value * value for value in decimal_values), Decimal(0)).sqrt()
            decimal_norms[pixel] = norm
        norms[0, pixel] = float(norm)
    assert exact_by_name["anomalies"] == data["hand_reference"]["anomaly_by_pixel"]
    assert exact_by_name["cumulative"] == data["hand_reference"]["cumulative_sum_by_pixel"]
    assert exact_by_name["prefix_min"] == data["hand_reference"]["prefix_min_by_pixel"]
    assert exact_by_name["prefix_max"] == data["hand_reference"]["prefix_max_by_pixel"]
    assert exact_squared_norms == data["hand_reference"]["squared_norm_by_pixel"]
    with localcontext() as context:
        context.prec = 40
        radicals = {
            "sqrt(15)/10": Decimal(15).sqrt() / Decimal(10),
            "sqrt(6)/4": Decimal(6).sqrt() / Decimal(4),
            "0": Decimal(0),
        }
        for actual, formula in zip(decimal_norms,
                                   data["hand_reference"]["frobenius_norm_by_pixel"]):
            if formula is None:
                assert actual is None
            else:
                assert abs(actual - radicals[formula]) < Decimal("1e-38")
    expected["frobenius_norm"] = norms
    return expected


def numpy_reference(data):
    """Independent NumPy cumulative reductions and vector norm after Float32 input."""
    frames = data["sorted_frame_order"]
    pixel_count = len(data["pixel_centers"])
    expected = {
        name: np.full((len(frames), pixel_count), np.nan)
        for name in ("anomalies", "cumulative", "cumulative_sum", "prefix_min", "prefix_max")
    }
    norms = np.full((1, pixel_count), np.nan)
    geometry = shape(data["scene_geometry"])
    for pixel, point in enumerate(data["pixel_centers"]):
        if not geometry.covers(Point(*point)):
            continue
        values = [data["frame_values"][frame]["ndvi"][pixel] for frame in frames]
        if any(value is None for value in values):
            continue
        observations = np.asarray(values, dtype=np.float32)
        baseline = np.asarray(data["baseline"], dtype=np.float32)
        anomalies = observations - baseline
        cumulative = np.cumsum(anomalies, dtype=np.float32)
        expected["anomalies"][:, pixel] = anomalies
        expected["cumulative"][:, pixel] = cumulative
        expected["cumulative_sum"][:, pixel] = cumulative
        expected["prefix_min"][:, pixel] = np.minimum.accumulate(anomalies)
        expected["prefix_max"][:, pixel] = np.maximum.accumulate(anomalies)
        norms[0, pixel] = np.linalg.norm(anomalies.astype(np.float64))
    expected["frobenius_norm"] = norms
    return expected


def test_fraction_and_decimal_references_cover_duplicate_dates_masks_and_geometry():
    data = fixture()
    module = example_module()
    assert data["schema"] == module.SYNTHETIC_VERSION
    assert data["frame_order"] != data["sorted_frame_order"]
    assert data["frame_days"]["frame-d180-a"] == data["frame_days"]["frame-d180-b"]
    start = datetime.fromtimestamp(data["origin_millis"] / 1000, timezone.utc)
    end = datetime.fromtimestamp(
        (data["origin_millis"] + 366 * 86_400_000) / 1000, timezone.utc,
    )
    assert start.year == 2024 and end.year == 2025

    exact = exact_references(data)
    np.testing.assert_allclose(exact["cumulative"][:, 0], [-0.05, 0.1, -0.25, -0.2])
    np.testing.assert_allclose(exact["cumulative"][:, 1], [-0.25, -0.75, -0.75, -0.5])
    np.testing.assert_allclose(exact["cumulative"][:, 2], [0, 0, 0, 0])
    np.testing.assert_allclose(exact["frobenius_norm"][0, :3],
                               [np.sqrt(15) / 10, np.sqrt(6) / 4, 0])
    missing = data["hand_reference"]["joint_missing_pixel_index"]
    assert np.isnan(exact["cumulative"][:, missing]).all()
    outside = data["pixel_centers"][data["hand_reference"]["outside_geometry_pixel_index"]]
    west, south, east, north = data["bbox"]
    assert west <= outside[0] <= east and south <= outside[1] <= north
    assert not shape(data["scene_geometry"]).covers(Point(*outside))


def test_official_sdk_cumulative_anomaly_workflow_compiles_and_matches_references():
    data = fixture()
    local = local_data(data)
    module = example_module()
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = module.build_cumulative_anomaly(
            ee, ee.ImageCollection(data["collection_id"]), data["baseline"],
        )
        compiled = {name: compile_value(ee, value, local) for name, value in outputs.items()}
        encoded = {name: encode(ee, value) for name, value in outputs.items()}
    assert guard.evidence()["attempt_count"] == 0
    assert compiled["source_ids"]["value"] == data["sorted_frame_order"]

    for name, result in compiled.items():
        if result["kind"] == "image":
            validate(result["process_graph"])
            assert len(result["process_graph"]) <= 500
            assert result["source_item_ids"] == data["sorted_frame_order"]
    for name in ("anomalies", "cumulative", "cumulative_sum", "prefix_min", "prefix_max"):
        assert compiled[name]["bands"] == FRAME_LABELS
    assert compiled["frobenius_norm"]["bands"] == ["anomaly_frobenius_norm"]

    calls = {
        name: [invocation for graph in encoded.values()
               for invocation in find_invocations(graph, name)]
        for name in (
            "ImageCollection.toArrayPerBand", "Image.arrayReshape", "Image.arrayAccum",
            "Image.matrixFnorm", "Reducer.sum", "Reducer.min", "Reducer.max",
        )
    }
    assert calls["ImageCollection.toArrayPerBand"]
    assert calls["ImageCollection.toArrayPerBand"][0]["arguments"]["dropMasked"] is False
    assert calls["Image.arrayReshape"][0]["arguments"]["dimensions"] == 2
    assert len(calls["Image.arrayAccum"]) >= 4
    assert all(call["arguments"]["axis"] == 0 for call in calls["Image.arrayAccum"])
    assert calls["Image.matrixFnorm"]
    assert calls["Reducer.sum"] and calls["Reducer.min"] and calls["Reducer.max"]
    default_accum = next(
        call for call in calls["Image.arrayAccum"]
        if "reducer" not in call["arguments"] or call["arguments"]["reducer"] is None
    )
    assert default_accum["arguments"]["axis"] == 0

    exact = exact_references(data)
    numpy = numpy_reference(data)
    names_by_output = {name: FRAME_LABELS for name in (
        "anomalies", "cumulative", "cumulative_sum", "prefix_min", "prefix_max",
    )}
    names_by_output["frobenius_norm"] = ["anomaly_frobenius_norm"]
    for name, expected_names in names_by_output.items():
        values, names, timed = evaluate_graph(
            compiled[name], local["arrays"], grid=local["grid"],
            source_geometries=local["geometries"],
        )
        assert names == expected_names and timed is False
        np.testing.assert_allclose(values, exact[name], atol=2e-6, rtol=2e-6, equal_nan=True)
        np.testing.assert_allclose(values, numpy[name], atol=2e-6, rtol=2e-6, equal_nan=True)

    for name in names_by_output:
        values = evaluate_graph(
            compiled[name], local["arrays"], grid=local["grid"],
            source_geometries=local["geometries"],
        )[0]
        assert np.isnan(values[..., 3:]).all()
