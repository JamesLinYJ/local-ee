"""SDK-compiled raster least squares with exact references and real masks."""
from copy import deepcopy
from fractions import Fraction
import importlib.util
import json
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
EXAMPLE_PATH = ROOT / "examples/18_GEE_python_raster_least_squares.py"


def fixture():
    return json.loads((ROOT / "tests/fixtures/ee-raster-least-squares-v1.json").read_text())


def example_module():
    spec = importlib.util.spec_from_file_location("raster_least_squares_example", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def sdk_encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def add_unknown_matrix_solve_argument(expression):
    result = deepcopy(expression)
    for _, node in result.get("scope", []):
        if isinstance(node, dict) and node.get("functionName") == "Image.matrixSolve":
            node["arguments"]["ignored"] = True
            return result
    raise AssertionError("SDK serialization omitted Image.matrixSolve")


def exact_fraction(value):
    return Fraction(str(value))


def independent_reference(data):
    """Use the hand-derived rational pseudoinverse after the explicit Float32 cast."""
    pinv = [[Fraction(7, 11), Fraction(-4, 11), Fraction(1, 11)],
            [Fraction(-4, 11), Fraction(7, 11), Fraction(1, 11)]]
    pixel_count = len(data["pixel_centers"])
    geometry = shape(data["scene_geometry"])
    bands = data["bands"]
    abundance = np.full((2, pixel_count), np.nan)
    reconstruction = np.full((3, pixel_count), np.nan)
    residuals = np.full((3, pixel_count), np.nan)
    for pixel in range(pixel_count):
        if not geometry.covers(Point(*data["pixel_centers"][pixel])):
            continue
        raw = [data["pixel_values"][band][pixel] for band in bands]
        if any(value is None for value in raw):
            continue
        # Values are narrowed by Image.toFloat before the solver sees them.
        observed = [Fraction.from_float(float(np.float32(value))) for value in raw]
        solved = [sum(pinv[row][column] * observed[column] for column in range(3))
                  for row in range(2)]
        reconstructed = [2 * solved[0] + solved[1],
                         solved[0] + 2 * solved[1],
                         solved[0] + solved[1]]
        residual = [observed[index] - reconstructed[index] for index in range(3)]
        abundance[:, pixel] = [float(value) for value in solved]
        reconstruction[:, pixel] = [float(value) for value in reconstructed]
        residuals[:, pixel] = [float(value) for value in residual]
    return {"abundances": abundance, "reconstruction": reconstruction, "residuals": residuals}


def test_exact_hand_reference_covers_clean_zero_noisy_and_negative_samples():
    data = fixture()
    assert data["schema"] == example_module().SYNTHETIC_VERSION
    design = [[Fraction(value) for value in row] for row in data["design_matrix"]]
    assert all(value > 0 for row in design for value in row)
    # Columns are non-orthogonal and full rank: det(AᵀA)=36-25=11.
    dot = sum(design[row][0] * design[row][1] for row in range(3))
    assert dot == 5
    gram_det = (sum(design[row][0] ** 2 for row in range(3))
                * sum(design[row][1] ** 2 for row in range(3)) - dot**2)
    assert gram_det == 11

    reference = data["hand_reference"]
    pinv = [[exact_fraction(value) for value in row] for row in reference["pseudoinverse"]]
    assert pinv == [[Fraction(7, 11), Fraction(-4, 11), Fraction(1, 11)],
                    [Fraction(-4, 11), Fraction(7, 11), Fraction(1, 11)]]
    for sample in reference["samples"]:
        index = sample["pixel_index"]
        input_values = [exact_fraction(data["pixel_values"][band][index]) for band in data["bands"]]
        abundance = [sum(pinv[row][column] * input_values[column] for column in range(3))
                     for row in range(2)]
        reconstructed = [sum(design[row][component] * abundance[component]
                             for component in range(2)) for row in range(3)]
        residual = [input_values[band] - reconstructed[band] for band in range(3)]
        assert abundance == [exact_fraction(value) for value in sample["abundances"]]
        assert reconstructed == [exact_fraction(value) for value in sample["reconstruction"]]
        assert residual == [exact_fraction(value) for value in sample["residuals"]]
        for component in range(2):
            assert sum(design[band][component] * residual[band] for band in range(3)) == 0
    noisy = reference["samples"][2]
    assert noisy["abundance_sum"] == "54/55"
    assert sum(exact_fraction(value) for value in noisy["abundances"]) != 1
    clean_mixture = [Fraction(2, 5), Fraction(3, 5)]
    clean_observation = [
        sum(design[band][component] * clean_mixture[component] for component in range(2))
        for band in range(3)
    ]
    noisy_input = [exact_fraction(value) for value in noisy["input"]]
    noise = [noisy_input[band] - clean_observation[band] for band in range(3)]
    assert noise == [exact_fraction(value) for value in noisy["noise"]]
    assert noisy_input == [exact_fraction(data["pixel_values"][band][2]) for band in data["bands"]]
    assert exact_fraction(reference["samples"][3]["abundances"][0]) < 0
    assert shape(data["scene_geometry"]).covers(Point(*data["pixel_centers"][4]))
    assert not shape(data["scene_geometry"]).covers(Point(*data["pixel_centers"][5]))
    assert data["pixel_values"]["red"][4] is None


def test_sdk_raster_unmixing_compiles_evaluates_and_preserves_common_masks():
    data = fixture()
    module = example_module()
    assert module.BANDS == data["bands"]
    assert module.DESIGN_MATRIX == data["design_matrix"]
    assert module.ENDMEMBER_BANDS == data["endmember_bands"]
    catalog = [{"id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["bands"]}}}]
    item = {"id": data["item_id"], "bbox": data["bbox"],
        "geometry": data["scene_geometry"],
        "properties": {"system:index": data["item_id"], "system:time_start": 1}}
    items = {data["collection_id"]: [item]}
    arrays = {data["item_id"]: {
        band: np.asarray([np.nan if value is None else value for value in data["pixel_values"][band]],
                         dtype=np.float64)
        for band in data["bands"]
    }}
    geometries = {data["item_id"]: data["scene_geometry"]}

    with OfflineGuard() as guard:
        ee = make_ee()
        source = ee.ImageCollection(data["collection_id"]).first()
        outputs = module.build_least_squares(ee, source)
        compiled = {
            name: compile_expression(sdk_encode(ee, image), catalog, items)
            for name, image in outputs.items()
        }

    assert guard.evidence()["attempt_count"] == 0
    assert set(compiled) == {"abundances", "reconstruction", "residuals"}
    expected = independent_reference(data)
    expected_names = {
        "abundances": data["endmember_bands"],
        "reconstruction": data["bands"],
        "residuals": data["bands"],
    }
    for name, result in compiled.items():
        validate(result["process_graph"])
        assert result["kind"] == "image"
        assert result["bands"] == expected_names[name]
        assert result["source_item_ids"] == [data["item_id"]]
        actual, band_names, timed = evaluate_graph(
            result, arrays, grid=data["pixel_centers"], source_geometries=geometries,
        )
        assert band_names == expected_names[name] and timed is False
        np.testing.assert_allclose(actual, expected[name], atol=2e-6, rtol=2e-6, equal_nan=True)

    estimated = compiled["abundances"]
    assert estimated["has_time_dimension"] is False
    actual_abundance, _, _ = evaluate_graph(
        estimated, arrays, grid=data["pixel_centers"], source_geometries=geometries,
    )
    assert actual_abundance[0, 2] == pytest.approx(119 / 220, abs=2e-6)
    assert actual_abundance[1, 2] == pytest.approx(97 / 220, abs=2e-6)
    assert actual_abundance[0, 3] < 0  # Unconstrained least squares does not clamp fractions.
    assert np.isnan(actual_abundance[:, 4]).all()  # Missing red masks the full array vector.
    assert np.isnan(actual_abundance[:, 5]).all()  # Scene geometry masks the outside pixel.


def test_raster_solver_requires_explicit_float_inputs_full_rank_and_known_parameters():
    data = fixture()
    ee = make_ee()
    source = ee.ImageCollection(data["collection_id"]).first()
    observations = source.select(data["bands"]).toArray().toArray(1).toFloat()
    design = ee.Image(ee.Array(data["design_matrix"]))
    catalog = [{"id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["bands"]}}}]
    item = {"id": data["item_id"], "bbox": data["bbox"],
        "geometry": data["scene_geometry"],
        "properties": {"system:index": data["item_id"]}}
    items = {data["collection_id"]: [item]}

    def compile_value(value):
        return compile_expression(sdk_encode(ee, value), catalog, items)

    def flattened(value):
        return value.arrayProject([0]).arrayFlatten([data["endmember_bands"]])

    with pytest.raises(UnsupportedEEError, match="explicit top-level toFloat"):
        compile_value(flattened(design.matrixSolve(observations)))

    typed_design = design.toFloat()
    untyped_observations = source.select(data["bands"]).toArray().toArray(1)
    with pytest.raises(UnsupportedEEError, match="explicit top-level toFloat"):
        compile_value(flattened(typed_design.matrixSolve(untyped_observations)))

    deficient = ee.Image(ee.Array([[1, 2], [2, 4], [3, 6]])).toFloat()
    with pytest.raises(UnsupportedEEError, match="full column rank"):
        compile_value(flattened(deficient.matrixSolve(observations)))

    valid_expression = sdk_encode(ee, flattened(typed_design.matrixSolve(observations)))
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(add_unknown_matrix_solve_argument(valid_expression), catalog, items)
