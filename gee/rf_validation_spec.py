"""Canonical data-only contracts for RF feature prediction and evaluation."""
from __future__ import annotations

import math

from .sampling_spec import _parse, encode_spec
from .table_values import columns as table_columns


MAX_SPEC_BYTES = 16_384
METRIC_OPERATIONS = frozenset({
    "array", "order", "accuracy", "kappa", "consumersAccuracy",
    "producersAccuracy", "fscore",
})


def _name(value):
    if (type(value) is not str or not value or len(value) > 256
            or "." in value or "\x00" in value):
        raise ValueError("Validation requires a nonempty flat property name <=256 characters")
    return value


def _version(value, fields):
    if (type(value) is not dict or set(value) != fields | {"version"}
            or type(value["version"]) is not int or value["version"] != 1):
        raise ValueError("Validation requires exact version1 fields")
    return value


def _spec(text):
    if type(text) is not str or len(text.encode("utf-8")) > MAX_SPEC_BYTES:
        raise ValueError("Validation specification exceeds16384 UTF-8 bytes")
    return _parse(text)


def _encode(value, checker):
    text = encode_spec(value)
    checker(text)
    return text


def decode_classify_spec(text):
    value = _version(_spec(text), {"output_name", "columns"})
    name = _name(value["output_name"])
    headers = value["columns"]
    if (name == "system:index" or type(headers) is not list
            or not 3 <= len(headers) <= 256
            or any(type(item) is not str or len(item) > 256 or "\x00" in item for item in headers)
            or len(set(headers)) != len(headers)
            or headers[0] != "system:index" or headers[-1] != ".geo"
            or headers[-2] != name):
        raise ValueError("Classification columns must preserve original headers and append one unique output property")
    return value


def prepare_classify_spec(output_name, columns):
    return _encode({"version": 1, "output_name": output_name, "columns": list(columns)}, decode_classify_spec)


def decode_feature_rows(text):
    value = _parse(text)
    table_columns(value)
    return value


def prepare_feature_rows(data):
    table_columns(data)
    return encode_spec(data)


def _label(value):
    if type(value) is float and math.isfinite(value) and value.is_integer():
        value = int(value)
    if type(value) is not int or abs(value) > 2**53:
        raise ValueError("Matrix order requires exact integer labels within +/-2^53")
    return value


def decode_matrix_spec(text):
    value = _version(_spec(text), {"actual", "predicted", "order"})
    _name(value["actual"])
    _name(value["predicted"])
    order = value["order"]
    if order is not None:
        if type(order) is not list or len(order) > 64:
            raise ValueError("Matrix order supports at most64 labels")
        labels = [_label(item) for item in order]
        if len(set(labels)) != len(labels) or any(type(item) is not int for item in order):
            raise ValueError("Matrix order requires unique canonical integer labels")
    return value


def prepare_matrix_spec(actual, predicted, order=None):
    if order is not None:
        if type(order) is not list or len(order) > 64:
            raise ValueError("Matrix order supports at most64 labels")
        order = [_label(item) for item in order]
    return _encode({"version": 1, "actual": actual, "predicted": predicted, "order": order}, decode_matrix_spec)


def decode_metric_spec(text):
    value = _spec(text)
    if type(value) is not dict or value.get("operation") not in METRIC_OPERATIONS:
        raise ValueError("Unsupported runtime ConfusionMatrix accessor")
    operation = value["operation"]
    _version(value, {"operation", "beta"} if operation == "fscore" else {"operation"})
    if operation == "fscore":
        beta = value["beta"]
        try:
            valid = (type(beta) in (int, float) and math.isfinite(beta) and beta > 0
                     and (type(beta) is not int or beta <= 2**53))
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("ConfusionMatrix fscore beta must be positive finite")
    return value


def prepare_metric_spec(operation, beta=1.0):
    value = {"version": 1, "operation": operation}
    if operation == "fscore":
        value["beta"] = beta
    return _encode(value, decode_metric_spec)


def _query_rows(value, schema_size):
    _version(value, {"rows"})
    rows = value["rows"]
    if (type(schema_size) is not int or not 1 <= schema_size <= 8
            or type(rows) is not list or len(rows) > 1000):
        raise ValueError("RF queries support0..1000 rows and1..8 schema columns")
    for row in rows:
        if type(row) is not list or len(row) != schema_size:
            raise ValueError("RF query rows must match the ordered model schema")
        for number in row:
            try:
                valid = (type(number) in (int, float) and math.isfinite(number)
                         and (type(number) is not int or abs(number) <= 2**53))
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError("RF queries require finite exact-domain numeric values")
    return value


def prepare_query_rows(rows, schema_size):
    return encode_spec(_query_rows({"version": 1, "rows": rows}, schema_size))


def decode_query_rows(text, schema_size):
    return _query_rows(_parse(text), schema_size)


def decode_prediction_rows(text, row_count, class_count):
    value = _version(_parse(text), {"predictions"})
    predictions = value["predictions"]
    if (type(row_count) is not int or not 0 <= row_count <= 1000
            or type(class_count) is not int or not 2 <= class_count <= 64
            or type(predictions) is not list or len(predictions) != row_count
            or any(type(label) is not int or not 0 <= label < class_count for label in predictions)):
        raise ValueError("RF predictions differ from the real row count or class domain")
    return value


def validate_metric_value(value):
    """Limit public accessors to finite scalars and rank1/rank2 numeric lists."""
    pending = [(value, 0)]
    cells = 0
    while pending:
        item, depth = pending.pop()
        if type(item) is list:
            if depth >= 2 or len(item) > 4096:
                raise ValueError("Runtime matrix result exceeds its bounded numeric shape")
            pending.extend((child, depth + 1) for child in item)
        else:
            cells += 1
            try:
                valid = (type(item) in (int, float) and math.isfinite(item)
                         and (type(item) is not int or abs(item) <= 2**53))
            except OverflowError:
                valid = False
            if not valid or cells > 4096:
                raise ValueError("Runtime matrix result must be a bounded finite numeric value")
    return value
