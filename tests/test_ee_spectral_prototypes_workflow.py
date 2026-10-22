"""Official-SDK spectral distance selection with static synthetic prototypes."""
from decimal import Decimal, localcontext
from fractions import Fraction
import importlib.util
import json
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
EXAMPLE_PATH = ROOT / "examples/24_GEE_python_spectral_prototypes.py"
PROTOTYPE_IDS = ["prototype_0", "prototype_1", "prototype_2"]


def fixture():
    return json.loads((ROOT / "tests/fixtures/ee-spectral-prototypes-v1.json").read_text())


def example_module():
    spec = importlib.util.spec_from_file_location("spectral_prototype_example", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def local_data(data):
    item = {
        "id": data["frame_id"],
        "bbox": data["bbox"],
        "geometry": data["scene_geometry"],
        "properties": {
            "system:index": data["frame_id"],
            "system:time_start": data["frame_time_millis"],
        },
    }
    arrays = {
        data["frame_id"]: {
            band: np.asarray([
                np.nan if value is None else value for value in data["pixel_values"][band]
            ], dtype=np.float64)
            for band in data["bands"]
        }
    }
    return {
        "catalog": [{
            "id": data["collection_id"],
            "cube:dimensions": {"bands": {"values": data["bands"]}},
        }],
        "items": {data["collection_id"]: [item]},
        "arrays": arrays,
        "geometries": {data["frame_id"]: data["scene_geometry"]},
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


def resolve_sdk_reference(encoded, value):
    scope = dict(encoded.get("scope", []))

    def resolve(node):
        if isinstance(node, dict):
            if node.get("type") == "ValueRef":
                return resolve(scope[node["value"]])
            if node.get("type") == "Invocation":
                return {
                    "type": "Invocation",
                    "functionName": node["functionName"],
                    "arguments": resolve(node.get("arguments", {})),
                }
            return {key: resolve(child) for key, child in node.items()}
        if isinstance(node, list):
            return [resolve(child) for child in node]
        if isinstance(node, tuple):
            return tuple(resolve(child) for child in node)
        return node

    return resolve(value)


def exact_references(data):
    pixels = len(data["pixel_centers"])
    distances = np.full((len(data["prototype_ids"]), pixels), np.nan)
    scores = np.full_like(distances, np.nan)
    selected = np.full((1, pixels), np.nan)
    exact_distances = [None] * pixels
    exact_selected = [None] * pixels
    decimal_distances = [None] * pixels
    prototypes = [[Fraction(str(value)) for value in vector]
                  for vector in data["prototype_vectors"]]
    geometry = shape(data["scene_geometry"])
    for pixel, point in enumerate(data["pixel_centers"]):
        if not geometry.covers(Point(*point)):
            continue
        observation = [data["pixel_values"][band][pixel] for band in data["bands"]]
        if any(value is None for value in observation):
            continue
        spectrum = [Fraction(str(value)) for value in observation]
        exact = [sum(((value - center) ** 2 for value, center in zip(spectrum, prototype)), Fraction(0))
                 for prototype in prototypes]
        reference = [str(value) for value in exact]
        assert reference == data["hand_reference"]["squared_distances_by_pixel"][pixel]
        exact_distances[pixel] = reference
        exact_selected[pixel] = exact.index(min(exact))
        distances[:, pixel] = [float(value) for value in exact]
        scores[:, pixel] = [-float(value) for value in exact]
        selected[0, pixel] = exact_selected[pixel]

        with localcontext() as context:
            context.prec = 50
            observed32 = [Decimal.from_float(float(np.float32(value))) for value in observation]
            prototypes32 = [[Decimal.from_float(float(np.float32(value))) for value in row]
                            for row in data["prototype_vectors"]]
            decimal_distances[pixel] = [
                sum(((value - center) ** 2 for value, center in zip(observed32, prototype)), Decimal(0))
                for prototype in prototypes32
            ]
    assert exact_selected == data["hand_reference"]["selected_prototype_by_pixel"]
    assert exact_distances == data["hand_reference"]["squared_distances_by_pixel"]
    with localcontext() as context:
        context.prec = 50
        for pixel, exact in enumerate(exact_distances):
            if exact is None:
                assert decimal_distances[pixel] is None
                continue
            for decimal_value, rational_text in zip(decimal_distances[pixel], exact):
                rational = Fraction(rational_text)
                assert decimal_value == Decimal(rational.numerator) / Decimal(rational.denominator)
    return {
        "distances": distances,
        "scores": scores,
        "selected_index": selected,
        "decimal_distances": decimal_distances,
    }


def numpy_reference(data):
    pixels = len(data["pixel_centers"])
    distances = np.full((len(data["prototype_ids"]), pixels), np.nan)
    selected = np.full((1, pixels), np.nan)
    geometry = shape(data["scene_geometry"])
    prototypes = np.asarray(data["prototype_vectors"], dtype=np.float32)
    for pixel, point in enumerate(data["pixel_centers"]):
        if not geometry.covers(Point(*point)):
            continue
        observation = [data["pixel_values"][band][pixel] for band in data["bands"]]
        if any(value is None for value in observation):
            continue
        spectrum = np.asarray(observation, dtype=np.float32)
        delta = spectrum[None, :] - prototypes
        squared = np.sum(np.square(delta, dtype=np.float32), axis=1, dtype=np.float32)
        distances[:, pixel] = squared
        selected[0, pixel] = np.argmax(-squared)
    return {"distances": distances, "scores": -distances, "selected_index": selected}


def test_fraction_decimal_references_and_first_tie_contract():
    data = fixture()
    module = example_module()
    assert data["schema"] == module.SYNTHETIC_VERSION
    exact = exact_references(data)
    assert exact["distances"][:, 0].tolist() == [0, 1 / 8, 1 / 4]
    assert exact["distances"][:, 1].tolist() == [1 / 8, 0, 1 / 8]
    assert exact["distances"][:, 2].tolist() == [1 / 4, 1 / 8, 0]
    assert exact["distances"][:, 3].tolist() == [1 / 32, 1 / 32, 5 / 32]
    assert exact["selected_index"][0, :5].tolist() == [0, 1, 2, 0, 0]
    assert exact["scores"][:, 0].max() == 0
    assert (exact["scores"][:, 4] < 0).all()
    assert exact["selected_index"][0, 3] == 0  # Equal exact distances choose the first prototype.
    assert exact["decimal_distances"][3][0] == exact["decimal_distances"][3][1]

    missing = data["hand_reference"]["joint_missing_pixel_index"]
    assert np.isnan(exact["distances"][:, missing]).all()
    outside = data["pixel_centers"][data["hand_reference"]["outside_geometry_pixel_index"]]
    west, south, east, north = data["bbox"]
    assert west <= outside[0] <= east and south <= outside[1] <= north
    assert not shape(data["scene_geometry"]).covers(Point(*outside))


def test_workflow_rejects_wrong_prototype_count_ids_and_vector_shapes():
    data = fixture()
    module = example_module()
    ee = make_ee()
    collection = ee.ImageCollection(data["collection_id"])
    with pytest.raises(ValueError, match="exactly three"):
        module.build_prototype_selection(
            ee, collection, data["prototype_ids"][:2], data["prototype_vectors"][:2],
        )
    with pytest.raises(ValueError, match="two-band"):
        module.build_prototype_selection(
            ee, collection, data["prototype_ids"], [[0.1], *data["prototype_vectors"][1:]],
        )
    with pytest.raises(ValueError, match="unique"):
        module.build_prototype_selection(
            ee, collection, ["prototype_0", "prototype_0", "prototype_2"],
            data["prototype_vectors"],
        )


def test_official_sdk_prototype_distances_compile_and_match_fraction_decimal_numpy():
    data = fixture()
    local = local_data(data)
    module = example_module()
    with OfflineGuard() as guard:
        ee = make_ee()
        outputs = module.build_prototype_selection(
            ee, ee.ImageCollection(data["collection_id"]),
            data["prototype_ids"], data["prototype_vectors"],
        )
        compiled = {name: compile_value(ee, value, local) for name, value in outputs.items()}
        encoded = {name: encode(ee, value) for name, value in outputs.items()}
    assert guard.evidence()["attempt_count"] == 0
    assert compiled["source_ids"]["value"] == [data["frame_id"]]
    assert compiled["distances"]["bands"] == PROTOTYPE_IDS
    assert compiled["scores"]["bands"] == PROTOTYPE_IDS
    assert compiled["selected_index"]["bands"] == ["selected_prototype_index"]
    for result in compiled.values():
        if result["kind"] == "image":
            validate(result["process_graph"])
            assert len(result["process_graph"]) <= 500
            assert result["source_item_ids"] == [data["frame_id"]]

    calls = {
        name: [call for graph in encoded.values() for call in find_invocations(graph, name)]
        for name in (
            "Image.toArray", "Image.arrayReduce", "Image.arrayCat",
            "Image.arrayArgmax", "Array.argmax",
        )
    }
    assert calls["Image.toArray"] and calls["Image.toArray"][0]["arguments"]["axis"] == 0
    selected_calls = {
        name: find_invocations(encoded["selected_index"], name)
        for name in ("Image.arrayReduce", "Image.arrayCat", "Image.arrayArgmax")
    }
    assert len(selected_calls["Image.arrayReduce"]) == 3
    for call in selected_calls["Image.arrayReduce"]:
        arguments = resolve_sdk_reference(encoded["selected_index"], call["arguments"])
        assert arguments["axes"] == [0]
        assert arguments["reducer"]["functionName"] == "Reducer.sum"
    assert len(selected_calls["Image.arrayCat"]) == 2
    assert all(call["arguments"]["axis"] == 0
               for call in selected_calls["Image.arrayCat"])
    assert calls["Image.arrayArgmax"] and calls["Array.argmax"]
    assert compiled["calibration_tie_index"]["value"] == [0]

    exact = exact_references(data)
    numpy = numpy_reference(data)
    for name, band_names in (
        ("distances", PROTOTYPE_IDS), ("scores", PROTOTYPE_IDS),
        ("selected_index", ["selected_prototype_index"]),
    ):
        values, names, timed = evaluate_graph(
            compiled[name], local["arrays"], grid=local["grid"],
            source_geometries=local["geometries"],
        )
        assert names == band_names and timed is False
        np.testing.assert_allclose(values, exact[name], atol=2e-7, rtol=2e-7, equal_nan=True)
        np.testing.assert_allclose(values, numpy[name], atol=2e-7, rtol=2e-7, equal_nan=True)
    selected = evaluate_graph(
        compiled["selected_index"], local["arrays"], grid=local["grid"],
        source_geometries=local["geometries"],
    )[0]
    assert selected[0, :5].tolist() == [0, 1, 2, 0, 0]
    assert np.isnan(selected[:, 5:]).all()
