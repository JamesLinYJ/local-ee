"""Separate RF object-work, copy-work and wire-scan budgets."""
from __future__ import annotations

import pytest

from engine import ee_process_adapters as adapters
from engine import ee_smile_rf_training as training
from engine.ee_sampling_result import SampledFeatureTable
from ee_smile_rf_engine_helpers import rows_text as _rows_text, sample_table as _sample_table, spec as _spec


def _sample_object_work(table, schema_width=2):
    cells = table.row_count * len(table.columns)
    row_cells = table.row_count * (schema_width + 1)
    return {
        "copy": cells + table.data_copy_work,
        "feature_rows": row_cells,
        "prepare_shape": row_cells,
        "decode_shape": row_cells,
    }


@pytest.mark.parametrize("invalid_prior", [50_001, True, -1, 1.5])
def test_prior_table_operation_work_is_strictly_capped_before_copy(monkeypatch, invalid_prior):
    table = _sample_table()
    table.sample_operation_work = invalid_prior

    def forbidden_copy(_):
        pytest.fail("invalid prior table work reached the SampledFeatureTable copy")

    monkeypatch.setattr(SampledFeatureTable, "data", property(forbidden_copy))
    with pytest.raises(ValueError, match="integer from 0 through 50000"):
        adapters.local_ee_train_smile_rf_samples(
            {"data": table, "spec": _spec()}, env=None,
        )


def test_sample_copy_shape_uses_rf_meter_but_prior_stays_at_50000(monkeypatch):
    extra_values = list(range(50_000))
    features = [
        {"type": "Feature", "id": f"f0_r0_c{index}", "geometry": None,
         "properties": {"landcover": label, "red": index + 0.25, "nir": index + 2,
                        "unused": {"nested": extra_values}}}
        for index, label in enumerate((0.0, 1.0))
    ]
    columns = ["system:index", "landcover", "red", "nir", "unused", ".geo"]
    table = _sample_table(rows=features, columns=columns)
    table.sample_operation_work = 50_000
    copy_work = table.row_count * len(table.columns) + table.data_copy_work
    assert copy_work + table.sample_operation_work > training.MAX_RF_RUNTIME_WORK

    def forbidden_copy(_):
        pytest.fail("over-budget nested FeatureCollection was copied")

    monkeypatch.setattr(SampledFeatureTable, "data", property(forbidden_copy))
    with pytest.raises(ValueError, match="150000-step object-work budget"):
        adapters.local_ee_train_smile_rf_samples(
            {"data": table, "spec": _spec()}, env=None,
        )


def test_sample_spec_wire_bytes_are_charged_before_decoder_or_copy(monkeypatch):
    spec_text = _spec()
    table = _sample_table()
    spec_bytes = len(spec_text.encode("utf-8"))
    monkeypatch.setattr(training, "MAX_RF_WIRE_SCAN_BYTES", 2 * spec_bytes - 1)

    def forbidden_decode(_):
        pytest.fail("spec decoder ran before its separate wire-scan charge")

    def forbidden_copy(_):
        pytest.fail("sample data was copied before spec wire-scan rejection")

    monkeypatch.setattr("gee.smile_rf_spec.decode_rf_spec", forbidden_decode)
    monkeypatch.setattr(SampledFeatureTable, "data", property(forbidden_copy))
    with pytest.raises(ValueError, match="3000000-byte wire-scan budget"):
        adapters.local_ee_train_smile_rf_samples(
            {"data": table, "spec": spec_text}, env=None,
        )


def test_static_rows_wire_budget_is_charged_before_row_decoder(monkeypatch):
    spec_text = _spec()
    rows_text = _rows_text(spec_text)
    rows_text += " " * (training.MAX_RF_ROWS_JSON_BYTES - len(rows_text) - 100)
    spec_charge = 2 * len(spec_text.encode("utf-8"))
    rows_charge = 3 * len(rows_text.encode("utf-8"))
    monkeypatch.setattr(training, "MAX_RF_WIRE_SCAN_BYTES", spec_charge + rows_charge - 1)

    def forbidden_decode(*_args):
        pytest.fail("static rows decoder ran before the separate wire-scan charge")

    monkeypatch.setattr("gee.smile_rf_spec.decode_rf_rows", forbidden_decode)
    with pytest.raises(ValueError, match="3000000-byte wire-scan budget"):
        adapters.local_ee_train_smile_rf_rows(
            {"rows": rows_text, "spec": spec_text}, env=None,
        )


def test_static_rows_shape_is_reserved_before_decoder(monkeypatch):
    from gee.smile_rf_spec import MAX_ROWS

    spec_text = _spec()
    required_shape = MAX_ROWS * 3
    monkeypatch.setattr(training, "MAX_RF_RUNTIME_WORK", required_shape - 1)

    def forbidden_decode(*_args):
        pytest.fail("static RF row shape was decoded before object-work reservation")

    monkeypatch.setattr("gee.smile_rf_spec.decode_rf_rows", forbidden_decode)
    with pytest.raises(ValueError, match="150000-step object-work budget"):
        adapters.local_ee_train_smile_rf_rows(
            {"rows": _rows_text(spec_text), "spec": spec_text}, env=None,
        )


def test_sample_prepare_wire_bound_is_reserved_before_prepare(monkeypatch):
    table = _sample_table()
    spec_text = _spec()
    wire_upper = training._rf_wire_upper_bound(table.row_count, 2)
    spec_charge = 2 * len(spec_text.encode("utf-8"))
    monkeypatch.setattr(training, "MAX_RF_WIRE_SCAN_BYTES", spec_charge + wire_upper - 1)

    def forbidden_prepare(*_args):
        pytest.fail("prepare_rf_rows ran before its wire-bound reservation")

    monkeypatch.setattr("gee.smile_rf_spec.prepare_rf_rows", forbidden_prepare)
    with pytest.raises(ValueError, match="3000000-byte wire-scan budget"):
        adapters.local_ee_train_smile_rf_samples(
            {"data": table, "spec": spec_text}, env=None,
        )


def test_sample_revalidation_wire_bound_is_reserved_before_decoder(monkeypatch):
    table = _sample_table()
    spec_text = _spec()
    wire_upper = training._rf_wire_upper_bound(table.row_count, 2)
    spec_charge = 2 * len(spec_text.encode("utf-8"))
    monkeypatch.setattr(
        training, "MAX_RF_WIRE_SCAN_BYTES",
        spec_charge + 3 * wire_upper - 1,
    )

    def forbidden_decode(*_args):
        pytest.fail("decode_rf_rows ran before its wire-bound reservation")

    monkeypatch.setattr("gee.smile_rf_spec.decode_rf_rows", forbidden_decode)
    with pytest.raises(ValueError, match="3000000-byte wire-scan budget"):
        adapters.local_ee_train_smile_rf_samples(
            {"data": table, "spec": spec_text}, env=None,
        )


def test_sample_prepare_shape_is_reserved_before_prepare(monkeypatch):
    table = _sample_table()
    spec_text = _spec()
    work = _sample_object_work(table)
    cap = work["copy"] + work["feature_rows"] + work["prepare_shape"] - 1
    monkeypatch.setattr(training, "MAX_RF_RUNTIME_WORK", cap)

    def forbidden_prepare(*_args):
        pytest.fail("prepare_rf_rows ran before its object-shape reservation")

    monkeypatch.setattr("gee.smile_rf_spec.prepare_rf_rows", forbidden_prepare)
    with pytest.raises(ValueError, match="150000-step object-work budget"):
        adapters.local_ee_train_smile_rf_samples(
            {"data": table, "spec": spec_text}, env=None,
        )


def test_sample_decode_shape_is_reserved_before_decoder(monkeypatch):
    table = _sample_table()
    spec_text = _spec()
    work = _sample_object_work(table)
    cap = sum(work.values()) - 1
    monkeypatch.setattr(training, "MAX_RF_RUNTIME_WORK", cap)

    def forbidden_decode(*_args):
        pytest.fail("decode_rf_rows ran before its object-shape reservation")

    monkeypatch.setattr("gee.smile_rf_spec.decode_rf_rows", forbidden_decode)
    with pytest.raises(ValueError, match="150000-step object-work budget"):
        adapters.local_ee_train_smile_rf_samples(
            {"data": table, "spec": spec_text}, env=None,
        )


def test_tree_work_bound_is_checked_before_sample_deep_copy(monkeypatch):
    spec_text = _spec(
        schema=tuple(f"x{index}" for index in range(8)),
        number_of_trees=256, variables_per_split=8, max_nodes=None,
    )
    rows = [
        {"type": "Feature", "id": f"f0_r0_c{index}", "geometry": None,
         "properties": {"landcover": index % 2,
                        **{f"x{column}": index + column / 10 for column in range(8)}}}
        for index in range(1000)
    ]
    columns = ["system:index", "landcover", *[f"x{index}" for index in range(8)], ".geo"]
    table = _sample_table(rows=rows, columns=columns)

    def forbidden_copy(_):
        pytest.fail("sample data was copied before the separate tree-work bound")

    monkeypatch.setattr(SampledFeatureTable, "data", property(forbidden_copy))
    with pytest.raises(ValueError, match="1000000000 training-work budget"):
        adapters.local_ee_train_smile_rf_samples(
            {"data": table, "spec": spec_text}, env=None,
        )


@pytest.mark.parametrize("change", [
    {"landcover": None}, {"landcover": True}, {"landcover": 0.5},
    {"red": float("nan")}, {"nir": float("inf")}, {"red": 2**53 + 1},
])
def test_actual_sample_rows_reject_bad_labels_and_numeric_values(change):
    spec_text = _spec()
    features = [
        {"type": "Feature", "id": "f0_r0_c0", "geometry": None,
         "properties": {"landcover": 0, "red": 1, "nir": 2}},
        {"type": "Feature", "id": "f0_r0_c1", "geometry": None,
         "properties": {"landcover": 1, "red": 3, "nir": 4}},
    ]
    features[0]["properties"].update(change)
    with pytest.raises(ValueError):
        adapters.local_ee_train_smile_rf_samples(
            {"data": _sample_table(rows=features), "spec": spec_text}, env=None,
        )


@pytest.mark.parametrize("arguments", [
    {"rows": "{}"}, {"rows": _rows_text(), "spec": _spec(), "extra": True},
])
def test_training_handlers_recheck_exact_arguments(arguments):
    with pytest.raises(ValueError):
        adapters.local_ee_train_smile_rf_rows(arguments, env=None)
