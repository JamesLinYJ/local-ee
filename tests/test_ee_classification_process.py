"""Trusted process validation, metadata, and dispatch; no native execution claims."""
from copy import deepcopy

import pytest
from openeo.metadata import Band, BandDimension, CollectionMetadata, SpatialDimension, TemporalDimension
from openeo_driver.datacube import DriverDataCube
from openeo_driver.dry_run import DataSource, DryRunDataCube, DryRunDataTracer

from engine import ee_process_adapters as adapters
from gee.backend import Processes
from gee.graph import collection_loads, materialize, validate
from gee.local_processes import validate_local_process


PROCESS = "local_ee_minimum_distance"


def model():
    return {"version": 1, "metric": "euclidean", "schema": ["nir", "red"],
            "labels": [0, 2], "centers": [[["3", "1"], ["0", "1"]],
                                         [["1", "3"], ["1", "2"]]]}


def metadata(names=("nir", "red"), timed=True):
    dimensions = [SpatialDimension("x", (1, 3), crs=4326),
                  SpatialDimension("y", (2, 4), crs=4326)]
    if timed:
        dimensions.append(TemporalDimension("t", ("2025-01-01", "2025-01-03")))
    return CollectionMetadata({}, dimensions=dimensions + [
        BandDimension("bands", [Band(name) for name in names])])


def dry_cube(names=("nir", "red"), timed=True):
    tracer = DryRunDataTracer()
    source = tracer.add_trace(DataSource("load_collection", {"id": "sample"}))
    return DryRunDataCube([source], tracer, metadata=metadata(names, timed))


def process_graph():
    return {
        "load": {"process_id": "load_collection", "arguments": {"id": "sample"}},
        "classify": {"process_id": PROCESS,
                     "arguments": {"data": {"from_node": "load"}, "model": model()},
                     "result": True},
    }


def test_classifier_graph_validates_freezes_catalog_and_publishes_honest_spec():
    graph = process_graph()
    validate(graph)
    assert collection_loads(graph) == {"sample": ("sample", None)}
    frozen = materialize(graph, ["sample"], "/tmp/classifier-test")
    assert frozen["load"]["process_id"] == "load_stac"
    assert frozen["classify"]["arguments"]["model"] == model()
    assert graph["load"]["process_id"] == "load_collection"
    spec = Processes().get_process_registry("1.2.0").get_spec(PROCESS)
    assert [p["name"] for p in spec["parameters"]] == ["data", "model"]
    assert "Int32 NoData" in spec["returns"]["description"]
    assert "unverified" in spec["description"]


@pytest.mark.parametrize("arguments,depth", [
    ({"data": {"from_node": "load"}}, 0),
    ({"data": "/tmp/data.tif", "model": model()}, 0),
    ({"data": {"from_parameter": "data"}, "model": model()}, 0),
    ({"data": {"from_node": "load"}, "model": model(), "extra": True}, 0),
    ({"data": {"from_node": "load"}, "model": model()}, 1),
    ({"data": {"from_node": "load"}, "model": {"from_node": "load"}}, 0),
])
def test_classifier_process_rejects_noncanonical_arguments_and_callbacks(arguments, depth):
    with pytest.raises(ValueError):
        validate_local_process(PROCESS, arguments, depth)


@pytest.mark.parametrize("change", [
    {"version": True}, {"version": 2}, {"metric": "mahalanobis"},
    {"schema": ["nir", "nir"]}, {"labels": [2, 0]}, {"labels": [False, 2]},
    {"centers": [[["2", "6"], ["0", "1"]], [["1", "3"], ["1", "2"]]]},
])
def test_model_is_rechecked_by_both_protocol_and_engine_bridge(change):
    invalid = model() | deepcopy(change)
    with pytest.raises(ValueError):
        validate_local_process(PROCESS, {"data": {"from_node": "load"}, "model": invalid}, 0)
    with pytest.raises(ValueError):
        adapters.local_ee_minimum_distance({"data": dry_cube(), "model": invalid}, None)


@pytest.mark.parametrize("timed", [False, True])
def test_dry_run_keeps_grid_time_and_sources_but_returns_only_v(timed):
    cube = dry_cube(timed=timed)
    result = adapters.local_ee_minimum_distance({"data": cube, "model": model()}, None)
    assert result.metadata.band_names == ["v"]
    assert result.metadata.dimension_names() == cube.metadata.dimension_names()
    assert result.metadata.spatial_dimensions == cube.metadata.spatial_dimensions
    assert result.metadata.has_temporal_dimension() is timed
    if timed:
        assert result.metadata.temporal_dimension.extent == cube.metadata.temporal_dimension.extent
    assert result._traces is cube._traces


@pytest.mark.parametrize("names", [("red", "nir"), ("nir",), ("nir", "red", "aux")])
def test_engine_bridge_requires_schema_order_even_if_names_overlap(names):
    with pytest.raises(ValueError, match="schema names and order"):
        adapters.local_ee_minimum_distance({"data": dry_cube(names), "model": model()}, None)


def test_native_dispatch_forwards_exact_model_without_changing_layer_type(monkeypatch):
    cube = DriverDataCube(metadata=metadata())
    expected_model = model()
    calls = []

    def capture(*args, **kwargs):
        calls.append((args, kwargs))
        return "trusted-native-dispatch"

    monkeypatch.setattr(adapters, "_apply_native", capture)
    result = adapters.local_ee_minimum_distance({"data": cube, "model": expected_model}, None)
    args, kwargs = calls[0]
    assert result == "trusted-native-dispatch"
    assert args[:2] == (cube, PROCESS)
    assert args[2]["model"] is expected_model
    assert args[3].band_names == ["v"]
    assert not kwargs  # retain input spatial/spatiotemporal layer type


def test_both_registries_include_classifier_and_reject_replacement(monkeypatch):
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
    adapters.register_local_ee_processes()
    for registry in (first, second):
        assert registry.get_function(PROCESS) is adapters.local_ee_minimum_distance
    first.handlers[PROCESS] = lambda *args: None
    with pytest.raises(RuntimeError, match="Refusing to replace"):
        adapters.register_local_ee_processes()
