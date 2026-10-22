"""Raw-grid references and bounded test-only evaluators for wave28 workflows."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from shapely.geometry import Point, shape

from ee_image_sample_reference import (
    cell_center, class_frequencies, grid_centers, reference_sample_rows,
    reference_training_rows,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-image-sample-rf-v1.json"
EXAMPLE_PATH = ROOT / "examples/33_GEE_python_image_sample.py"
SAMPLE = "local_ee_sample_regions"
SAMPLE_OP = "local_ee_sample_table_op"
RF_ROWS = "local_ee_train_smile_rf_rows"
RF_SAMPLES = "local_ee_train_smile_rf_samples"
RF_CLASSIFY_IMAGE = "local_ee_smile_rf"
RF_CLASSIFY_ROWS = "local_ee_smile_rf_classify_rows"
RF_CONFUSION = "local_ee_smile_rf_confusion"
ERROR_MATRIX = "local_ee_error_matrix"
CONFUSION_VALUE = "local_ee_confusion_value"
ACCESSORS = {
    "array": "array", "order": "order", "accuracy": "accuracy",
    "kappa": "kappa", "consumers_accuracy": "consumersAccuracy",
    "producers_accuracy": "producersAccuracy", "fscore_beta_2": "fscore",
}
def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def example_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("image_sample_example", EXAMPLE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_metadata(data):
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["catalog_bands"]}},
    }]
    items = {data["collection_id"]: [{
        key: row[key] for key in ("id", "bbox", "geometry", "properties")
    } for row in data["items"]]}
    arrays = {item["id"]: {
        band: np.asarray([
            np.nan if value is None else value
            for value in item["pixel_values"][band]
        ], dtype=np.float64)
        for band in data["catalog_bands"]
    } for item in data["items"]}
    geometries = {item["id"]: item["geometry"] for item in data["items"]}
    return catalog, items, arrays, geometries


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def compile_value(ee, value, metadata):
    from gee.ee_translate import compile_expression

    return compile_expression(encode(ee, value), metadata[0], metadata[1])


def nodes(graph, process_id):
    return [(key, node) for key, node in graph.items()
            if node["process_id"] == process_id]


def _sample_process(data, arguments, values):
    """Test-only graph evaluator, checked against the raw-grid reference."""
    from gee.image_sampling_spec import decode_image_sample_spec

    spec = decode_image_sample_spec(arguments["spec"])
    cube, names, timed = values[arguments["data"]["from_node"]]
    if timed:
        raise AssertionError("Image.sample fixture expects one untimed image")
    matrix = np.asarray(cube, dtype=np.float64)
    rows, cols = data["grid"]["shape_rows_columns"]
    if matrix.shape != (len(names), rows * cols):
        raise AssertionError("Image.sample source dimensions differ from the fixture")
    if names != spec["bands"]:
        raise AssertionError("Image.sample source bands differ from declared band order")
    image_options = spec["image_sample"]
    region_feature = spec["regions"]["features"][0]
    region = shape(region_feature["geometry"])
    candidates = []
    for row in range(rows):
        for col in range(cols):
            x, y = cell_center(data, row, col)
            if region.covers(Point(x, y)):
                candidates.append((row, col, x, y))
    population = len(candidates)
    probability = 1.0
    if image_options["factor"] is not None:
        probability = image_options["factor"]
    elif image_options["num_pixels"] is not None and population:
        probability = min(1.0, image_options["num_pixels"] / population)
    selected = [cell for cell in candidates
                if _workflow_grid_uniform(image_options["seed"], cell[0], cell[1]) < probability]
    output = []
    for row, col, x, y in selected:
        pixel = row * cols + col
        sampled = []
        for band in spec["bands"]:
            value = float(matrix[names.index(band), pixel])
            if np.isinf(value):
                raise ValueError("Image.sample fixture contains infinity")
            sampled.append(None if np.isnan(value) else value)
        if image_options["drop_nulls"] and any(value is None for value in sampled):
            continue
        feature = {
            "type": "Feature",
            "id": f"f0_r{row}_c{col}",
            "geometry": {"type": "Point", "coordinates": [x, y]}
                if spec["geometries"] else None,
            "properties": dict(zip(spec["bands"], sampled)),
        }
        output.append(feature)
    return {"type": "FeatureCollection", "features": output}


def _predicate_matches(predicate, properties):
    name, arguments = predicate["name"], predicate["arguments"]
    if name == "notNull":
        return all(properties.get(key) is not None for key in arguments["properties"])
    if name in {"greaterThan", "greaterThanOrEquals"}:
        left = properties.get(arguments.get("leftField"))
        right = arguments.get("rightValue")
        if left is None or right is None:
            return False
        return left > right if name == "greaterThan" else left >= right
    raise AssertionError(f"Unexpected workflow filter: {name}")


def _sample_operation(arguments, values):
    """Bounded evaluator for the workflow's notNull/filter/limit chain."""
    table = values[arguments["data"]["from_node"]]
    spec = json.loads(arguments["spec"])
    features = table["features"]
    if len(features) > 1000:
        raise AssertionError("Workflow oracle exceeded the sample row limit")
    if spec["operation"] == "filter":
        features = [feature for feature in features
                    if _predicate_matches(spec["predicate"], feature["properties"])]
    elif spec["operation"] == "limit":
        count = spec["count"]
        if count is not None:
            features = features[:count]
    else:
        raise AssertionError(f"Unexpected sample table operation: {spec['operation']}")
    return {"type": "FeatureCollection", "features": features}


def graph_process_handlers(data):
    return {SAMPLE: lambda arguments, values: _sample_process(data, arguments, values),
            SAMPLE_OP: _sample_operation}


def compiled_sampling_spec(descriptor):
    nodes_for_sample = nodes(descriptor["process_graph"], SAMPLE)
    assert len(nodes_for_sample) == 1
    return json.loads(nodes_for_sample[0][1]["arguments"]["spec"])


def _workflow_grid_uniform(seed, row, col):
    """Separate graph-oracle hash implementation for reference cross-checks."""
    mask = (1 << 64) - 1

    def mix(word):
        word &= mask
        word = ((word ^ (word >> 30)) * 0xBF58476D1CE4E5B9) & mask
        word = ((word ^ (word >> 27)) * 0x94D049BB133111EB) & mask
        return (word ^ (word >> 31)) & mask

    word = ((seed & mask) ^ mix(col + 0x9E3779B97F4A7C15)
            ^ mix(row + 0xD1B54A32D192ED03)) & mask
    return (mix(word) >> 11) / (1 << 53)
