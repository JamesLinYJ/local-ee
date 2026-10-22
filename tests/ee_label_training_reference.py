"""Independent raw-fixture references and test-only compiled-graph handlers.

Numerical expectations are derived from raw JSON arrays, Shapely cell geometry,
exact Fractions, and Decimal cosine scores. The oracle never imports the
production remap, sample-table filter, or minimum-distance trainer.
"""
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from pathlib import Path

import numpy as np
from shapely.geometry import Point, shape

from ee_sampling_workflow_helpers import (
    _cell,
    _reference_cells,
    compile_inputs as _compile_inputs,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-label-training-v1.json"


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text())


def compile_inputs(data):
    """Reuse only the old raw-input packaging helper; no EE result is added."""
    return _compile_inputs(data)


def reference_sample_rows(data, geometries=True, diagnostics=False):
    """N sampleRegions result from raw cells, remapped labels, and source data."""
    item = data["items"][0]
    label_map = dict(zip(data["label_remap"]["from"], data["label_remap"]["to"]))
    output = []
    counts = {"selected_cells": 0, "unmapped_labels": 0, "source_nodata": 0}
    for feature_index, feature in enumerate(data["training_features"]):
        properties = feature["properties"]
        for row, col in _reference_cells(data, feature["geometry"]):
            counts["selected_cells"] += 1
            pixel = row * data["grid"]["shape_rows_columns"][1] + col
            label_code = item["pixel_values"][data["label_remap"]["band"]][pixel]
            if label_code not in label_map:
                counts["unmapped_labels"] += 1
                continue
            bands = [data["class_property"], *data["input_properties"]]
            values = [label_map[label_code], *(
                item["pixel_values"][band][pixel] for band in data["input_properties"]
            )]
            if any(value is None for value in values):
                counts["source_nodata"] += 1
                continue
            if not all(np.isfinite(float(value)) for value in values):
                raise ValueError("Fixture selected a non-finite sample")
            x, y, _ = _cell(data, row, col)
            copied = {name: properties[name] for name in data["sample_properties"]}
            copied.update(dict(zip(bands, values)))
            output.append({
                "feature": feature_index,
                "row": row,
                "col": col,
                "id": f"f{feature_index}_r{row}_c{col}",
                "x": x,
                "y": y,
                "values": values,
                "properties": copied,
                "geometry": {"type": "Point", "coordinates": [x, y]}
                if geometries else None,
            })
    return (output, counts) if diagnostics else output


def reference_filter_stages(data, geometries=True):
    """Independently retain candidates at each ordered filter/limit stage."""
    filter_data = data["sample_filter"]
    required = filter_data["not_null"]
    candidates = reference_sample_rows(data, geometries=geometries)
    non_null = []
    for row in candidates:
        props = row["properties"]
        if all(name in props and props[name] is not None for name in required):
            non_null.append(row)
    eligible = []
    for row in non_null:
        props = row["properties"]
        # The expression is keep == true && landcover >= 0 && landcover < 2
        # && site != "drop".
        # Check bool and numeric types explicitly; bool is an int subclass in
        # Python, but Earth Engine metadata equality keeps those types distinct.
        if any(name not in props or props[name] is None for name in required):
            continue
        if type(props["keep"]) is not bool or props["keep"] is not True:
            continue
        landcover = props["landcover"]
        if type(landcover) not in (int, float) or not np.isfinite(float(landcover)):
            continue
        if (landcover < 0 or landcover >= 2 or type(props["site"]) is not str
                or props["site"] == "drop"):
            continue
        eligible.append(row)
    return {"candidates": candidates, "non_null": non_null,
            "eligible": eligible, "limited": eligible[:filter_data["limit"]]}


def reference_table(data, geometries=True):
    """Apply the fixture's notNull, expression, and ordered limit semantics."""
    return reference_filter_stages(data, geometries=geometries)["limited"]


def reference_feature_collection(data, geometries=True):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": row["id"], "geometry": row["geometry"],
         "properties": row["properties"]}
        for row in reference_table(data, geometries=geometries)
    ]}


def _as_fraction(value):
    if type(value) is int:
        return Fraction(value)
    return Fraction.from_float(float(value))


def independent_training_model(data, metric="euclidean"):
    grouped = {}
    for row in reference_table(data):
        props = row["properties"]
        grouped.setdefault(props[data["class_property"]], []).append(
            [_as_fraction(props[band]) for band in data["input_properties"]]
        )
    labels = sorted(grouped)
    centers = {
        label: tuple(
            sum((vector[index] for vector in grouped[label]), Fraction())
            / len(grouped[label])
            for index in range(len(data["input_properties"]))
        )
        for label in labels
    }
    return {"metric": metric, "schema": list(data["input_properties"]),
            "labels": labels, "centers": centers}


def _cosine_similarity(query, center):
    def decimal(value):
        return Decimal(value.numerator) / Decimal(value.denominator)

    left = [decimal(value) for value in query]
    right = [decimal(value) for value in center]
    dot = sum((a * b for a, b in zip(left, right)), Decimal(0))
    left_norm = sum((value * value for value in left), Decimal(0)).sqrt()
    right_norm = sum((value * value for value in right), Decimal(0)).sqrt()
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Cosine fixture vectors must be nonzero")
    return dot / (left_norm * right_norm)


def _predict(model, query):
    scored = []
    for label in model["labels"]:
        center = model["centers"][label]
        if model["metric"] == "euclidean":
            score = sum(((a - b) ** 2 for a, b in zip(query, center)), Fraction())
            scored.append((score, label))
        elif model["metric"] == "manhattan":
            scored.append((sum((abs(a - b) for a, b in zip(query, center)), Fraction()), label))
        else:
            with localcontext() as context:
                context.prec = 80
                scored.append((-_cosine_similarity(query, center), label))
    scored.sort()
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        raise ValueError("Fixture query has a minimum-distance tie")
    return scored[0][1]


def independent_target_predictions(data, metric="euclidean"):
    """N target predictions from raw vectors and the independently trained model."""
    model = independent_training_model(data, metric)
    coordinates = data["pixel_centers"]
    prediction = np.full((len(data["items"]), 1, len(coordinates)), np.nan)
    for scene_index, item in enumerate(data["items"]):
        footprint = shape(item["geometry"])
        for pixel, coordinate in enumerate(coordinates):
            if not footprint.covers(Point(*coordinate)):
                continue
            vector = [item["pixel_values"][band][pixel]
                      for band in data["input_properties"]]
            if any(value is None for value in vector):
                continue
            if not all(np.isfinite(float(value)) for value in vector):
                raise ValueError("Fixture target vector contains infinity")
            prediction[scene_index, 0, pixel] = _predict(
                model, [_as_fraction(value) for value in vector],
            )
    return prediction



def model_centers_as_pairs(model):
    return {str(label): [[str(value.numerator), str(value.denominator)] for value in center]
            for label, center in model["centers"].items()}
