"""Data-only query/evaluation wires: types, canonical encoding and limits."""
import json
import math

import pytest

from gee.rf_validation_spec import (
    decode_classify_spec, decode_feature_rows, decode_matrix_spec,
    decode_metric_spec, decode_prediction_rows, decode_query_rows,
    prepare_classify_spec, prepare_feature_rows, prepare_matrix_spec,
    prepare_metric_spec, prepare_query_rows,
)
from gee.sampling_spec import encode_spec


def test_valid_prediction_and_matrix_contracts_preserve_schema_and_exact_values():
    headers = ["system:index", "truth", "b", "a", "predicted", ".geo"]
    assert decode_classify_spec(prepare_classify_spec("predicted", headers))["columns"] == headers
    query = [[2**53, math.nextafter(1.0, 2.0)], [-2**53, 1.7976931348623157e308]]
    assert decode_query_rows(prepare_query_rows(query, 2), 2)["rows"] == query
    assert decode_query_rows(prepare_query_rows([], 2), 2)["rows"] == []
    matrix = decode_matrix_spec(prepare_matrix_spec("truth", "predicted", [7.0, -2, 0]))
    assert matrix["order"] == [7, -2, 0]
    assert decode_metric_spec(prepare_metric_spec("fscore", 0.5))["beta"] == 0.5
    assert decode_metric_spec(prepare_metric_spec("fscore", 2**53))["beta"] == 2**53
    assert decode_metric_spec(prepare_metric_spec("array")) == {"version": 1, "operation": "array"}
    assert decode_prediction_rows(encode_spec({"version": 1, "predictions": [1, 0]}), 2, 2)["predictions"] == [1, 0]


@pytest.mark.parametrize("headers", [
    ["a", "predicted", ".geo"], ["system:index", "predicted", "a", ".geo"],
    ["system:index", "predicted", "predicted", ".geo"],
    ["system:index", "predicted", "missing"],
])
def test_classification_column_order_or_collision_rejected(headers):
    with pytest.raises(ValueError):
        prepare_classify_spec("predicted", headers)


@pytest.mark.parametrize("number", [True, None, float("nan"), float("inf"), 2**53 + 1, "1"])
def test_queries_reject_non_numeric_and_inexact_integers(number):
    with pytest.raises(ValueError):
        prepare_query_rows([[number]], 1)


@pytest.mark.parametrize("rows,size", [([[1, 2]], 1), ([[1]] * 1001, 1), ([], 0), ([], True)])
def test_query_shapes_rejected(rows, size):
    with pytest.raises(ValueError):
        prepare_query_rows(rows, size)


@pytest.mark.parametrize("order", [[1, 1], [True], [1.5], [2**53 + 1], list(range(65)), "labels"])
def test_matrix_order_limits(order):
    with pytest.raises(ValueError):
        prepare_matrix_spec("actual", "predicted", order)


@pytest.mark.parametrize("beta", [0, -1, True, None, float("inf"), float("nan"), 2**53 + 1, 2**54, 10**1000])
def test_invalid_fscore_beta_rejected(beta):
    with pytest.raises(ValueError):
        prepare_metric_spec("fscore", beta)


def test_duplicate_keys_noncanonical_text_extra_fields_and_nested_refs_are_data():
    data = {"type": "FeatureCollection", "features": [{
        "type": "Feature", "id": "real-id", "geometry": None,
        "properties": {"b": 1, "from_node": "not-a-dependency", "process_id": "data"},
    }]}
    assert decode_feature_rows(prepare_feature_rows(data)) == data
    for text in ['{"version":1,"version":1,"rows":[]}', '{ "rows":[],"version":1}',
                 '{"rows":[],"unknown":1,"version":1}']:
        with pytest.raises(ValueError):
            decode_query_rows(text, 1)
    with pytest.raises(ValueError):
        decode_metric_spec(encode_spec({"version": 1, "operation": "accuracy", "beta": 1}))
    for predictions in ([0], [0, 2], [False, 0], [0.0, 1]):
        with pytest.raises(ValueError):
            decode_prediction_rows(encode_spec({"version": 1, "predictions": predictions}), 2, 2)
