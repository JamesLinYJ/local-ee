"""Attestation-cache bounds and mutation checks for classified table ops."""
from __future__ import annotations

import pytest
from openeo_driver.processgraph.registry import ENV_DRY_RUN_TRACER

from engine.ee_json_result import (
    PendingRuntimeTable, RuntimeFeatureTable, attach_classification_origin,
)
from engine.ee_process_adapters import local_ee_runtime_table_op
from engine.ee_runtime_table_lineage import (
    CACHE_ATTESTATION_WORK, MAX_VERIFIED_ORIGIN_CACHE,
    cache_entry_count, clear_cache, is_cached,
)
from engine.ee_runtime_table_ops import validate_runtime_table_origin
from gee.random_column_spec import prepare_random_column_spec
from gee.rf_validation_spec import prepare_classify_spec
from gee.sample_table_spec import prepare_sample_limit


HEADERS = ["system:index", "truth", "reflectance", "prediction", ".geo"]
ORIGIN = prepare_classify_spec("prediction", HEADERS)


def _table():
    table = RuntimeFeatureTable({"type": "FeatureCollection", "features": []}, HEADERS)
    return attach_classification_origin(table, ORIGIN)


def _run(table, spec, env=None):
    return local_ee_runtime_table_op({"data": table, "spec": spec}, env=env)


@pytest.mark.parametrize("field", ["origin", "operations", "headers", "work"])
def test_cached_attestation_rejects_mutated_provenance_header_or_work(field):
    table = _run(
        _table(), prepare_random_column_spec("split", row_keys=["system:index"]),
    )
    if field == "origin":
        table.classification_origin_spec = table.classification_origin_spec.encode().decode()
        assert table.classification_origin_spec == ORIGIN
        assert table.classification_origin_spec is not ORIGIN
    elif field == "operations":
        previous = table.runtime_operations
        table.runtime_operations = tuple(list(table.runtime_operations))
        assert table.runtime_operations == (prepare_random_column_spec(
            "split", row_keys=["system:index"],
        ),)
        assert table.runtime_operations is not previous
    elif field == "headers":
        previous = table._columns
        table._columns = tuple(list(table._columns))
        assert table._columns == tuple([*HEADERS[:-1], "split", ".geo"])
        assert table._columns is not previous
    else:
        table.runtime_operation_work += 1

    with pytest.raises(ValueError, match="header/work metadata changed"):
        _run(table, prepare_sample_limit(1))


def test_forged_cache_like_attributes_cannot_attest_invalid_origin():
    table = _table()
    table.classification_origin_spec = "not-canonical-json"
    table._verified_origin_state = (ORIGIN, (), table._columns, 0, 0, 0)
    table._runtime_schema_cache = tuple(HEADERS)

    with pytest.raises(ValueError, match="canonical|JSON|Expecting"):
        _run(table, prepare_sample_limit(1))


def test_cache_is_bounded_and_evicted_origin_is_fully_revalidated(monkeypatch):
    from engine.ee_sample_table_ops import _SampleOperationContext
    from gee import runtime_table_spec

    clear_cache()
    tables = [_table() for _ in range(MAX_VERIFIED_ORIGIN_CACHE + 1)]
    for table in tables:
        validate_runtime_table_origin(table, _SampleOperationContext(0))
    assert cache_entry_count() == MAX_VERIFIED_ORIGIN_CACHE
    assert not is_cached(tables[0])

    parses = []
    real_runtime_columns = runtime_table_spec.runtime_columns

    def count_parse(*args, **kwargs):
        parses.append(1)
        return real_runtime_columns(*args, **kwargs)

    monkeypatch.setattr(runtime_table_spec, "runtime_columns", count_parse)
    _run(tables[0], prepare_sample_limit(1))
    assert len(parses) == 1


def test_validation_charges_cache_population_without_rewriting_input_work():
    from engine.ee_sample_table_ops import _SampleOperationContext

    table = _table()
    work = _SampleOperationContext(0)
    validate_runtime_table_origin(table, work)

    assert work.steps >= CACHE_ATTESTATION_WORK
    assert table.runtime_operation_work == 0


def test_result_work_includes_input_and_output_attestation_bookkeeping():
    clear_cache()
    result = _run(_table(), prepare_sample_limit(1))

    assert result.runtime_operation_work >= 2 * CACHE_ATTESTATION_WORK
    assert is_cached(result)


def test_actual_and_pending_steps_return_fresh_header_tuples():
    actual = _table()
    actual_result = _run(
        actual, prepare_random_column_spec("split", row_keys=["system:index"]),
    )
    assert actual_result._columns == (*actual._columns[:-1], "split", ".geo")
    assert actual_result._columns is not actual._columns

    tracer = object()
    pending = PendingRuntimeTable(HEADERS, data_tracer=tracer)
    attach_classification_origin(pending, ORIGIN)
    pending_result = _run(
        pending, prepare_sample_limit(1), {ENV_DRY_RUN_TRACER: tracer},
    )
    assert pending_result.columns == pending.columns
    assert pending_result.columns is not pending.columns
