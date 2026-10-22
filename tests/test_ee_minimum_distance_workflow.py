"""Independent held-out-label evidence for an actual trained class-mean model."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / "tests/fixtures/ee-minimum-distance-v1.json").read_text())


def test_trained_model_resubstitution_and_independent_validation_labels():
    data = fixture()
    spec = importlib.util.spec_from_file_location("minimum_distance_example",
        ROOT / "examples/15_GEE_python_minimum_distance_validation.py")
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    assert example.SYNTHETIC_VERSION == data["schema"]
    assert example.INPUT_PROPERTIES == data["input_properties"]
    assert example.TRAINING_ROWS == data["training"]
    assert example.VALIDATION_ROWS == data["validation"]
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        training = ee.FeatureCollection([ee.Feature(None, row) for row in data["training"]])
        validation = ee.FeatureCollection([ee.Feature(None, row) for row in data["validation"]])
        expression = example.build_validation(ee, training, validation)
        value = compile_expression(ee.serializer.encode(expression, for_cloud_api=False), [], {})["value"]
    assert value["schema"] == data["input_properties"]
    assert value["training_confusion"] == data["training_confusion"]
    assert value["training_accuracy"] == pytest.approx(5/6, abs=1e-15)
    assert value["predictions"] == data["predictions"]
    assert value["validation_confusion"] == data["validation_confusion"]
    assert value["validation_accuracy"] == pytest.approx(3/5, abs=1e-15)
    assert value["validation_kappa"] == pytest.approx(1/6, abs=1e-15)
    assert guard.evidence()["attempt_count"] == 0


def test_reference_separates_training_from_validation_and_uses_means_not_one_nn():
    data = fixture()
    schema = data["input_properties"]
    labels = [1, 3]
    means = np.array([[np.mean([row[key] for row in data["training"]
        if row["landcover"] == label]) for key in schema] for label in labels])
    np.testing.assert_allclose(means, [[2, 2/3], [7, 2/3]], atol=1e-15, rtol=0)
    samples = np.array([[row[key] for key in schema] for row in data["validation"]])
    squared_distances = np.sum((samples[:, None, :] - means[None, :, :])**2, axis=2)
    assert np.all(squared_distances[:, 0] != squared_distances[:, 1])
    assert [labels[index] for index in np.argmin(squared_distances, axis=1)] == data["predictions"]
    # The training outlier is its own nearest training observation of class 1,
    # but the mathematically nearest class mean is class 3.
    outlier = np.array([6, 0])
    assert np.argmin(np.sum((means - outlier)**2, axis=1)) == 1
