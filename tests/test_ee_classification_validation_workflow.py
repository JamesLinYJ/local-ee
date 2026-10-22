"""Label-table validation against independent class frequencies and chance."""
from collections import Counter
import importlib.util
import json
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


def test_versioned_classification_validation_uses_explicit_order_and_valid_rows():
    fixture = json.loads((ROOT / "tests/fixtures/ee-classification-validation-v1.json").read_text())
    spec = importlib.util.spec_from_file_location("classification_validation_example",
        ROOT / "examples/13_GEE_python_synthetic_classification_validation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SYNTHETIC_VERSION == fixture["schema"]
    assert module.CLASS_ORDER == fixture["order"]
    assert module.SAMPLE_ROWS == fixture["rows"]
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        rows = ee.FeatureCollection([ee.Feature(None, row) for row in fixture["rows"]])
        expression = module.build_validation(ee, rows)
        value = compile_expression(ee.serializer.encode(expression, for_cloud_api=False), [], {})["value"]
    expected = fixture["independent_reference"]
    assert value["class_order"] == fixture["order"]
    assert value["matrix"] == expected["matrix"]
    assert value["complete_rows"] == expected["complete_rows"]
    assert value["evaluated_rows"] == expected["evaluated_rows"]
    assert value["accuracy"] == pytest.approx(12 / 17, abs=1e-15)
    assert value["kappa"] == pytest.approx(107 / 192, abs=1e-15)
    assert guard.evidence()["attempt_count"] == 0


def test_reference_uses_independent_label_frequencies_and_chance_agreement():
    fixture = json.loads((ROOT / "tests/fixtures/ee-classification-validation-v1.json").read_text())
    classes = set(fixture["order"])
    rows = [(row["actual"], row["predicted"]) for row in fixture["rows"]
            if row.get("actual") in classes and row.get("predicted") in classes]
    actual = Counter(a for a, _ in rows)
    predicted = Counter(p for _, p in rows)
    agreement = sum(a == p for a, p in rows) / len(rows)
    chance = sum((actual[label] / len(rows)) * (predicted[label] / len(rows)) for label in classes)
    assert len(rows) == 17
    assert agreement == pytest.approx(12 / 17, abs=1e-15)
    assert (agreement - chance) / (1 - chance) == pytest.approx(107 / 192, abs=1e-15)
