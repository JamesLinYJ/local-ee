"""Shared fixture builders and compiler probes for RF workflow tests."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ee_rf_validation_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-rf-validation-workflow-v1.json"
EXAMPLE_PATH = ROOT / "examples/32_GEE_python_rf_validation.py"
RF_ROWS = "local_ee_train_smile_rf_rows"
RF_SAMPLES = "local_ee_train_smile_rf_samples"
RF_CLASSIFY_ROWS = "local_ee_smile_rf_classify_rows"
RF_CLASSIFY_SAMPLES = "local_ee_smile_rf_classify_samples"
RF_CONFUSION = "local_ee_smile_rf_confusion"
ERROR_MATRIX = "local_ee_error_matrix"
CONFUSION_VALUE = "local_ee_confusion_value"
SAMPLE = "local_ee_sample_regions"
SAMPLE_OP = "local_ee_sample_table_op"
ACCESSOR_OPERATION = {
    "array": "array", "order": "order", "accuracy": "accuracy",
    "kappa": "kappa", "consumers_accuracy": "consumersAccuracy",
    "producers_accuracy": "producersAccuracy", "fscore_beta_2": "fscore",
}


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def example_module():
    spec = importlib.util.spec_from_file_location("rf_validation_example", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def local_metadata(data):
    grid = data["grid"]
    xmin, ymin, xmax, ymax = grid["extent"]
    scene_id = data["training_scene_id"]
    geometry = {
        "type": "Polygon",
        "coordinates": [[[xmin, ymin], [xmax, ymin], [xmax, ymax],
                         [xmin, ymax], [xmin, ymin]]],
    }
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": list(data["training_pixel_values"])}},
    }]
    item = {
        "id": scene_id,
        "bbox": grid["extent"],
        "geometry": geometry,
        "properties": {"system:index": scene_id},
    }
    return catalog, {data["collection_id"]: [item]}


def encode(ee, value):
    return ee.serializer.encode(value, is_compound=True, for_cloud_api=False)


def semantic_wire(value, key=None):
    """Compare parsed SDK wire data while retaining the exact model contract."""
    if key in {"spec", "rows"} and type(value) is str:
        value = json.loads(value)
    if type(value) is dict:
        return {name: semantic_wire(item, name) for name, item in value.items()}
    if type(value) is list:
        return [semantic_wire(item) for item in value]
    if type(value) is int:
        if abs(value) <= 2**53:
            return ("number", float(value).hex())
        return ("integer", str(value))
    if type(value) is float:
        return ("number", value.hex())
    return value


def compile_value(ee, value, local):
    return compile_expression(encode(ee, value), local[0], local[1])


def nodes(graph, process_id):
    return [(key, node) for key, node in graph.items()
            if node["process_id"] == process_id]


def compile_workflow(ee, module, data, metadata, mode):
    workflow = module.build_workflow(ee, data, mode)
    descriptors = {
        "training_predictions": compile_value(
            ee, workflow["training_predictions"], metadata,
        ),
        "validation_predictions": compile_value(
            ee, workflow["validation_predictions"], metadata,
        ),
        "training_values": {
            name: compile_value(ee, value, metadata)
            for name, value in workflow["training_values"].items()
        },
        "validation_values": {
            name: compile_value(ee, value, metadata)
            for name, value in workflow["validation_values"].items()
        },
    }
    return workflow, descriptors


def trainer_nodes(graph):
    return nodes(graph, RF_ROWS), nodes(graph, RF_SAMPLES)


@pytest.fixture(scope="module")
def javascript_workflows():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for official JavaScript SDK serialization parity")
    result = subprocess.run([node, "-e", JAVASCRIPT], cwd=ROOT,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["attempts"] == 0
    return output["outputs"]


def compile_cross_sdk_workflows(ee, javascript_workflows):
    data = load_fixture()
    metadata = local_metadata(data)
    module = example_module()
    python = {}
    for mode in ("inline", "sampled"):
        workflow = module.build_workflow(ee, data, mode)
        expressions = {
            "training_predictions": workflow["training_predictions"],
            "validation_predictions": workflow["validation_predictions"],
            "training_values": workflow["training_values"],
            "validation_values": workflow["validation_values"],
        }
        python[mode] = {
            "training_predictions": encode(ee, expressions["training_predictions"]),
            "validation_predictions": encode(ee, expressions["validation_predictions"]),
            "training_values": {
                name: encode(ee, value)
                for name, value in expressions["training_values"].items()
            },
            "validation_values": {
                name: encode(ee, value)
                for name, value in expressions["validation_values"].items()
            },
        }
    python_descriptors = {
        mode: {
            key: (
                {name: compile_expression(value, *metadata) for name, value in encoded.items()}
                if key.endswith("_values") else compile_expression(encoded, *metadata)
            )
            for key, encoded in output.items()
        }
        for mode, output in python.items()
    }
    javascript_descriptors = {
        mode: {
            key: (
                {name: compile_expression(value, *metadata) for name, value in encoded.items()}
                if key.endswith("_values") else compile_expression(encoded, *metadata)
            )
            for key, encoded in output.items()
        }
        for mode, output in javascript_workflows.items()
    }
    return python_descriptors, javascript_descriptors
