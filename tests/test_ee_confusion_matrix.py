"""Pinned Python ConfusionMatrix serialization and static semantic controls."""
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


def invocation_names(expression):
    return [node["functionName"] for _, node in expression.get("scope", [])
            if isinstance(node, dict) and node.get("type") == "Invocation"]


def add_unknown_argument(expression, function_name):
    result = deepcopy(expression)
    for _, node in reversed(result.get("scope", [])):
        if isinstance(node, dict) and node.get("functionName") == function_name:
            node["arguments"]["unexpected"] = 1
            return result
    raise AssertionError(f"No {function_name} invocation in SDK serialization")


MATRIX = [[5, 1, 0], [2, 3, 1], [0, 1, 4]]
ORDER = [10, -1, 3]


def confusion_matrix(ee, matrix=MATRIX, order=ORDER):
    return ee.ConfusionMatrix(ee.Array(matrix), order)


def test_pinned_sdk_serializes_typed_array_and_constructor_methods(ee):
    matrix = confusion_matrix(ee)
    encoded = encode(ee, matrix)
    assert "Array" in invocation_names(encoded)
    assert "ConfusionMatrix" in invocation_names(encoded)

    assert output(ee, matrix.array()) == MATRIX
    assert output(ee, matrix.order()) == ORDER


def test_official_constructor_does_not_promote_a_raw_list_to_typed_array(ee):
    # The 1.7.49 client permits constructing this wrapper, despite its public
    # constructor documentation saying the argument cannot be a list. Its wire
    # form retains a List and does not add the typed Array invocation.
    raw = ee.ConfusionMatrix([[1, 0], [0, 1]])
    encoded = encode(ee, raw)
    assert "ConfusionMatrix" in invocation_names(encoded)
    assert "Array" not in invocation_names(encoded)
    with pytest.raises(UnsupportedEEError, match="static ee.Array"):
        output(ee, raw.array())

    typed = ee.ConfusionMatrix(ee.Array([[1, 0], [0, 1]]))
    assert output(ee, typed.array()) == [[1, 0], [0, 1]]


def test_accuracy_and_kappa_match_independent_integer_fraction_references(ee):
    matrix = confusion_matrix(ee)
    # N=17, trace=12. Row totals are (6, 6, 5), column totals are (7, 5, 5),
    # so expected agreement numerator is 6*7 + 6*5 + 5*5 = 97.
    # Kappa is (17*12 - 97) / (17**2 - 97) = 107 / 192.
    assert output(ee, matrix.accuracy()) == 12 / 17
    assert output(ee, matrix.kappa()) == 107 / 192


def test_default_order_is_zero_based_and_explicit_order_keeps_negative_labels(ee):
    default = ee.ConfusionMatrix(ee.Array([[3, 1], [0, 4]]))
    assert output(ee, default.order()) == [0, 1]
    assert output(ee, default.array()) == [[3, 1], [0, 4]]

    explicit = confusion_matrix(ee)
    assert output(ee, explicit.order()) == [10, -1, 3]
    assert output(ee, explicit.array()) == MATRIX


def test_order_labels_use_unique_integer_values_with_exact_float64_boundaries(ee):
    boundary = ee.ConfusionMatrix(
        ee.Array([[1, 0], [0, 1]]), [-(2**53), 2**53]
    )
    assert output(ee, boundary.order()) == [-(2**53), 2**53]

    for order in ([1], [1, 1], [1, 1.5], [1, True], [2**53 + 1]):
        value = ee.ConfusionMatrix(ee.Array([[1, 0], [0, 1]]), order)
        with pytest.raises(UnsupportedEEError):
            output(ee, value.array())


def test_static_confusion_matrix_type_survives_dictionary_and_if_round_trips(ee):
    first = confusion_matrix(ee)
    from_dictionary = ee.ConfusionMatrix(
        ee.Dictionary({"estimate": first}).get("estimate")
    )
    assert output(ee, from_dictionary.accuracy()) == 12 / 17

    diagonal = ee.ConfusionMatrix(ee.Array([[3, 0], [0, 3]]), [10, -1])
    from_if = ee.ConfusionMatrix(ee.Algorithms.If(False, first, diagonal))
    assert output(ee, from_if.array()) == [[3, 0], [0, 3]]
    assert output(ee, from_if.kappa()) == 1.0


@pytest.mark.parametrize("matrix", [
    [[1, 2, 3], [4, 5, 6]],
    [[1, -1], [0, 2]],
    [[1.5]],
    [[True]],
    [[2**53 + 1]],
])
def test_invalid_shapes_and_count_types_are_rejected_after_sdk_serialization(ee, matrix):
    value = ee.ConfusionMatrix(ee.Array(matrix))
    with pytest.raises(UnsupportedEEError):
        output(ee, value.array())


def test_total_count_must_remain_within_exact_float64_integer_domain(ee):
    value = ee.ConfusionMatrix(ee.Array([[2**52, 0], [0, 2**52 + 1]]))
    with pytest.raises(UnsupportedEEError, match="total exceeds the exact Float64 domain"):
        output(ee, value.array())


def test_exact_float64_integer_count_boundary_is_accepted(ee):
    value = ee.ConfusionMatrix(ee.Array([[2**53]]))
    assert output(ee, value.array()) == [[2**53]]
    assert output(ee, value.accuracy()) == 1.0


def test_class_count_accepts_64_by_64_and_rejects_65(ee):
    boundary = ee.ConfusionMatrix(ee.Array([[0] * 64 for _ in range(64)]))
    assert output(ee, boundary.array().length().toList()) == [64, 64]

    too_large = ee.ConfusionMatrix(ee.Array([[0] * 65 for _ in range(65)]))
    with pytest.raises(UnsupportedEEError, match="at most 64 classes"):
        output(ee, too_large.array())


def test_confusion_matrix_work_is_bounded_when_materializing_arrays(ee):
    matrix = ee.ConfusionMatrix(ee.Array([[0] * 64 for _ in range(64)]))
    repeated_arrays = ee.List([matrix.array() for _ in range(10)])
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        output(ee, repeated_arrays)


def test_undefined_accuracy_and_expected_agreement_fail_explicitly(ee):
    empty = ee.ConfusionMatrix(ee.Array([[0]]))
    with pytest.raises(UnsupportedEEError, match="accuracy is undefined"):
        output(ee, empty.accuracy())
    with pytest.raises(UnsupportedEEError, match="kappa is undefined"):
        output(ee, empty.kappa())

    perfect = ee.ConfusionMatrix(ee.Array([[5, 0], [0, 0]]))
    assert output(ee, perfect.accuracy()) == 1.0
    with pytest.raises(UnsupportedEEError, match="kappa is undefined"):
        output(ee, perfect.kappa())


@pytest.mark.parametrize("method", ["producersAccuracy", "consumersAccuracy", "fscore"])
def test_other_sdk_confusion_methods_remain_explicitly_unsupported(ee, method):
    value = getattr(confusion_matrix(ee), method)()
    with pytest.raises(UnsupportedEEError, match="Unsupported Earth Engine algorithm"):
        output(ee, value)


def test_unknown_constructor_and_method_arguments_are_rejected(ee):
    matrix = confusion_matrix(ee)
    for expression, function_name in [
        (encode(ee, matrix.array()), "ConfusionMatrix"),
        (encode(ee, matrix.accuracy()), "ConfusionMatrix.accuracy"),
    ]:
        malformed = add_unknown_argument(expression, function_name)
        with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
            compile_expression(malformed, [], {})


def test_direct_confusion_matrix_json_output_is_explicitly_unsupported(ee):
    with pytest.raises(UnsupportedEEError, match="direct server-object JSON is unsupported"):
        output(ee, confusion_matrix(ee))
