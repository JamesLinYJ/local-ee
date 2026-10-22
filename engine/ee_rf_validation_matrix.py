"""Opaque runtime confusion matrices and the shared bounded accessor math."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


_MATRIX_TOKEN = object()
MAX_MATRIX_CLASSES = 64
MAX_MATRIX_CELLS = MAX_MATRIX_CLASSES * MAX_MATRIX_CLASSES
MAX_EXACT_COUNT = 2**53


@dataclass(frozen=True, slots=True)
class RuntimeConfusionMatrix:
    """Trusted matrix reference; only confusion-value may consume this type."""

    _value: Any
    _token: Any

    def __post_init__(self):
        if self._token is not _MATRIX_TOKEN:
            raise TypeError("Runtime confusion matrices can only come from trusted producers")


@dataclass(frozen=True, slots=True)
class PendingRfConfusionMatrix:
    """Dry-run matrix reference with lineage and no fabricated counts."""

    traces: tuple[Any, ...] = ()
    data_tracer: Any = None


class _StaticMatrixContext:
    """Resource context consumed by the established static confusion helpers."""

    def __init__(self):
        self.steps = 0

    def allowed(self, arguments, names):
        unknown = set(arguments) - set(names)
        if unknown:
            raise ValueError(f"Unsupported runtime confusion arguments: {sorted(unknown)}")


def _new_matrix(matrix):
    from gee.compat.earthengine.confusion_values import StaticConfusionMatrix

    if type(matrix) is not StaticConfusionMatrix:
        raise ValueError("Runtime confusion matrix producer returned an invalid matrix")
    return RuntimeConfusionMatrix(matrix, _MATRIX_TOKEN)


def _integer_label(value, label):
    import math

    if type(value) is int:
        result = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        result = int(value)
    else:
        raise ValueError(f"Collection.errorMatrix {label} labels must be finite integers")
    if abs(result) > MAX_EXACT_COUNT:
        raise ValueError(f"Collection.errorMatrix {label} labels exceed the exact Float64 domain")
    return result


def error_matrix(features, actual_name, predicted_name, order, work):
    """Build an error matrix using the static feature-operation edge rules."""
    if type(features) is not list or len(features) > 1_000:
        raise ValueError("Collection.errorMatrix supports at most 1000 features")
    work.charge(len(actual_name) + len(predicted_name) + 2)
    pairs = []
    for feature in features:
        work.charge()
        if type(feature) is not dict or type(feature.get("properties")) is not dict:
            raise ValueError("Collection.errorMatrix requires validated feature properties")
        properties = feature["properties"]
        work.charge(len(properties))
        for key in properties:
            work.charge(len(key))
        work.charge(2)
        for key in (actual_name, predicted_name):
            if key not in properties:
                raise ValueError(f"Collection.errorMatrix property is missing: {key}")
            if properties[key] is None:
                raise ValueError(f"Collection.errorMatrix property is null: {key}")
        pairs.append((
            _integer_label(properties[actual_name], "actual"),
            _integer_label(properties[predicted_name], "predicted"),
        ))

    if order is None:
        if not pairs:
            raise ValueError("Collection.errorMatrix needs an explicit order for an empty collection")
        if any(actual < 0 or predicted < 0 for actual, predicted in pairs):
            raise ValueError("Collection.errorMatrix labels must be nonnegative when order is omitted")
        dimension = max(max(actual, predicted) for actual, predicted in pairs) + 1
        if dimension > MAX_MATRIX_CLASSES:
            raise ValueError("Collection.errorMatrix inferred order supports at most 64 labels")
        labels = tuple(range(dimension))
    else:
        labels = tuple(order)
    dimension = len(labels)
    cells = dimension * dimension
    if dimension > MAX_MATRIX_CLASSES or cells > MAX_MATRIX_CELLS:
        raise ValueError("Collection.errorMatrix supports at most 64 labels and 4096 cells")

    # Reserve allocation, count work, and the static ConfusionMatrix validator
    # before allocating the matrix.
    work.charge(cells + 2 * dimension + len(pairs) + cells + dimension)
    positions = {label: index for index, label in enumerate(labels)}
    counts = np.zeros((dimension, dimension), dtype=np.int64)
    for actual, predicted in pairs:
        work.charge()
        row = positions.get(actual)
        column = positions.get(predicted)
        if row is not None and column is not None:
            counts[row, column] += 1

    from gee.compat.earthengine.array_core import wrap_array
    from gee.compat.earthengine.confusion_values import make_confusion

    context = _StaticMatrixContext()
    matrix = make_confusion(context, wrap_array(counts), order=list(labels))
    return _new_matrix(matrix)


def confusion_from_native(text, class_count, training_row_count):
    """Independently validate the JVM resubstitution matrix envelope."""
    from gee.sampling_spec import _parse
    from gee.compat.earthengine.array_core import wrap_array
    from gee.compat.earthengine.confusion_values import make_confusion

    if type(text) is not str:
        raise ValueError("Smile RF JVM confusionMatrix must return canonical JSON text")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Smile RF JVM confusionMatrix must return valid UTF-8") from exc
    if len(encoded) > 16_384:
        raise ValueError("Smile RF JVM confusionMatrix exceeds the 16384-byte limit")
    value = _parse(text)
    if (type(value) is not dict or set(value) != {"matrix", "order", "version"}
            or type(value["version"]) is not int or value["version"] != 1):
        raise ValueError("Smile RF JVM confusionMatrix returned an invalid version1 envelope")
    if type(class_count) is not int or not 2 <= class_count <= MAX_MATRIX_CLASSES:
        raise ValueError("Smile RF model has an invalid class count")
    if type(training_row_count) is not int or not 2 <= training_row_count <= 1_000:
        raise ValueError("Smile RF model has an invalid training-row count")
    expected_order = list(range(class_count))
    matrix = value["matrix"]
    if (type(value["order"]) is not list or value["order"] != expected_order
            or any(type(label) is not int for label in value["order"])
            or type(matrix) is not list or len(matrix) != class_count):
        raise ValueError("Smile RF JVM confusionMatrix has an unexpected order or row count")
    total = 0
    for row in matrix:
        if type(row) is not list or len(row) != class_count:
            raise ValueError("Smile RF JVM confusionMatrix must be square")
        for count in row:
            if type(count) is not int or count < 0:
                raise ValueError("Smile RF JVM confusion counts must be nonnegative integers")
            total += count
            if total > MAX_EXACT_COUNT:
                raise ValueError("Smile RF JVM confusion total exceeds the exact Float64 domain")
    if total != training_row_count:
        raise ValueError("Smile RF JVM confusion total differs from retained training row count")

    context = _StaticMatrixContext()
    frozen = make_confusion(context, wrap_array(matrix), order=value["order"])
    return _new_matrix(frozen)


def evaluate_confusion(matrix, metric_spec, work):
    """Evaluate the established static ConfusionMatrix implementations."""
    from gee.compat.earthengine.array_core import StaticArray
    from gee.compat.earthengine.confusion_values import invoke_confusion

    if type(matrix) is not RuntimeConfusionMatrix or matrix._token is not _MATRIX_TOKEN:
        raise ValueError("ConfusionMatrix accessors require an RF confusion result")
    if (type(metric_spec) is not dict or type(metric_spec.get("version")) is not int
            or metric_spec["version"] != 1 or type(metric_spec.get("operation")) is not str):
        raise ValueError("Runtime ConfusionMatrix spec must be a validated version1 object")
    operation_name = metric_spec["operation"]
    expected_fields = {"version", "operation", "beta"} if operation_name == "fscore" else {"version", "operation"}
    if set(metric_spec) != expected_fields:
        raise ValueError("Runtime ConfusionMatrix spec has unexpected fields")
    names = {
        "array": "ConfusionMatrix.array",
        "order": "ConfusionMatrix.order",
        "accuracy": "ConfusionMatrix.accuracy",
        "kappa": "ConfusionMatrix.kappa",
        "consumersAccuracy": "ConfusionMatrix.consumersAccuracy",
        "producersAccuracy": "ConfusionMatrix.producersAccuracy",
        "fscore": "ConfusionMatrix.fscore",
    }
    try:
        operation = names[operation_name]
    except KeyError as exc:
        raise ValueError("Unsupported runtime ConfusionMatrix accessor") from exc
    arguments = {"confusionMatrix": matrix._value}
    if operation_name == "fscore":
        arguments["beta"] = metric_spec["beta"]
    value = invoke_confusion(work, operation, arguments)
    if type(value) is StaticArray:
        work.charge(value.data.size)
        return value.to_value()
    return value
