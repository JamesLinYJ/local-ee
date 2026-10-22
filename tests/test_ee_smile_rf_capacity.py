"""RF bridge capacity acceptance using the bounded Python SampledFeatureTable."""
from __future__ import annotations

import json

from engine import ee_process_adapters as adapters
from engine import ee_smile_rf_training as training
from engine.ee_sampling_result import SampledFeatureTable
from engine.ee_smile_rf import TrainedSmileRfModel
from ee_smile_rf_engine_helpers import large_rf_sample_case, install_factory


def test_1000_by_8_sample_table_runs_python_bridge_into_test_factory(monkeypatch):
    """The proxy factory tests forwarding/encoding only; no real JVM is started."""
    spec_text, table, expected_rows = large_rf_sample_case(prior_work=50_000)
    calls = install_factory(monkeypatch)
    assert type(table) is SampledFeatureTable

    model = adapters.local_ee_train_smile_rf_samples(
        {"data": table, "spec": spec_text}, env=None,
    )

    assert type(model) is TrainedSmileRfModel
    assert calls == [(spec_text, expected_rows)]
    assert len(json.loads(calls[0][1])["rows"]) == 1000
    assert len(calls[0][1].encode("utf-8")) < training.MAX_RF_ROWS_JSON_BYTES

    object_charges = {
        "prior_table_operations": 50_000,
        "sample_copy": table.row_count * len(table.columns) + table.data_copy_work,
        "feature_to_rows": table.row_count * 9,
        "prepare_shape": table.row_count * 9,
        "decode_shape": table.row_count * 9,
    }
    wire_upper = training._rf_wire_upper_bound(table.row_count, 8)
    wire_charges = {
        "spec_parse_and_canonicalize": 2 * len(spec_text.encode("utf-8")),
        "prepare_rows_encode": wire_upper,
        "decode_and_canonicalize": 2 * wire_upper,
    }
    assert sum(object_charges.values()) <= training.MAX_RF_RUNTIME_WORK
    assert sum(wire_charges.values()) <= training.MAX_RF_WIRE_SCAN_BYTES
