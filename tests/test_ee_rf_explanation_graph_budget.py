"""Aggregate graph validation budgets for repeated actual RF explanations."""
import pytest

from gee.graph import validate
from gee.rf_explanation_processes import (
    MAX_EXPLANATION_GRAPH_WORK, MAX_EXPLANATION_GRAPH_WIRE_BYTES,
    preflight_explanation_graph,
)
from gee.rf_explanation_spec import prepare_explanation_spec, project_explanation
from gee.smile_rf_spec import (
    decode_rf_spec, prepare_rf_parameters, prepare_rf_rows, prepare_rf_spec,
)


def _wide_explanation_graph(count):
    schema = ["😀" * 255 + chr(ord("a") + index) for index in range(8)]
    class_property = "😀" * 255 + "z"
    trainer_spec = prepare_rf_spec(
        prepare_rf_parameters(3), schema, class_property,
    )
    rows = prepare_rf_rows([
        [0, [0] * len(schema)], [1, [10] * len(schema)],
    ], decode_rf_spec(trainer_spec))
    nodes = {"trainer": {
        "process_id": "local_ee_train_smile_rf_rows",
        "arguments": {"rows": rows, "spec": trainer_spec},
    }}
    projection = prepare_explanation_spec(schema, 3)
    for index in range(count):
        nodes[f"explain{index}"] = {
            "process_id": "local_ee_smile_rf_explain",
            "arguments": {"model": {"from_node": "trainer"}, "spec": projection},
            "result": index == count - 1,
        }
    return nodes, trainer_spec, projection


def test_repeated_explanations_reserve_aggregate_rf_budget_before_decoding(monkeypatch):
    import gee.rf_explanation_processes as explanation_processes
    import gee.rf_explanation_spec as explanation_spec
    import gee.smile_rf_processes as smile_processes

    nodes, trainer_spec, projection = _wide_explanation_graph(3)
    scanned = []
    size_text = explanation_spec._utf8_size

    def unexpected_decode(*_args, **_kwargs):
        raise AssertionError("RF specs must be budgeted before graph decoding")

    def track_scan(text, maximum):
        scanned.append(text)
        return size_text(text, maximum)

    monkeypatch.setattr(explanation_spec, "_utf8_size", track_scan)
    monkeypatch.setattr(explanation_processes, "decode_rf_spec", unexpected_decode)
    monkeypatch.setattr(smile_processes, "decode_rf_spec", unexpected_decode)
    monkeypatch.setattr(explanation_spec, "decode_explanation_spec", unexpected_decode)
    with pytest.raises(ValueError, match="150000-step object-work budget"):
        validate(nodes)
    assert scanned == [trainer_spec, projection, trainer_spec, projection, trainer_spec]


def test_repeated_explanations_within_aggregate_budget_still_validate():
    nodes, trainer_spec, projection = _wide_explanation_graph(2)
    trainer_bytes = len(trainer_spec.encode("utf-8"))
    pair_bytes = trainer_bytes + len(projection.encode("utf-8"))
    work = 2 * pair_bytes * 3 + trainer_bytes * 2
    wire = 2 * pair_bytes * 4 + trainer_bytes * 3
    assert work <= MAX_EXPLANATION_GRAPH_WORK
    assert wire <= MAX_EXPLANATION_GRAPH_WIRE_BYTES
    validate(nodes)


def test_explanation_schema_preserves_nul_names_supported_by_rf_schema():
    schema = ["tile\x00name"]
    class_property = "class\x00name"
    trainer_spec = prepare_rf_spec(prepare_rf_parameters(3), schema, class_property)
    assert decode_rf_spec(trainer_spec)["schema"] == schema

    projection = prepare_explanation_spec(schema, 3, view="importance_value", keys=schema)
    full = {
        "importance": {schema[0]: 1.5},
        "numberOfTrees": 3,
        "outOfBagErrorEstimate": 0.0,
    }
    assert project_explanation(full, projection) == 1.5


def test_explanation_prepare_rejects_large_canonical_wire_before_encoding(monkeypatch):
    import gee.rf_explanation_spec as explanation_spec

    def unexpected_encode(_value):
        raise AssertionError("oversized specifications must fail before JSON encoding")

    monkeypatch.setattr(explanation_spec, "encode_spec", unexpected_encode)
    schema = ["x" * 256]
    with pytest.raises(ValueError, match="16384 UTF-8 bytes"):
        prepare_explanation_spec(
            schema, 3, view="importance_values", keys=[schema[0]] * 64,
        )
