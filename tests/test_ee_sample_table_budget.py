"""Pre-allocation work checks for actual sampled-table operations."""
from __future__ import annotations

import pytest

from engine import ee_process_adapters as adapters
from engine import ee_sample_table_ops as table_ops
from engine.ee_sampling_result import SampledFeatureTable
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from gee.sample_table_spec import prepare_sample_limit
from ee_sampling_bridge_helpers import _spec


def _table():
    sample_spec = _spec()
    columns = sampling_columns(decode_sampling_spec(sample_spec))
    features = [{
        "type": "Feature", "id": f"f0_r0_c{index}",
        "geometry": {"type": "Point", "coordinates": [index + .5, 2.5]},
        "properties": {
            "plot_id": f"plot-{index}", "landcover": index % 2,
            "red": index + 1, "nir": index + 2,
        },
    } for index in range(3)]
    table = SampledFeatureTable(
        {"type": "FeatureCollection", "features": features}, columns,
    )
    table.sample_spec = sample_spec
    table.sample_spec_verified = True
    table.sample_operations = ()
    table.sample_operation_work = 0
    return table


def _blob_features(rows, blob_size):
    """Build independent nested payloads so the deepcopy bound has no aliases."""
    return [{
        "type": "Feature", "id": f"f0_r0_c{index}",
        "geometry": {"type": "Point", "coordinates": [index + .5, 2.5]},
        "properties": {
            "plot_id": f"plot-{index}", "landcover": index % 2,
            "red": index + 1, "nir": index + 2,
            # Each row owns a separate list; repeated integer scalars are
            # immutable and do not create shared nested containers.
            "blob": [index] * blob_size,
        },
    } for index in range(rows)]


def _blob_spec(*, long_plot_ids=False):
    regions = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [index + .5, 2.5]},
        "properties": {
            "plot_id": ("x" * 3000 + str(index)) if long_plot_ids else f"plot-{index}",
            "landcover": index % 2,
            "blob": None,
        },
    } for index in range(10)]
    return _spec(
        properties=["plot_id", "landcover", "blob"], features=regions
    )


def _large_table(*, sample_spec=None, rows=10, blob_size=1500):
    sample_spec = _blob_spec() if sample_spec is None else sample_spec
    columns = sampling_columns(decode_sampling_spec(sample_spec))
    table = SampledFeatureTable(
        {"type": "FeatureCollection", "features": _blob_features(rows, blob_size)},
        columns,
    )
    table.sample_spec = sample_spec
    table.sample_spec_verified = True
    table.sample_operations = ()
    table.sample_operation_work = 50
    return table


def test_input_cell_cost_rejects_before_data_property_deepcopy(monkeypatch):
    table = _table()
    operation = prepare_sample_limit(None)
    cells = table.row_count * len(table.columns)
    prior_cost = len(table.sample_spec.encode("utf-8")) + len(operation.encode("utf-8"))
    table.sample_operation_work = table_ops.MAX_SAMPLE_TABLE_WORK - prior_cost - cells + 1
    reads = []
    original = SampledFeatureTable.data
    monkeypatch.setattr(
        SampledFeatureTable,
        "data",
        property(lambda instance: reads.append(instance) or original.fget(instance)),
    )

    with pytest.raises(ValueError, match="50000-step work budget"):
        adapters.local_ee_sample_table_op({"data": table, "spec": operation}, env=None)
    assert reads == []


def test_original_sample_spec_cost_is_charged_before_decoding(monkeypatch):
    table = _table()
    spec_bytes = len(table.sample_spec.encode("utf-8"))
    table.sample_operation_work = table_ops.MAX_SAMPLE_TABLE_WORK - spec_bytes + 1
    operation = prepare_sample_limit(1)
    import gee.sampling_spec as sampling_spec

    decodes = []
    monkeypatch.setattr(
        sampling_spec, "decode_sampling_spec",
        lambda text: decodes.append(text),
    )
    with pytest.raises(ValueError, match="50000-step work budget"):
        adapters.local_ee_sample_table_op({"data": table, "spec": operation}, env=None)
    assert decodes == []


def test_prior_operation_cost_is_charged_before_decoding(monkeypatch):
    table = _table()
    prior = prepare_sample_limit(1)
    table.sample_operations = (prior,)
    prior_bytes = len(prior.encode("utf-8"))
    sample_bytes = len(table.sample_spec.encode("utf-8"))
    table.sample_operation_work = table_ops.MAX_SAMPLE_TABLE_WORK - sample_bytes - prior_bytes + 1
    operation = prepare_sample_limit(2)
    import gee.sample_table_spec as sample_table_spec

    decodes = []
    monkeypatch.setattr(
        sample_table_spec, "decode_sample_operation",
        lambda text: decodes.append(text),
    )
    with pytest.raises(ValueError, match="50000-step work budget"):
        adapters.local_ee_sample_table_op({"data": table, "spec": operation}, env=None)
    assert decodes == []


def test_output_full_copy_cost_rejects_before_result_table_constructor(monkeypatch):
    nested = _large_table()
    operation_work = prepare_sample_limit(None)
    before_output = (
        nested.sample_operation_work
        + len(nested.sample_spec.encode("utf-8"))
        + len(operation_work.encode("utf-8"))
        + nested.row_count * len(nested.columns)
        + nested.data_copy_work
        + nested.row_count
    )
    output_copy = SampledFeatureTable._measure_copy_work(nested._data)
    assert before_output < table_ops.MAX_SAMPLE_TABLE_WORK
    assert (
        before_output + nested.row_count * len(nested.columns) + output_copy
        > table_ops.MAX_SAMPLE_TABLE_WORK
    )
    constructions = []
    reads = []
    original_data = SampledFeatureTable.data
    monkeypatch.setattr(
        SampledFeatureTable,
        "data",
        property(lambda instance: reads.append(instance) or original_data.fget(instance)),
    )

    def forbidden_constructor(self, *args, **kwargs):
        constructions.append((args, kwargs))
        raise AssertionError("output table construction must be precharged")

    monkeypatch.setattr(SampledFeatureTable, "__init__", forbidden_constructor)
    with pytest.raises(ValueError, match="50000-step work budget"):
        adapters.local_ee_sample_table_op(
            {"data": nested, "spec": operation_work}, env=None
        )
    assert constructions == []
    assert reads == [nested]


def test_cached_full_input_copy_cost_rejects_before_data_getter(monkeypatch):
    long_spec = _blob_spec(long_plot_ids=True)
    table = _large_table(sample_spec=long_spec)
    assert 30_000 <= table.data_copy_work < 40_000
    assert 30_000 <= len(long_spec.encode("utf-8")) < 40_000
    operation = prepare_sample_limit(None)
    old_work = (
        table.sample_operation_work
        + len(long_spec.encode("utf-8"))
        + len(operation.encode("utf-8"))
        + table.row_count * len(table.columns)
        + table.row_count
        + table.row_count * len(table.columns)
    )
    assert old_work < table_ops.MAX_SAMPLE_TABLE_WORK
    assert old_work + table.data_copy_work > table_ops.MAX_SAMPLE_TABLE_WORK
    reads = []
    original = SampledFeatureTable.data
    monkeypatch.setattr(
        SampledFeatureTable,
        "data",
        property(lambda instance: reads.append(instance) or original.fget(instance)),
    )

    with pytest.raises(ValueError, match="50000-step work budget"):
        adapters.local_ee_sample_table_op({"data": table, "spec": operation}, env=None)
    assert reads == []
