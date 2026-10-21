"""Python metadata and trusted-registry behavior, without starting a JVM."""
import pytest

from openeo.metadata import Band, BandDimension, CollectionMetadata, SpatialDimension, TemporalDimension
from openeo_driver.dry_run import DataSource, DryRunDataCube, DryRunDataTracer

from engine import ee_process_adapters as adapters


def test_reducer_wire_contract_matches_api_validator():
    from gee.local_processes import EE_BAND_REDUCERS

    assert adapters.EE_BAND_REDUCERS == EE_BAND_REDUCERS


def _metadata():
    return CollectionMetadata(
        metadata={},
        dimensions=[
            SpatialDimension("x", (0, 2)),
            SpatialDimension("y", (0, 2)),
            TemporalDimension("t", ("2025-01-01T00:00:00Z", "2025-01-01T00:00:00Z")),
            BandDimension("bands", [Band("B2"), Band("B3")]),
        ],
    )


def _dry_run_cube():
    tracer = DryRunDataTracer()
    source = tracer.add_trace(DataSource("load_collection", {"id": "sample"}))
    return DryRunDataCube(traces=[source], data_tracer=tracer, metadata=_metadata())


def test_drop_single_time_dry_run_removes_only_time_and_preserves_source_trace():
    cube = _dry_run_cube()
    result = adapters.local_ee_drop_single_time({"data": cube}, env=None)

    assert result.metadata.dimension_names() == ["x", "y", "bands"]
    assert result.metadata.band_names == ["B2", "B3"]
    assert result._traces is cube._traces


def test_reduce_bands_dry_run_collapses_ordered_bands_to_v_and_preserves_time():
    cube = _dry_run_cube()
    result = adapters.local_ee_reduce_bands({"data": cube, "reducer": "median"}, env=None)

    assert result.metadata.dimension_names() == ["x", "y", "t", "bands"]
    assert result.metadata.band_names == ["v"]
    assert result.metadata.temporal_dimension.extent == cube.metadata.temporal_dimension.extent
    assert result._traces is cube._traces


@pytest.mark.parametrize(
    "arguments",
    [
        {"data": _dry_run_cube(), "reducer": "count", "extra": 1},
        {"data": _dry_run_cube(), "reducer": "unknown"},
        {"data": _dry_run_cube(), "reducer": {"from_node": "n"}},
    ],
)
def test_band_handler_rechecks_exact_arguments(arguments):
    with pytest.raises(ValueError):
        adapters.local_ee_reduce_bands(arguments, env=None)


def test_registration_is_idempotent_and_refuses_to_replace_handlers(monkeypatch):
    class Registry:
        def __init__(self):
            self.handlers = {}

        def contains(self, name):
            return name in self.handlers

        def get_function(self, name):
            return self.handlers[name]

        def add_hidden(self, handler):
            self.handlers[handler.__name__] = handler

    import openeo_driver.processgraph.registry as process_registry

    registries = Registry(), Registry()
    monkeypatch.setattr(process_registry, "process_registry_100", registries[0])
    monkeypatch.setattr(process_registry, "process_registry_2xx", registries[1])
    adapters.register_local_ee_processes()
    adapters.register_local_ee_processes()

    for registry in registries:
        assert registry.get_function("local_ee_drop_single_time") is adapters.local_ee_drop_single_time
        assert registry.get_function("local_ee_reduce_bands") is adapters.local_ee_reduce_bands

    registries[0].handlers["local_ee_drop_single_time"] = lambda args, env: None
    with pytest.raises(RuntimeError, match="Refusing to replace"):
        adapters.register_local_ee_processes()
