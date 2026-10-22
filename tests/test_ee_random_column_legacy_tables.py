"""Legacy direct-table compatibility and malformed-lineage rejection controls."""
from __future__ import annotations

import pytest

from engine import ee_process_adapters as adapters
from engine.ee_sampling_result import SampledFeatureTable
from gee.random_column_spec import prepare_random_column_spec
from ee_sampling_bridge_helpers import _training_spec
from ee_smile_rf_engine_helpers import install_factory, sample_table, spec as rf_spec


def test_direct_v1_rf_table_rejects_untracked_operations_before_copy(monkeypatch):
    table = sample_table()
    table.sample_operations = (prepare_random_column_spec("split"),)
    calls = install_factory(monkeypatch)
    monkeypatch.setattr(SampledFeatureTable, "data", property(
        lambda _table: pytest.fail("unverified operations must fail before copying"),
    ))
    with pytest.raises(ValueError, match="verified origin and operation chain"):
        adapters.local_ee_train_smile_rf_samples({
            "data": table,
            "spec": rf_spec(schema=("red", "nir"), class_property="landcover"),
        }, env=None)
    assert calls == []


def test_direct_v1_rf_table_rejects_collection_image_metadata(monkeypatch):
    original = sample_table()
    data = original.data
    data["properties"] = {"band_order": ["red", "nir"]}
    table = SampledFeatureTable(data, original.columns)
    calls = install_factory(monkeypatch)
    with pytest.raises(ValueError, match="FeatureCollection fields"):
        adapters.local_ee_train_smile_rf_samples({
            "data": table,
            "spec": rf_spec(schema=("red", "nir"), class_property="landcover"),
        }, env=None)
    assert calls == []


def test_direct_v1_minimum_distance_keeps_bounded_prior_work():
    table = sample_table()
    table.sample_operation_work = 17
    model = adapters.local_ee_train_minimum_distance({
        "data": table,
        "spec": _training_spec(schema=["red"], class_property="landcover"),
    }, env=None)
    assert model["schema"] == ["red"]


def test_direct_minimum_distance_rejects_untracked_operations_before_copy(monkeypatch):
    table = sample_table()
    table.sample_operations = (prepare_random_column_spec("split"),)
    monkeypatch.setattr(SampledFeatureTable, "data", property(
        lambda _table: pytest.fail("unverified operations must fail before copying"),
    ))
    with pytest.raises(ValueError, match="verified origin and operation chain"):
        adapters.local_ee_train_minimum_distance({
            "data": table,
            "spec": _training_spec(schema=["red"], class_property="landcover"),
        }, env=None)


def test_direct_minimum_distance_rejects_collection_image_metadata():
    original = sample_table()
    data = original.data
    data["properties"] = {"band_order": ["red", "nir"]}
    table = SampledFeatureTable(data, original.columns)
    with pytest.raises(ValueError, match="FeatureCollection fields"):
        adapters.local_ee_train_minimum_distance({
            "data": table,
            "spec": _training_spec(schema=["red"], class_property="landcover"),
        }, env=None)
