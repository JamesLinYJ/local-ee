"""Synthetic source data and non-production oracles for raster classification."""
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from pathlib import Path

import numpy as np
from shapely.geometry import Point, shape


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-raster-classification-v1.json"
PROCESS_ID = "local_ee_minimum_distance"


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text())


def compile_inputs(data):
    """Build compiler metadata and sample arrays from the synthetic fixture."""
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["catalog_bands"]}},
    }]
    items = {data["collection_id"]: [{
        key: row[key] for key in ("id", "bbox", "geometry", "properties")
    } for row in data["items"]]}
    arrays = {
        item["id"]: {
            band: np.asarray([
                np.nan if value is None else value
                for value in item["pixel_values"][band]
            ], dtype=np.float64)
            for band in data["catalog_bands"]
        }
        for item in data["items"]
    }
    geometries = {item["id"]: item["geometry"] for item in data["items"]}
    return catalog, items, arrays, geometries


def fraction(value):
    if isinstance(value, int):
        return Fraction(value)
    return Fraction.from_float(float(value))


def _distance(metric, query, center):
    if metric == "euclidean":
        return sum(((left - right) ** 2 for left, right in zip(query, center)), Fraction(0))
    if metric == "manhattan":
        return sum((abs(left - right) for left, right in zip(query, center)), Fraction(0))
    raise AssertionError(metric)


def _fraction_decimal(value):
    return Decimal(value.numerator) / Decimal(value.denominator)


def _cosine_similarity(query, center):
    q = [_fraction_decimal(value) for value in query]
    c = [_fraction_decimal(value) for value in center]
    dot = sum((left * right for left, right in zip(q, c)), Decimal(0))
    q_norm = sum((value * value for value in q), Decimal(0)).sqrt()
    c_norm = sum((value * value for value in c), Decimal(0)).sqrt()
    if not q_norm or not c_norm:
        raise ValueError("cosine sample reference needs nonzero vectors")
    return dot / (q_norm * c_norm)


def _independent_prediction(metric, query, labels, centers):
    if metric == "cosine":
        with localcontext() as context:
            context.prec = 80
            scores = [(_cosine_similarity(query, center), label)
                      for label, center in zip(labels, centers)]
            scores.sort(reverse=True)
    else:
        scores = [(_distance(metric, query, center), label)
                  for label, center in zip(labels, centers)]
        scores.sort()
    if len(scores) > 1 and scores[0][0] == scores[1][0]:
        raise ValueError("fixture unexpectedly contains an equal-distance prediction")
    return scores[0][1]


def independent_reference(data, metric):
    """Compute expected labels from raw fixture rows, never compiler model code."""
    schema = data["input_properties"]
    grouped = {}
    for row in data["training_rows"]:
        grouped.setdefault(row[data["class_property"]], []).append(
            [fraction(row[name]) for name in schema]
        )
    labels = sorted(grouped)
    centers = [
        [sum((sample[axis] for sample in grouped[label]), Fraction(0))
         / len(grouped[label]) for axis in range(len(schema))]
        for label in labels
    ]

    output = np.full((len(data["items"]), 1, len(data["pixel_centers"])),
                     np.nan, dtype=np.float64)
    for scene_index, item in enumerate(data["items"]):
        geometry = shape(item["geometry"])
        for pixel_index, center_point in enumerate(data["pixel_centers"]):
            if not geometry.covers(Point(*center_point)):
                continue
            query = [item["pixel_values"][name][pixel_index] for name in schema]
            if any(value is None for value in query):
                continue
            if any(not np.isfinite(float(value)) for value in query):
                raise ValueError("finite source sample expected in classification oracle")
            output[scene_index, 0, pixel_index] = _independent_prediction(
                metric, [fraction(value) for value in query], labels, centers,
            )
    return output


def sample_process_handler(arguments, values):
    """Test oracle for a declared process graph; this is not native execution."""
    data, names, timed = values[arguments["data"]["from_node"]]
    model = arguments["model"]
    if set(model) != {"version", "metric", "schema", "labels", "centers"}:
        raise AssertionError("classifier wire keys changed")
    if model["version"] != 1 or names != model["schema"]:
        raise AssertionError("classifier process data must use the exact wire schema order")
    if not timed:
        data = np.expand_dims(data, axis=0)
    if data.ndim != 3 or data.shape[1] != len(model["schema"]):
        raise AssertionError("sample cube shape does not match classifier schema")

    centers = [
        [Fraction(int(pair[0]), int(pair[1])) for pair in row]
        for row in model["centers"]
    ]
    labels = model["labels"]
    output = np.full((data.shape[0], 1, data.shape[2]), np.nan, dtype=np.float64)
    for time_index in range(data.shape[0]):
        for pixel_index in range(data.shape[2]):
            query_values = data[time_index, :, pixel_index]
            if np.isinf(query_values).any():
                raise ValueError("non-finite infinite classifier input is rejected")
            if np.isnan(query_values).any():
                continue
            query = [Fraction.from_float(float(value)) for value in query_values]
            output[time_index, 0, pixel_index] = _independent_prediction(
                model["metric"], query, labels, centers,
            )
    return (output if timed else output[0]), ["v"], timed


PROCESS_HANDLERS = {PROCESS_ID: sample_process_handler}


def classifier_node(result):
    nodes = [node for node in result["process_graph"].values()
             if node["process_id"] == PROCESS_ID]
    if len(nodes) != 1:
        raise AssertionError(f"expected one {PROCESS_ID} node, got {len(nodes)}")
    return nodes[0]
