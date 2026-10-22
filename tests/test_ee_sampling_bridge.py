"""Dry-run schemas and trusted process registration for EE sampling."""
from __future__ import annotations

import pytest

from engine import ee_process_adapters as adapters
from engine.ee_sampling_result import PendingMinimumDistanceModel, PendingSampledTable
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from openeo_driver.datacube import DriverDataCube
from ee_sampling_bridge_helpers import _dry_cube, _metadata, _spec, _training_spec


def test_pending_sample_and_training_keep_schema_and_source_traces():
    training, train_source, tracer = _dry_cube()
    sample = adapters.local_ee_sample_regions({"data": training, "spec": _spec()}, env=None)
    assert type(sample) is PendingSampledTable
    assert sample.columns == tuple(sampling_columns(decode_sampling_spec(_spec())))
    assert sample.traces == (train_source,)
    assert sample.data_tracer is tracer

    model = adapters.local_ee_train_minimum_distance(
        {"data": sample, "spec": _training_spec()}, env=None
    )
    assert type(model) is PendingMinimumDistanceModel
    assert model.schema == ("red", "nir")
    assert model.metric == "euclidean"
    assert not hasattr(model, "centers")
    assert model.traces == (train_source,)
    assert model.data_tracer is tracer


def test_training_handler_rechecks_exact_arguments_and_canonical_spec():
    cube, _, _ = _dry_cube()
    sample = adapters.local_ee_sample_regions({"data": cube, "spec": _spec()}, env=None)
    with pytest.raises(ValueError, match="accepts exactly"):
        adapters.local_ee_train_minimum_distance(
            {"data": sample, "spec": _training_spec(), "extra": True}, env=None
        )
    with pytest.raises(ValueError, match="spec must be canonical JSON"):
        adapters.local_ee_train_minimum_distance(
            {"data": sample, "spec": {}}, env=None
        )


def test_pending_model_dry_run_classification_keeps_both_sources_and_schema():
    train_cube, train_source, tracer = _dry_cube(source_id="training")
    sample = adapters.local_ee_sample_regions({"data": train_cube, "spec": _spec()}, env=None)
    model = adapters.local_ee_train_minimum_distance(
        {"data": sample, "spec": _training_spec()}, env=None
    )
    image, image_source, _ = _dry_cube(tracer=tracer, source_id="classification")
    result = adapters.local_ee_minimum_distance({"data": image, "model": model}, env=None)

    assert result.metadata.band_names == ["v"]
    assert any(trace is train_source for trace in result._traces)
    assert any(trace is image_source for trace in result._traces)
    assert result._data_tracer is tracer


def test_pending_model_cannot_reach_actual_classifier_execution():
    cube = DriverDataCube(metadata=_metadata())
    pending = PendingMinimumDistanceModel("euclidean", ("red", "nir"), "landcover")
    with pytest.raises(ValueError, match="pending classifier model"):
        adapters.local_ee_minimum_distance({"data": cube, "model": pending}, env=None)


@pytest.mark.parametrize(
    "args,error",
    [
        ({"data": None, "spec": "{}", "extra": 1}, "exactly"),
        ({"data": None, "spec": {}}, "spec must be canonical JSON"),
    ],
)
def test_sample_handler_rechecks_exact_arguments_and_spec_type(args, error):
    cube, _, _ = _dry_cube()
    args["data"] = cube
    with pytest.raises(ValueError, match=error):
        adapters.local_ee_sample_regions(args, env=None)


def test_sample_handler_rejects_band_order_time_and_invalid_pending_training_schema():
    reversed_cube, _, _ = _dry_cube(bands=("nir", "red"))
    with pytest.raises(ValueError, match="band names and order"):
        adapters.local_ee_sample_regions({"data": reversed_cube, "spec": _spec()}, env=None)

    temporal_cube, _, _ = _dry_cube(temporal=True)
    with pytest.raises(ValueError, match="no time dimension"):
        adapters.local_ee_sample_regions({"data": temporal_cube, "spec": _spec()}, env=None)

    cube, _, _ = _dry_cube()
    sample = adapters.local_ee_sample_regions(
        {"data": cube, "spec": _spec(properties=["plot_id"])}, env=None
    )
    with pytest.raises(ValueError, match="missing training property"):
        adapters.local_ee_train_minimum_distance(
            {"data": sample, "spec": _training_spec()}, env=None
        )


def test_sampling_and_training_handlers_register_in_both_trusted_registries(monkeypatch):
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
    for registry in (first, second):
        assert registry.get_function("local_ee_sample_regions") is adapters.local_ee_sample_regions
        assert registry.get_function("local_ee_train_minimum_distance") is adapters.local_ee_train_minimum_distance
