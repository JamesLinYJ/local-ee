"""Official-SDK covariance workflow over bounded synthetic remote-sensing samples."""
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
EXAMPLE_PATH = ROOT / "examples/22_GEE_python_synthetic_covariance.py"
COVARIANCE_BANDS = ["red_red", "red_nir", "nir_red", "nir_nir"]
DIAGONAL_BANDS = ["red_variance", "nir_variance"]
SAMPLE_BANDS = [f"d{day}_{band}" for day in ("000", "090", "180", "270")
                for band in ("red", "nir")]


def fixture():
    return json.loads((ROOT / "tests/fixtures/ee-covariance-descriptors-v1.json").read_text())


def example_module():
    spec = importlib.util.spec_from_file_location("synthetic_covariance_example", EXAMPLE_PATH)
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
                + data["frame_day"][frame] * 86_400_000,
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


def exact_covariance_reference(data):
    count = len(data["sorted_frame_order"])
    pixels = len(data["pixel_centers"])
    covariances = np.full((4, pixels), np.nan)
    diagonals = np.full((2, pixels), np.nan)
    diagonal_matrices = np.full((4, pixels), np.nan)
    traces = np.full((1, pixels), np.nan)
    determinants = np.full((1, pixels), np.nan)
    centered_values = np.full((2 * count, pixels), np.nan)
    exact_traces = [None] * pixels
    exact_determinants = [None] * pixels
    geometry = shape(data["scene_geometry"])
    hand = data["hand_reference"]["sample_covariance_by_pixel"]
    for pixel, point in enumerate(data["pixel_centers"]):
        if not geometry.covers(Point(*point)):
            continue
        samples = [[data["frame_values"][frame][band][pixel]
                    for band in data["bands"]]
                   for frame in data["sorted_frame_order"]]
        if any(value is None for row in samples for value in row):
            continue
        rows = [[Fraction(value) for value in row] for row in samples]
        means = [sum(row[column] for row in rows) / count for column in range(2)]
        centered = [[value - means[column] for column, value in enumerate(row)]
                    for row in rows]
        covariance = [[
            sum(row[left] * row[right] for row in centered) / (count - 1)
            for right in range(2)
        ] for left in range(2)]
        assert [[str(value) for value in row] for row in covariance] == hand[pixel]
        covariances[:, pixel] = [float(value) for row in covariance for value in row]
        diagonals[:, pixel] = [float(covariance[0][0]), float(covariance[1][1])]
        diagonal_matrices[:, pixel] = [
            float(covariance[0][0]), 0.0, 0.0, float(covariance[1][1]),
        ]
        trace = covariance[0][0] + covariance[1][1]
        determinant = covariance[0][0] * covariance[1][1] - covariance[0][1] * covariance[1][0]
        traces[0, pixel] = float(trace)
        determinants[0, pixel] = float(determinant)
        exact_traces[pixel] = str(trace)
        exact_determinants[pixel] = str(determinant)
        for row, values in enumerate(centered):
            centered_values[row * 2:row * 2 + 2, pixel] = [float(x) for x in values]
    assert exact_traces == data["hand_reference"]["trace_by_pixel"]
    assert exact_determinants == data["hand_reference"]["determinant_by_pixel"]
    return {
        "covariance": covariances,
        "diagonal": diagonals,
        "diagonal_matrix": diagonal_matrices,
        "trace": traces,
        "determinant": determinants,
        "centered": centered_values,
    }


def numpy_covariance_reference(data):
    """Independent sample-covariance calculation using NumPy's ddof=1 path."""
    pixels = len(data["pixel_centers"])
    covariance = np.full((4, pixels), np.nan)
    geometry = shape(data["scene_geometry"])
    for pixel, point in enumerate(data["pixel_centers"]):
        if not geometry.covers(Point(*point)):
            continue
        samples = np.asarray([
            [data["frame_values"][frame][band][pixel] for band in data["bands"]]
            for frame in data["sorted_frame_order"]
        ], dtype=object)
        if any(value is None for value in samples.flat):
            continue
        narrowed = samples.astype(np.float32).astype(np.float64)
        matrix = np.cov(narrowed, rowvar=False, ddof=1)
        covariance[:, pixel] = matrix.reshape(-1)
    return covariance


def test_fixture_fraction_reference_and_covariance_invariants():
    data = fixture()
    module = example_module()
    assert data["schema"] == module.SYNTHETIC_VERSION
    assert data["frame_order"] != data["sorted_frame_order"]
    exact = exact_covariance_reference(data)
    np.testing.assert_allclose(exact["covariance"][:, 0], [5 / 3, 2 / 3, 2 / 3, 4 / 3])
    np.testing.assert_allclose(exact["covariance"][:, 1], [5 / 3, -5 / 3, -5 / 3, 5 / 3])
    np.testing.assert_allclose(exact["covariance"][:, 2], [0, 0, 0, 2 / 3])
    np.testing.assert_allclose(exact["trace"][0, :3], [3, 10 / 3, 2 / 3])
    np.testing.assert_allclose(exact["determinant"][0, :3], [16 / 9, 0, 0])
    assert np.isnan(exact["covariance"][:, 3]).all()
    assert np.isnan(exact["covariance"][:, 4]).all()
    assert exact["covariance"][1, 0] > 0 and exact["covariance"][1, 1] < 0
    assert exact["covariance"][0, 2] == 0 and exact["covariance"][3, 2] > 0

    for pixel in range(3):
        matrix = exact["covariance"][:, pixel].reshape((2, 2))
        assert matrix[0, 0] >= 0 and matrix[1, 1] >= 0
        assert np.linalg.det(matrix) >= -1e-12
        assert np.linalg.eigvalsh(matrix).min() >= -1e-12

    missing = data["hand_reference"]["joint_missing_pixel_index"]
    outside = data["pixel_centers"][data["hand_reference"]["outside_geometry_pixel_index"]]
    assert np.isnan(exact["covariance"][:, missing]).all()
    west, south, east, north = data["bbox"]
    assert west <= outside[0] <= east and south <= outside[1] <= north
    assert not shape(data["scene_geometry"]).covers(Point(*outside))

    numpy_reference = numpy_covariance_reference(data)
    np.testing.assert_allclose(numpy_reference, exact["covariance"], atol=1e-12, equal_nan=True)


def test_official_sdk_covariance_workflow_compiles_and_matches_independent_values():
    data = fixture()
    local = local_data(data)
    module = example_module()
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = module.build_covariance(ee, ee.ImageCollection(data["collection_id"]))
        compiled = {name: compile_value(ee, value, local) for name, value in outputs.items()}
        encoded = {name: encode(ee, value) for name, value in outputs.items()}
    assert guard.evidence()["attempt_count"] == 0

    assert compiled["source_ids"]["value"] == data["sorted_frame_order"]
    assert compiled["covariance"]["bands"] == COVARIANCE_BANDS
    assert compiled["diagonal"]["bands"] == DIAGONAL_BANDS
    assert compiled["diagonal_matrix"]["bands"] == COVARIANCE_BANDS
    assert compiled["centered"]["bands"] == SAMPLE_BANDS
    assert compiled["trace"]["bands"] == ["trace"]
    assert compiled["determinant"]["bands"] == ["determinant"]
    for result in compiled.values():
        if result["kind"] == "image":
            validate(result["process_graph"])
            assert len(result["process_graph"]) <= 500
            assert result["source_item_ids"] == data["sorted_frame_order"]

    all_invocations = [call for graph in encoded.values()
                       for call in find_invocations(graph, "ImageCollection.toArrayPerBand")]
    assert all_invocations and all(call["arguments"]["dropMasked"] is False
                                    for call in all_invocations)
    expected_algorithms = {
        "Image.arrayTranspose", "Image.matrixMultiply", "Image.matrixDiagonal",
        "Image.matrixToDiag", "Image.matrixTrace", "Image.matrixDeterminant",
    }
    seen_algorithms = {
        invocation["functionName"]
        for graph in encoded.values()
        for invocation in find_invocations(graph, "Image.arrayTranspose")
        + find_invocations(graph, "Image.matrixMultiply")
        + find_invocations(graph, "Image.matrixDiagonal")
        + find_invocations(graph, "Image.matrixToDiag")
        + find_invocations(graph, "Image.matrixTrace")
        + find_invocations(graph, "Image.matrixDeterminant")
    }
    assert expected_algorithms <= seen_algorithms

    exact = exact_covariance_reference(data)
    numpy_reference = numpy_covariance_reference(data)
    for name, bands in (
        ("centered", SAMPLE_BANDS), ("covariance", COVARIANCE_BANDS),
        ("diagonal", DIAGONAL_BANDS), ("diagonal_matrix", COVARIANCE_BANDS),
        ("trace", ["trace"]), ("determinant", ["determinant"]),
    ):
        actual, names, timed = evaluate_graph(
            compiled[name], local["arrays"], grid=local["grid"],
            source_geometries=local["geometries"],
        )
        assert names == bands and timed is False
        np.testing.assert_allclose(actual, exact[name], atol=2e-6, rtol=2e-6, equal_nan=True)
        if name == "covariance":
            np.testing.assert_allclose(actual, numpy_reference, atol=2e-6, rtol=2e-6, equal_nan=True)
    assert np.isnan(evaluate_graph(
        compiled["covariance"], local["arrays"], grid=local["grid"],
        source_geometries=local["geometries"],
    )[0][:, 3:]).all()
