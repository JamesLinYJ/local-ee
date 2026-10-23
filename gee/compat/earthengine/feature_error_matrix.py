"""Bounded confusion matrices for inline Earth Engine FeatureCollections."""
from __future__ import annotations

import math

import numpy as np

from ...rf_validation_spec import prepare_matrix_spec
from ...sample_table_spec import decode_sample_operation
from .array_core import wrap_array
from .confusion_values import make_confusion
from .feature_values import charge, is_collection, property_name, validate_feature
from .ir import SampledFeatures, fail
from .runtime_feature_ir import RFClassifiedFeatureTable, RuntimeFeatureErrorMatrix
from .sampled_feature_ops import validated_sampled_schema
from .classified_feature_ops import validated_classified_schema


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

    table = a["collection"]
    if isinstance(table, (SampledFeatures, RFClassifiedFeatureTable)):
        return _runtime_error_matrix(translator, a, table)

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


def _runtime_error_matrix(translator, arguments, table):
    """Retain an errorMatrix over a lazy sampled or predicted feature table."""
    known_empty = False
    if isinstance(table, SampledFeatures):
        try:
            sampled, columns, operations = validated_sampled_schema(
                table, translator, "Collection.errorMatrix sample table",
            )
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"Collection.errorMatrix has an invalid sample table: {exc}")
        known_empty = _sampled_table_empty(sampled, operations)
    else:
        columns, post_operations, _source_operations = validated_classified_schema(
            table, translator, "Collection.errorMatrix classified table",
        )
        known_empty = table.row_count == 0
        if isinstance(table.source, SampledFeatures):
            try:
                sampled, sampled_columns, operations = validated_sampled_schema(
                    table.source, translator,
                    "Collection.errorMatrix classified sample table",
                )
            except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
                fail(f"Collection.errorMatrix has an invalid sample table: {exc}")
            if not set(sampled_columns) <= set(columns):
                fail("Collection.errorMatrix classified table lost sample-table columns")
            known_empty = known_empty or _sampled_table_empty(sampled, operations)
        for text in post_operations:
            charge(translator, 8 + 6 * len(text))
            try:
                operation = decode_sample_operation(text)
            except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
                fail(f"Collection.errorMatrix has an invalid classified-table operation: {exc}")
            if operation["operation"] == "limit" and operation["count"] == 0:
                known_empty = True

    actual = property_name(arguments.get("actual"))
    predicted = property_name(arguments.get("predicted"))
    charge(translator, len(actual) + len(predicted) + 2)
    if known_empty and arguments.get("order") is None:
        fail("Collection.errorMatrix needs an explicit order for an empty collection")
    if not known_empty:
        available = set(columns)
        for name in (actual, predicted):
            if name not in available:
                fail(f"Collection.errorMatrix property is missing: {name}")
    try:
        spec = prepare_matrix_spec(actual, predicted, arguments.get("order"))
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Collection.errorMatrix specification is invalid: {exc}")
    charge(translator, len(spec) + len(columns))
    return RuntimeFeatureErrorMatrix(table=table, spec=spec)


def _sampled_table_empty(sampled_spec, operations):
    """Recognize empty rows only from the literal regions or limit(0)."""
    from ...image_sampling_spec import is_image_sample

    if not sampled_spec["regions"]["features"]:
        return True
    if is_image_sample(sampled_spec) and sampled_spec["image_sample"]["num_pixels"] == 0:
        return True
    for text in operations:
        try:
            operation = decode_sample_operation(text)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"Collection.errorMatrix has an invalid sample-table operation: {exc}")
        if operation["operation"] == "limit" and operation["count"] == 0:
            return True
    return False
