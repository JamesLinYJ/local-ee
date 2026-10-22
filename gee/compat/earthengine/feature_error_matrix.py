"""Bounded confusion matrices for inline Earth Engine FeatureCollections."""
from __future__ import annotations

import math

import numpy as np

from .array_core import wrap_array
from .confusion_values import make_confusion
from .feature_values import charge, is_collection, property_name, validate_feature
from .ir import fail


_MAX_FEATURES = 1000
_MAX_MATRIX_DIMENSION = 64
_MAX_MATRIX_CELLS = 4096
_MAX_EXACT_LABEL = 2**53


def _integer_label(value, label):
    """Convert an integer-valued numeric property without accepting bools."""
    if type(value) is int:
        return value
    if type(value) is float and math.isfinite(value) and value.is_integer():
        return int(value)
    fail(f"Collection.errorMatrix {label} labels must be finite integers")


def _collection_features(translator, value):
    if not is_collection(value):
        fail("Collection.errorMatrix requires an inline FeatureCollection")
    features = value.get("features")
    if not isinstance(features, list):
        fail("Inline FeatureCollection requires a feature list")
    if len(features) > _MAX_FEATURES:
        fail("Collection.errorMatrix supports at most 1000 features")

    for feature in features:
        charge(translator)
        validate_feature(translator, feature)
    return features


def _explicit_order(translator, value):
    if not isinstance(value, list):
        fail("Collection.errorMatrix order must be a list of integer labels")
    if len(value) > _MAX_MATRIX_DIMENSION:
        fail("Collection.errorMatrix order supports at most 64 labels")

    charge(translator, len(value))
    labels = []
    seen = set()
    for item in value:
        label = _integer_label(item, "order")
        if not -_MAX_EXACT_LABEL <= label <= _MAX_EXACT_LABEL:
            fail("Collection.errorMatrix order labels must be within +/-2^53")
        if label in seen:
            fail("Collection.errorMatrix order labels must be unique")
        seen.add(label)
        labels.append(label)
    return tuple(labels)


def invoke_error_matrix(translator, name, arguments):
    """Evaluate Collection.errorMatrix over a complete inline Feature list.

    All input values, shape limits and shared compilation charges are checked
    before allocating the result. Remote collections and sampled/partial
    property semantics are intentionally outside this static operation.
    """
    if name != "Collection.errorMatrix":
        fail(f"Unsupported Earth Engine algorithm: {name}")

    a = arguments
    translator.allowed(a, {"collection", "actual", "predicted", "order"})
    if "collection" not in a:
        fail("Collection.errorMatrix requires a collection")

    actual_name = property_name(a.get("actual"))
    predicted_name = property_name(a.get("predicted"))
    charge(translator, len(actual_name) + len(predicted_name) + 2)
    features = _collection_features(translator, a["collection"])

    # Validate every property and account for dictionary-key scans before
    # reading the requested columns. validate_feature has already established
    # that properties is a string-keyed dictionary.
    pairs = []
    for feature in features:
        properties = feature["properties"]
        charge(translator, len(properties))
        for key in properties:
            charge(translator, len(key))
        charge(translator, 2)
        for key in (actual_name, predicted_name):
            if key not in properties:
                fail(f"Collection.errorMatrix property is missing: {key}")
            if properties[key] is None:
                fail(f"Collection.errorMatrix property is null: {key}")
        actual = _integer_label(properties[actual_name], "actual")
        predicted = _integer_label(properties[predicted_name], "predicted")
        pairs.append((actual, predicted))

    if "order" in a and a["order"] is not None:
        order = _explicit_order(translator, a["order"])
    else:
        if not pairs:
            fail("Collection.errorMatrix needs an explicit order for an empty collection")
        if any(actual < 0 or predicted < 0 for actual, predicted in pairs):
            fail("Collection.errorMatrix labels must be nonnegative when order is omitted")
        max_label = max(max(actual, predicted) for actual, predicted in pairs)
        dimension = max_label + 1
        if dimension > _MAX_MATRIX_DIMENSION:
            fail("Collection.errorMatrix inferred order supports at most 64 labels")
        order = tuple(range(dimension))

    dimension = len(order)
    cells = dimension * dimension
    if dimension > _MAX_MATRIX_DIMENSION or cells > _MAX_MATRIX_CELLS:
        fail("Collection.errorMatrix supports at most 64 labels and 4096 cells")

    # Include output memory/work in the shared budget before allocating the
    # matrix; input scanning and requested property-name costs were charged
    # above. Check the later pair pass and factory validation up front too,
    # while letting their work be charged when performed.
    charge(translator, cells + 2 * dimension)
    if translator.steps + len(pairs) + cells + dimension > 50_000:
        fail("Earth Engine graph exceeds compilation limits")
    order_values = list(order)
    positions = {label: index for index, label in enumerate(order_values)}
    matrix = np.zeros((dimension, dimension), dtype=np.int64)
    for actual, predicted in pairs:
        charge(translator)
        row = positions.get(actual)
        column = positions.get(predicted)
        if row is not None and column is not None:
            matrix[row, column] += 1

    return make_confusion(translator, wrap_array(matrix), order=order_values)
