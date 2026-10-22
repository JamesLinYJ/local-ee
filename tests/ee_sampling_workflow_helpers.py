"""Versioned sampleRegions fixture and independent scientific references.

The helpers deliberately do not import the local sampler, sampled-table
assembler, runtime trainer or classifier.  ``graph_process_handlers`` are a
test-only evaluator for the declared compiled graph; comparisons use the
separate raw-fixture/Shapely reference path below.
"""
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from pathlib import Path

import numpy as np
from shapely.geometry import Point, box, shape


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-sampling-training-v1.json"
SAMPLE_PROCESS = "local_ee_sample_regions"
TRAIN_PROCESS = "local_ee_train_minimum_distance"
CLASSIFY_PROCESS = "local_ee_minimum_distance"


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text())


def compile_inputs(data):
    """Build metadata and raw vectors without adding expected pixel outputs."""
    catalog = [{
        "id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["catalog_bands"]}},
    }]
    items = {data["collection_id"]: [{
        key: row[key] for key in ("id", "bbox", "geometry", "properties")
    } for row in data["items"]]}
    arrays = {
        row["id"]: {
            band: np.asarray([
                np.nan if value is None else value
                for value in row["pixel_values"][band]
            ], dtype=np.float64)
            for band in data["catalog_bands"]
        }
        for row in data["items"]
    }
    geometries = {row["id"]: row["geometry"] for row in data["items"]}
    return catalog, items, arrays, geometries


def _cell(data, row, col):
    west, south, east, north = data["extent"]
    rows, columns = data["grid"]["shape_rows_columns"]
    width = (east - west) / columns
    height = (north - south) / rows
    x = west + (col + 0.5) * width
    y = north - (row + 0.5) * height
    return x, y, box(x - width / 2, y - height / 2, x + width / 2, y + height / 2)


def _point_cell(data, coordinate):
    x, y = coordinate[:2]
    west, south, east, north = data["extent"]
    rows, columns = data["grid"]["shape_rows_columns"]
    if x < west or x >= east or y <= south or y > north:
        return None
    width = (east - west) / columns
    height = (north - south) / rows
    col = int((x - west) // width)
    row = int((north - y) // height)
    return (row, col) if row < rows and col < columns else None


def _reference_cells(data, geometry):
    """N reference: brute-force every raw cell square against each geometry."""
    geom = shape(geometry)
    rows, columns = data["grid"]["shape_rows_columns"]
    kind = geometry["type"]
    if kind == "Point":
        cell = _point_cell(data, geometry["coordinates"])
        return [] if cell is None else [cell]
    if kind == "MultiPoint":
        return sorted({cell for coordinate in geometry["coordinates"]
                      if (cell := _point_cell(data, coordinate)) is not None})
    selected = []
    for row in range(rows):
        for col in range(columns):
            _, _, cell_square = _cell(data, row, col)
            if geom.intersection(cell_square).area > 0:
                selected.append((row, col))
    return selected


def reference_sample_rows(data, geometries=True):
    """Independently sample raw source arrays using Shapely cell intersections."""
    source = data["items"][0]
    rows = []
    for feature_index, feature in enumerate(data["training_features"]):
        properties = feature["properties"]
        for row, col in _reference_cells(data, feature["geometry"]):
            pixel = row * data["grid"]["shape_rows_columns"][1] + col
            values = [source["pixel_values"][band][pixel]
                      for band in data["input_properties"]]
            if any(value is None for value in values):
                continue
            if not all(np.isfinite(float(value)) for value in values):
                raise ValueError("Fixture selected a non-finite sample")
            x, y, _ = _cell(data, row, col)
            copied = {name: properties[name] for name in data["sample_properties"]}
            copied.update(dict(zip(data["input_properties"], values)))
            rows.append({
                "feature": feature_index, "row": row, "col": col,
                "id": f"f{feature_index}_r{row}_c{col}",
                "x": x, "y": y, "values": values,
                "properties": copied,
                "geometry": {"type": "Point", "coordinates": [x, y]} if geometries else None,
            })
    return rows


def reference_feature_collection(data, geometries=True):
    rows = reference_sample_rows(data, geometries=geometries)
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": row["id"], "geometry": row["geometry"],
         "properties": row["properties"]}
        for row in rows
    ]}


def _as_fraction(value):
    if type(value) is int:
        return Fraction(value)
    return Fraction.from_float(float(value))


def independent_training_model(data, metric):
    """Compute exact class means directly from independently selected raw pixels."""
    grouped = {}
    for row in reference_sample_rows(data):
        label = row["properties"][data["class_property"]]
        grouped.setdefault(label, []).append([_as_fraction(v) for v in row["values"]])
    labels = sorted(grouped)
    centers = {
        label: tuple(sum((row[i] for row in grouped[label]), Fraction()) / len(grouped[label])
                     for i in range(len(data["input_properties"])))
        for label in labels
    }
    return {"metric": metric, "schema": list(data["input_properties"]),
            "labels": labels, "centers": centers}


def _cosine_score(query, center):
    def decimal(value):
        return Decimal(value.numerator) / Decimal(value.denominator)

    left = [decimal(x) for x in query]
    right = [decimal(x) for x in center]
    dot = sum((x * y for x, y in zip(left, right)), Decimal(0))
    left_norm = sum((x * x for x in left), Decimal(0)).sqrt()
    right_norm = sum((x * x for x in right), Decimal(0)).sqrt()
    if left_norm == 0 or right_norm == 0:
        raise ValueError("Cosine fixture vectors must be nonzero")
    return dot / (left_norm * right_norm)


def _predict(model, query):
    scored = []
    for label in model["labels"]:
        center = model["centers"][label]
        if model["metric"] == "euclidean":
            score = sum(((x - y) ** 2 for x, y in zip(query, center)), Fraction())
            scored.append((score, label))
        elif model["metric"] == "manhattan":
            score = sum((abs(x - y) for x, y in zip(query, center)), Fraction())
            scored.append((score, label))
        else:
            with localcontext() as context:
                context.prec = 80
                scored.append((-_cosine_score(query, center), label))
    scored.sort()
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        raise ValueError("Fixture query has a minimum-distance tie")
    return scored[0][1]


def independent_target_predictions(data, metric):
    """N reference for both raw target arrays, preserving source geometry masks."""
    model = independent_training_model(data, metric)
    rows, columns = data["grid"]["shape_rows_columns"]
    centers = data["pixel_centers"]
    output = np.full((len(data["items"]), 1, len(centers)), np.nan, dtype=np.float64)
    for scene_index, item in enumerate(data["items"]):
        footprint = shape(item["geometry"])
        for pixel, coordinate in enumerate(centers):
            if not footprint.covers(Point(*coordinate)):
                continue
            query = [item["pixel_values"][band][pixel]
                     for band in data["input_properties"]]
            if any(value is None for value in query):
                continue
            if not all(np.isfinite(float(value)) for value in query):
                raise ValueError("Fixture target values must be finite or NoData")
            output[scene_index, 0, pixel] = _predict(
                model, [_as_fraction(value) for value in query],
            )
    assert output.shape == (len(data["items"]), 1, rows * columns)
    return output


def _compiled_spec(arguments):
    return json.loads(arguments["spec"])


def _sample_graph_process(data, arguments, values):
    """Test-only evaluator for the compiled sampler process, not production."""
    spec = _compiled_spec(arguments)
    cube, names, timed = values[arguments["data"]["from_node"]]
    if timed or list(names) != spec["bands"]:
        raise AssertionError("Compiled sampler must receive one image in declared band order")
    matrix = np.asarray(cube, dtype=np.float64)
    rows, columns = data["grid"]["shape_rows_columns"]
    if matrix.shape != (len(spec["bands"]), rows * columns):
        raise AssertionError("Compiled sampler source grid differs from the pinned fixture")
    output = []
    for feature_index, feature in enumerate(spec["regions"]["features"]):
        geometry = shape(feature["geometry"])
        kind = feature["geometry"]["type"]
        selected = set()
        if kind in {"Point", "MultiPoint"}:
            points = [feature["geometry"]["coordinates"]] if kind == "Point" else feature["geometry"]["coordinates"]
            for point in points:
                cell = _point_cell(data, point)
                if cell is not None:
                    selected.add(cell)
        else:
            # Index cells by spatial intersection first, then exclude zero-area
            # touches. Overlaps remain attached to their original feature index.
            for row in range(rows):
                for col in range(columns):
                    x, y, cell = _cell(data, row, col)
                    if geometry.intersects(cell) and geometry.intersection(cell).area > 0:
                        selected.add((row, col))
        for row, col in sorted(selected):
            pixel = row * columns + col
            sampled = [float(matrix[names.index(band), pixel]) for band in spec["bands"]]
            if any(np.isnan(value) for value in sampled):
                continue
            if any(not np.isfinite(value) for value in sampled):
                raise ValueError("Compiled sampler cannot return an infinite selected value")
            x, y, _ = _cell(data, row, col)
            props = {name: feature["properties"][name] for name in spec["properties"]}
            props.update(dict(zip(spec["bands"], sampled)))
            output.append({
                "type": "Feature", "id": f"f{feature_index}_r{row}_c{col}",
                "geometry": {"type": "Point", "coordinates": [x, y]} if spec["geometries"] else None,
                "properties": props,
            })
    return {"type": "FeatureCollection", "features": output}


def _runtime_training_process(arguments, values):
    """Independent runtime trainer for the compiled train-node reference."""
    table = values[arguments["data"]["from_node"]]
    spec = json.loads(arguments["spec"])
    grouped = {}
    for feature in table["features"]:
        props = feature["properties"]
        label = props[spec["class_property"]]
        grouped.setdefault(label, []).append([_as_fraction(props[name]) for name in spec["schema"]])
    labels = sorted(grouped)
    centers = [
        [sum((row[i] for row in grouped[label]), Fraction()) / len(grouped[label])
         for i in range(len(spec["schema"]))]
        for label in labels
    ]
    return {"metric": spec["metric"], "schema": spec["schema"],
            "labels": labels, "centers": centers}


def _runtime_classifier_process(arguments, values):
    """Independent evaluator for the emitted dynamic classifier process."""
    data, names, timed = values[arguments["data"]["from_node"]]
    model_ref = arguments["model"]["from_node"]
    model = values[model_ref]
    matrix = np.asarray(data, dtype=np.float64)
    if not timed:
        matrix = np.expand_dims(matrix, 0)
    centers = np.asarray([[float(value) for value in center]
                          for center in model["centers"]], dtype=np.float64)
    labels = np.asarray(model["labels"], dtype=np.int64)
    output = np.full((matrix.shape[0], 1, matrix.shape[-1]), np.nan, dtype=np.float64)
    for time_index in range(matrix.shape[0]):
        for pixel in range(matrix.shape[-1]):
            values_by_band = [matrix[time_index, names.index(name), pixel]
                              for name in model["schema"]]
            if any(np.isnan(value) for value in values_by_band):
                continue
            if any(not np.isfinite(value) for value in values_by_band):
                raise ValueError("Classifier query contains infinity")
            query = np.asarray(values_by_band, dtype=np.float64)
            if model["metric"] == "euclidean":
                scores = np.sum((centers - query) ** 2, axis=1)
            elif model["metric"] == "manhattan":
                scores = np.sum(np.abs(centers - query), axis=1)
            else:
                norm = np.linalg.norm(query)
                center_norms = np.linalg.norm(centers, axis=1)
                if norm == 0 or np.any(center_norms == 0):
                    raise ValueError("Cosine fixture vectors must be nonzero")
                scores = -(centers @ query) / (center_norms * norm)
            best = int(np.argmin(scores))
            if np.count_nonzero(scores == scores[best]) > 1:
                raise ValueError("Fixture query has a minimum-distance tie")
            output[time_index, 0, pixel] = labels[best]
    return (output if timed else output[0]), ["v"], timed


def graph_process_handlers(data):
    return {
        SAMPLE_PROCESS: lambda arguments, values: _sample_graph_process(data, arguments, values),
        TRAIN_PROCESS: _runtime_training_process,
        CLASSIFY_PROCESS: _runtime_classifier_process,
    }


def model_centers_as_pairs(model):
    return {str(label): [[str(value.numerator), str(value.denominator)] for value in center]
            for label, center in model["centers"].items()}
