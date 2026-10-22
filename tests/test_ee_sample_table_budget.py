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


def test_output_cell_cost_rejects_before_result_table_constructor(monkeypatch):
    table = _table()
    operation = prepare_sample_limit(1)
    input_cells = table.row_count * len(table.columns)
    output_cells = len(table.columns)
    prior_cost = (
        len(table.sample_spec.encode("utf-8"))
        + len(operation.encode("utf-8"))
        + input_cells + table.row_count
    )
    monkeypatch.setattr(
        table_ops, "MAX_SAMPLE_TABLE_WORK", prior_cost + output_cells - 1
    )
    constructions = []

    def forbidden_constructor(self, *args, **kwargs):
        constructions.append((args, kwargs))
        raise AssertionError("output table construction must be precharged")

    monkeypatch.setattr(SampledFeatureTable, "__init__", forbidden_constructor)
    with pytest.raises(ValueError, match="50000-step work budget"):
        adapters.local_ee_sample_table_op({"data": table, "spec": operation}, env=None)
    assert constructions == []
