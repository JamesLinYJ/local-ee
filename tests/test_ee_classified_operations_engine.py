"""Engine checks for bounded post-classification table operations."""
from __future__ import annotations

import pytest
from openeo_driver.processgraph.registry import ENV_DRY_RUN_TRACER

from engine import ee_process_adapters as adapters
from engine.ee_json_result import (
    PendingRuntimeTable, RuntimeFeatureTable, attach_classification_origin,
)
from gee.compat.earthengine.ir import Filter
from gee.random_column_spec import prepare_random_column_spec
from gee.rf_validation_spec import prepare_classify_spec, prepare_matrix_spec
from gee.sample_table_spec import prepare_sample_filter, prepare_sample_limit


HEADERS = ["system:index", "truth", "reflectance", "prediction", ".geo"]


def _origin_spec():
    return prepare_classify_spec("prediction", HEADERS)


def _features(count=3):
    rows = []
    for index in range(count):
        feature = {
            "type": "Feature",
            "id": ["feature/id with spaces", "feature:two", "feature-three"][index],
            "geometry": {"type": "Point", "coordinates": [index + 0.25, 5.5]},
            "properties": {
                "truth": index % 2,
                "reflectance": 0.25 + index,
                "prediction": (index + 1) % 2,
            },
        }
        if index == 1:
            feature["id"] = "f0_r0_c999999999999999999999"
            feature["properties"]["system:index"] = "declared-index"
        rows.append(feature)
    return rows


def _table(*, count=3, prior_count=0, prior_work=0, operations=(), operation_work=None):
    data = {
        "type": "FeatureCollection",
        "properties": {"band_order": ["reflectance"]},
        "features": _features(count),
    }
    table = RuntimeFeatureTable(data, HEADERS)
    source = object()
    table.traces = (source,)
    attach_classification_origin(
        table, _origin_spec(),
        prior_sample_operation_count=prior_count,
        prior_sample_operation_work=prior_work,
        operations=operations,
        operation_work=operation_work,
    )
    return table, source


def _run(table, spec, env=None):
    return adapters.local_ee_runtime_table_op({"data": table, "spec": spec}, env=env)


def test_filter_uses_literal_feature_ids_and_property_system_index_precedence():
    table, _ = _table()
    before = table.data
    by_id = _run(table, prepare_sample_filter(Filter("equals", {
        "leftField": "system:index", "rightValue": "feature/id with spaces",
    })))
    by_property = _run(table, prepare_sample_filter(Filter("equals", {
        "leftField": "system:index", "rightValue": "declared-index",
    })))

    assert type(by_id) is RuntimeFeatureTable
    assert [row["id"] for row in by_id.data["features"]] == ["feature/id with spaces"]
    assert [row["id"] for row in by_property.data["features"]] == [
        "f0_r0_c999999999999999999999",
    ]
    assert by_id.data["features"][0]["geometry"] == before["features"][0]["geometry"]
    assert by_id.data["properties"] == before["properties"]
    assert table.data == before


def test_random_column_then_unsorted_limit_preserves_lineage_and_input():
    table, source = _table()
    before = table.data
    random_spec = prepare_random_column_spec(
        "split", seed=23, row_keys=["system:index"],
    )

    randomized = _run(table, random_spec)
    limited = _run(randomized, prepare_sample_limit(2))

    assert type(randomized) is RuntimeFeatureTable
    assert randomized.columns == [*HEADERS[:-1], "split", ".geo"]
    assert len(randomized.data["features"]) == 3
    assert all(type(row["properties"]["split"]) is float
               for row in randomized.data["features"])
    assert [row["id"] for row in limited.data["features"]] == [
        row["id"] for row in before["features"][:2]
    ]
    assert table.data == before
    assert randomized.classification_origin_spec == _origin_spec()
    assert randomized.runtime_operations == (random_spec,)
    assert limited.runtime_operations == (random_spec, prepare_sample_limit(2))
    assert limited.prior_sample_operation_count == 0
    assert limited.prior_sample_operation_work == 0
    assert limited.runtime_operation_work > randomized.runtime_operation_work > 0
    assert randomized.traces == limited.traces == (source,)
    assert randomized.data_tracer is limited.data_tracer is None


@pytest.mark.parametrize("spec", [
    prepare_sample_filter(Filter("equals", {
        "leftField": "truth", "rightValue": 99,
    })),
    prepare_sample_limit(0),
    prepare_random_column_spec("split", row_keys=["system:index"]),
])
def test_empty_classified_tables_keep_declared_schema_and_never_fabricate_rows(spec):
    table, _ = _table(count=0)

    result = _run(table, spec)

    assert type(result) is RuntimeFeatureTable
    assert result.row_count == 0
    assert result.columns == (HEADERS if '"operation":"random_column"' not in spec
                              else [*HEADERS[:-1], "split", ".geo"])
    assert result.data["features"] == []


def test_pending_chain_reuses_only_the_same_dry_run_tracer_and_has_no_rows():
    tracer = object()
    source = object()
    table = PendingRuntimeTable(HEADERS, traces=(source,), data_tracer=tracer)
    attach_classification_origin(table, _origin_spec())

    result = _run(table, prepare_sample_limit(1), {ENV_DRY_RUN_TRACER: tracer})

    assert type(result) is PendingRuntimeTable
    assert result.data_tracer is tracer
    assert result.traces == (source,)
    assert result.columns == tuple(HEADERS)
    assert result.runtime_operations == (prepare_sample_limit(1),)
    assert not hasattr(result, "data")
    with pytest.raises(ValueError, match="dry run"):
        _run(table, prepare_sample_limit(1), {ENV_DRY_RUN_TRACER: object()})


def test_actual_table_in_a_dry_run_returns_pending_without_copying_rows(monkeypatch):
    table, source = _table()
    tracer = object()
    monkeypatch.setattr(
        RuntimeFeatureTable, "data",
        property(lambda _table: pytest.fail("dry run copied classified rows")),
    )

    result = _run(table, prepare_sample_limit(1), {ENV_DRY_RUN_TRACER: tracer})

    assert type(result) is PendingRuntimeTable
    assert result.data_tracer is tracer
    assert result.traces == (source,)
    assert not hasattr(result, "data")


def test_runtime_operation_rejects_nonexact_unverified_and_header_mismatched_tables():
    class RuntimeSubclass(RuntimeFeatureTable):
        pass

    table, _ = _table()
    with pytest.raises(ValueError, match="actual or pending classified table"):
        _run(RuntimeSubclass(table._data, HEADERS), prepare_sample_limit(1))

    table, _ = _table()
    table.classification_origin_verified = False
    with pytest.raises(ValueError, match="verified classification origin"):
        _run(table, prepare_sample_limit(1))

    table, _ = _table()
    table._columns = ("system:index", "wrong", ".geo")
    with pytest.raises(ValueError, match="columns differ"):
        _run(table, prepare_sample_limit(1))


def test_standalone_runtime_tables_keep_existing_sinks_but_are_not_op_origins():
    standalone = RuntimeFeatureTable({
        "type": "FeatureCollection", "features": _features(1),
    }, HEADERS)
    assert standalone.create_flask_response().get_json()["features"]

    with pytest.raises(ValueError):
        _run(standalone, prepare_sample_limit(1))


def test_malformed_chain_and_inconsistent_cumulative_work_are_rejected():
    table, _ = _table()
    table.runtime_operations = [prepare_sample_limit(1)]
    with pytest.raises(ValueError, match="tuple"):
        _run(table, prepare_sample_limit(1))

    table, _ = _table()
    table.runtime_operation_work = 50_001
    with pytest.raises(ValueError, match="cumulative operation work"):
        _run(table, prepare_sample_limit(1))

    table, _ = _table(operations=("not-json",), operation_work=100)
    with pytest.raises(ValueError, match="JSON|canonical|Expecting"):
        _run(table, prepare_sample_limit(1))

    table, _ = _table(prior_count=1, prior_work=100)
    table.runtime_operation_work = 99
    with pytest.raises(ValueError, match="inherited or cumulative"):
        _run(table, prepare_sample_limit(1))

    table, _ = _table()
    table.prior_sample_operation_count = 1
    with pytest.raises(ValueError, match="count/work metadata"):
        _run(table, prepare_sample_limit(1))


def test_sampled_operation_count_and_total_runtime_work_are_carried_forward():
    table, _ = _table(prior_count=16, prior_work=100)
    with pytest.raises(ValueError, match="16 operations"):
        _run(table, prepare_sample_limit(1))

    table, _ = _table(prior_count=15, prior_work=100)
    final_allowed = _run(table, prepare_sample_limit(1))
    assert len(final_allowed.runtime_operations) == 1
    with pytest.raises(ValueError, match="16 operations"):
        _run(final_allowed, prepare_sample_limit(1))

    table, _ = _table(prior_count=1, prior_work=49_900)
    with pytest.raises(ValueError, match="50000-step work budget"):
        _run(table, prepare_sample_limit(1))


def test_sixteen_small_overwrite_and_limit_operations_fit_actual_header_work():
    table, _ = _table(count=3)
    overwrite = prepare_random_column_spec("split", row_keys=["system:index"])

    for _ in range(12):
        table = _run(table, overwrite)
    for _ in range(4):
        table = _run(table, prepare_sample_limit(2))

    assert len(table.runtime_operations) == 16
    assert table.row_count == 2
    assert table.columns == [*HEADERS[:-1], "split", ".geo"]


def test_near_cap_origin_is_precharged_before_schema_parse_or_data_copy(monkeypatch):
    from gee import runtime_table_spec

    table, _ = _table(
        operations=(prepare_sample_limit(1),), operation_work=49_999,
    )
    table.classification_origin_spec = "x" * 16_384
    monkeypatch.setattr(
        runtime_table_spec, "runtime_columns",
        lambda *_args: pytest.fail("near-cap origin reached schema parsing"),
    )
    monkeypatch.setattr(
        RuntimeFeatureTable, "data",
        property(lambda _table: pytest.fail("near-cap validation copied rows")),
    )

    with pytest.raises(ValueError, match="50000-step work budget"):
        _run(table, prepare_sample_limit(1))


def test_error_matrix_and_getinfo_revalidate_classification_headers():
    table, _ = _table(count=1)
    assert table.create_flask_response().get_json()["features"]

    table._columns = ("system:index", "wrong", ".geo")
    with pytest.raises(ValueError, match="header/work metadata changed"):
        table.create_flask_response()
    with pytest.raises(ValueError, match="header/work metadata changed"):
        from engine.ee_rf_validation import local_ee_error_matrix

        local_ee_error_matrix({
            "data": table,
            "spec": prepare_matrix_spec("truth", "prediction", [0, 1]),
        }, env=None)


def test_rf_matrix_validation_inherits_actual_and_pending_table_operation_work(monkeypatch):
    from engine import ee_rf_validation, ee_runtime_table_ops
    from engine.ee_rf_validation_matrix import PendingRfConfusionMatrix
    from engine.ee_rf_validation_runtime import OperationBudget, actual_table

    table, _ = _table(count=1, prior_work=2_000)
    validated_at = []
    real_validate = ee_runtime_table_ops.validate_runtime_table_origin

    def record_work(value, work):
        validated_at.append(work.steps)
        return real_validate(value, work)

    monkeypatch.setattr(ee_runtime_table_ops, "validate_runtime_table_origin", record_work)
    budget = OperationBudget()
    payload, columns, pending = actual_table(table, budget, allow_runtime=True)
    assert type(payload) is dict and not pending
    assert columns == tuple(HEADERS)
    assert validated_at[-1] >= table.runtime_operation_work
    assert budget.steps > table.runtime_operation_work

    tracer = object()
    pending_table = PendingRuntimeTable(HEADERS, data_tracer=tracer)
    attach_classification_origin(
        pending_table, _origin_spec(), prior_sample_operation_work=2_000,
    )
    matrix = ee_rf_validation.local_ee_error_matrix({
        "data": pending_table,
        "spec": prepare_matrix_spec("truth", "prediction", [0, 1]),
    }, env={ENV_DRY_RUN_TRACER: tracer})
    assert type(matrix) is PendingRfConfusionMatrix
    assert validated_at[-1] >= pending_table.runtime_operation_work


def test_runtime_table_process_is_registered_in_both_trusted_registries(monkeypatch):
    class Registry:
        def __init__(self):
            self.handlers = {}

        def contains(self, name):
            return name in self.handlers

        def get_function(self, name):
            return self.handlers[name]

        def add_hidden(self, handler):
            self.handlers[handler.__name__] = handler

    import openeo_driver.processgraph.registry as registries

    first, second = Registry(), Registry()
    monkeypatch.setattr(registries, "process_registry_100", first)
    monkeypatch.setattr(registries, "process_registry_2xx", second)
    adapters.register_local_ee_processes()

    assert first.get_function("local_ee_runtime_table_op") is adapters.local_ee_runtime_table_op
    assert second.get_function("local_ee_runtime_table_op") is adapters.local_ee_runtime_table_op
