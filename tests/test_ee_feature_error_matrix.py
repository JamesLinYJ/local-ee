"""Pinned Python FeatureCollection.errorMatrix workflows and bounds."""
from copy import deepcopy
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def output(ee, value):
    return compile_expression(encode(ee, value), [], {})["value"]


def feature_collection(ee, rows):
    return ee.FeatureCollection([ee.Feature(None, row) for row in rows])


def error_matrix(ee, rows, order=None):
    return feature_collection(ee, rows).errorMatrix(
        "actual", "predicted", order=order
    )


def add_unknown_argument(expression, function_name):
    result = deepcopy(expression)
    for _, node in reversed(result.get("scope", [])):
        if isinstance(node, dict) and node.get("functionName") == function_name:
            node["arguments"]["unexpected"] = 1
            return result
    raise AssertionError(f"No {function_name} invocation in SDK serialization")


PAIRS = (
    [(10, 10)] * 5 + [(10, -1)] + [(-1, 10)] * 2 + [(-1, -1)] * 3
    + [(-1, 3), (3, -1)] + [(3, 3)] * 4
)


def rows_from_pairs(pairs):
    return [{"actual": actual, "predicted": predicted}
            for actual, predicted in pairs]


def test_sdk_error_matrix_counts_actual_rows_and_predicted_columns(ee):
    matrix = error_matrix(ee, rows_from_pairs(PAIRS), order=[10, -1, 3])
    assert output(ee, matrix.array()) == [[5, 1, 0], [2, 3, 1], [0, 1, 4]]
    assert output(ee, matrix.order()) == [10, -1, 3]
    # This deliberately asymmetric fixture catches a row/column reversal.
    assert output(ee, matrix.accuracy()) == 12 / 17
    assert output(ee, matrix.kappa()) == 107 / 192


def test_inferred_order_is_zero_based_and_includes_missing_intermediate_labels(ee):
    matrix = error_matrix(ee, rows_from_pairs([(2, 0), (0, 1), (2, 2)]))
    assert output(ee, matrix.order()) == [0, 1, 2]
    assert output(ee, matrix.array()) == [[0, 1, 0], [0, 0, 0], [1, 0, 1]]


def test_explicit_order_counts_only_pairs_with_both_labels_in_the_order(ee):
    rows = rows_from_pairs([(5, 5), (5, 1), (5, 9), (9, 1), (1, 5)])
    matrix = error_matrix(ee, rows, order=[5, 1])
    assert output(ee, matrix.array()) == [[1, 1], [1, 0]]
    assert output(ee, matrix.order()) == [5, 1]


def test_integer_valued_float_properties_are_accepted(ee):
    matrix = error_matrix(
        ee, [{"actual": 2.0, "predicted": 1.0},
             {"actual": 1.0, "predicted": 1.0}]
    )
    assert output(ee, matrix.array()) == [[0, 0, 0], [0, 1, 0], [0, 1, 0]]


def test_empty_order_materializes_a_zero_by_zero_matrix(ee):
    matrix = error_matrix(ee, rows_from_pairs([(7, 8)]), order=[])
    assert output(ee, matrix.order()) == []
    assert output(ee, matrix.array().length().toList()) == [0, 0]


def test_empty_collection_requires_explicit_order_and_can_build_zero_counts(ee):
    with pytest.raises(UnsupportedEEError, match="explicit order for an empty collection"):
        output(ee, error_matrix(ee, []).array())

    matrix = error_matrix(ee, [], order=[4, -2])
    assert output(ee, matrix.order()) == [4, -2]
    assert output(ee, matrix.array()) == [[0, 0], [0, 0]]
    with pytest.raises(UnsupportedEEError, match="accuracy is undefined"):
        output(ee, matrix.accuracy())


@pytest.mark.parametrize("row", [
    {"predicted": 0},
    {"actual": None, "predicted": 0},
    {"actual": 1, "predicted": None},
    {"actual": 1.5, "predicted": 0},
    {"actual": 0, "predicted": 1.5},
    {"actual": True, "predicted": 0},
    {"actual": 0, "predicted": False},
])
def test_missing_null_fractional_and_boolean_properties_fail(ee, row):
    with pytest.raises(UnsupportedEEError):
        output(ee, error_matrix(ee, [row]).array())


@pytest.mark.parametrize("order", [[1, 1], [1.5], [True], list(range(65))])
def test_explicit_order_rejects_duplicate_noninteger_boolean_and_oversize_labels(ee, order):
    matrix = error_matrix(ee, rows_from_pairs([(1, 1)]), order=order)
    with pytest.raises(UnsupportedEEError):
        output(ee, matrix.array())


def test_inferred_order_rejects_negative_and_more_than_64_classes(ee):
    negative = error_matrix(ee, rows_from_pairs([(-1, 0)]))
    with pytest.raises(UnsupportedEEError, match="nonnegative when order is omitted"):
        output(ee, negative.array())

    too_many = error_matrix(ee, rows_from_pairs([(64, 64)]))
    with pytest.raises(UnsupportedEEError, match="at most 64 labels"):
        output(ee, too_many.array())


def test_inferred_64_class_boundary_and_explicit_noncontiguous_boundary(ee):
    inferred = error_matrix(ee, rows_from_pairs([(63, 63)]))
    assert output(ee, inferred.array().length().toList()) == [64, 64]

    order = list(range(-32, 32))
    explicit = error_matrix(ee, rows_from_pairs([(31, -32)]), order=order)
    assert output(ee, explicit.array().length().toList()) == [64, 64]
    assert output(ee, explicit.array().get([63, 0])) == 1


def test_inline_feature_limit_accepts_1000_and_rejects_1001(ee):
    accepted = error_matrix(ee, rows_from_pairs([(0, 0)] * 1000))
    assert output(ee, accepted.array().get([0, 0])) == 1000

    rejected = error_matrix(ee, rows_from_pairs([(0, 0)] * 1001))
    with pytest.raises(UnsupportedEEError, match="at most 1000 features"):
        output(ee, rejected.array())


def test_error_matrix_unknown_arguments_are_rejected_in_sdk_wire_expression(ee):
    expression = encode(ee, error_matrix(ee, rows_from_pairs([(0, 0)])).array())
    malformed = add_unknown_argument(expression, "Collection.errorMatrix")
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        compile_expression(malformed, [], {})


def test_direct_error_matrix_object_json_output_is_explicitly_unsupported(ee):
    with pytest.raises(UnsupportedEEError, match="direct server-object JSON is unsupported"):
        output(ee, error_matrix(ee, rows_from_pairs([(0, 0)])))


def test_feature_error_matrix_respects_the_shared_compilation_work_limit(ee):
    rows = []
    for _ in range(100):
        properties = {f"field_{index:02d}": index for index in range(60)}
        properties.update(actual=0, predicted=0)
        rows.append(properties)

    matrix = error_matrix(ee, rows)
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        output(ee, matrix.array())
