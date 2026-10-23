"""Regression for pinned dry-run band-filter metadata and conservative recovery."""
import pytest
from shapely.geometry import box

from ee_sampling_bridge_helpers import _dry_cube, _metadata
from engine import ee_process_adapters as adapters
from engine.ee_neighborhood_metadata import single_band_metadata
from gee.convolve_spec import prepare_convolve_spec
from gee.focal_spec import prepare_focal_spec
from gee.neighborhood_spec import prepare_neighborhood_spec


@pytest.mark.parametrize("process,spec", [
    ("local_ee_focal", prepare_focal_spec("mean", [(0, 0), (1, 0)])),
    ("local_ee_convolve", prepare_convolve_spec([(0, 0, 1.0), (1, 0, -1.0)])),
    ("local_ee_neighborhood", prepare_neighborhood_spec("mean", [(0, 0, 0.5), (1, 0, 1.0)])),
])
def test_real_process_registry_evaluates_multiband_selection_and_blocks_output_pushdown(monkeypatch, process, spec):
    from openeo_driver import ProcessGraphDeserializer  # Register pinned standard processes.
    from openeo_driver.backend import CollectionCatalog, OpenEoBackendImplementation
    from openeo_driver.dry_run import DryRunDataTracer
    from openeo_driver.processgraph import registry
    from openeo_driver.processgraph.evaluator import evaluate
    from openeo_driver.utils import EvalEnv

    # Isolate local registrations; execute real standard load/filter/resample
    # handlers and our bridge without a native runtime or invented pixel values.
    for processes in (registry.process_registry_100, registry.process_registry_2xx):
        monkeypatch.setattr(processes, "_processes", dict(processes._processes))
    adapters.register_local_ee_processes()
    metadata = {"id": "synthetic", "cube:dimensions": {
        "x": {"type": "spatial", "axis": "x", "extent": [0, 4], "reference_system": 4326},
        "y": {"type": "spatial", "axis": "y", "extent": [0, 3], "reference_system": 4326},
        "t": {"type": "temporal", "extent": ["2025-01-01", "2025-01-02"]},
        "bands": {"type": "bands", "values": ["red", "nir"]},
    }}
    backend = OpenEoBackendImplementation(catalog=CollectionCatalog([metadata]),
                                          processing=registry.ConcreteProcessing())
    tracer = DryRunDataTracer()
    env = EvalEnv({"backend_implementation": backend, "openeo_api_version": "1.2.0",
                   registry.ENV_DRY_RUN_TRACER: tracer, "node_caching": False})
    full = {"west": 0, "south": 0, "east": 4, "north": 3, "crs": "EPSG:4326"}
    graph = {
        "source": {"process_id": "load_collection", "arguments": {
            "id": "synthetic", "spatial_extent": full,
            "temporal_extent": ["2025-01-01", "2025-01-02"]}},
        "band": {"process_id": "filter_bands", "arguments": {
            "data": {"from_node": "source"}, "bands": ["nir"]}},
        "kernel": {"process_id": process, "arguments": {
            "data": {"from_node": "band"}, "spec": spec}},
        "output": {"process_id": "resample_spatial", "arguments": {
            "data": {"from_node": "kernel"}, "resolution": 20, "projection": 32649}},
        "roi": {"process_id": "filter_bbox", "arguments": {
            "data": {"from_node": "output"},
            "extent": {"west": 1, "south": 1, "east": 2, "north": 2}}, "result": True},
    }
    result = evaluate(graph, env=env, do_dry_run=False)
    assert result.metadata.band_names == ["v"] and result.metadata.has_temporal_dimension()
    constraints = tracer.get_source_constraints()
    assert len(constraints) == 1
    assert constraints[0][1]["bands"] == ["nir"]
    assert constraints[0][1]["spatial_extent"] == full
    assert "resample" not in constraints[0][1]


@pytest.mark.parametrize("process,spec", [
    ("local_ee_focal", prepare_focal_spec("mean", [(0, 0), (1, 0)])),
    ("local_ee_convolve", prepare_convolve_spec([(0, 0, 1.0), (1, 0, -1.0)])),
    ("local_ee_neighborhood", prepare_neighborhood_spec("mean", [(0, 0, 0.5), (1, 0, 1.0)])),
])
def test_single_selected_band_from_multiband_source_preserves_owned_trace(process, spec):
    cube, source, tracer = _dry_cube(bands=("red", "nir"), temporal=True)
    filtered = cube.filter_bands(["nir"]).mask_polygon(box(0, 0, 2, 2))
    assert filtered.metadata.band_names == ["red", "nir"]  # Pinned upstream behavior.
    actual = getattr(adapters, process)({"data": filtered, "spec": spec}, None)
    assert actual.metadata.band_names == ["v"]
    assert actual.metadata.has_temporal_dimension()
    assert actual._data_tracer is tracer and actual._traces[0].get_source() is source
    assert cube.metadata.band_names == filtered.metadata.band_names == ["red", "nir"]
    assert tracer.get_source_constraints()[0][1]["bands"] == ["nir"]


@pytest.mark.parametrize("bands", [[], ["red", "nir"], [""], [0], ["x" * 257]])
def test_invalid_nearest_filter_cannot_be_hidden_by_single_source_metadata(bands):
    cube, _, _ = _dry_cube(bands=("red",))
    with pytest.raises(ValueError, match="exactly one"):
        single_band_metadata(cube.filter_bands(bands), "local_ee_convolve")


@pytest.mark.parametrize("operation", ["merge_cubes", "apply_dimension", "reduce_dimension", "unknown"])
def test_shape_changing_or_unknown_operation_prevents_old_filter_recovery(operation):
    cube, _, _ = _dry_cube()
    filtered = cube.filter_bands(["red"])._process(operation, {})
    with pytest.raises(ValueError, match="exactly one"):
        single_band_metadata(filtered, "local_ee_convolve")


def test_multiple_traces_cannot_borrow_a_single_branch_filter():
    first, _, tracer = _dry_cube()
    second, _, _ = _dry_cube(tracer=tracer, source_id="other")
    merged = first.filter_bands(["red"]).merge_cubes(second.filter_bands(["nir"]), None)
    with pytest.raises(ValueError, match="exactly one"):
        single_band_metadata(merged, "local_ee_convolve")


def test_actual_cubes_do_not_use_pending_trace_recovery():
    from openeo_driver.datacube import DriverDataCube
    with pytest.raises(ValueError, match="exactly one"):
        single_band_metadata(DriverDataCube(metadata=_metadata()), "local_ee_convolve")


def test_bounded_trace_walk_and_cycle_reject():
    cube, _, _ = _dry_cube()
    filtered = cube.filter_bands(["red"])
    for _ in range(500):
        filtered = filtered._process("process_type", [])
    with pytest.raises(ValueError, match="500"):
        single_band_metadata(filtered, "local_ee_convolve")
    loop = cube._process("process_type", [])
    loop._traces[0].parent = loop._traces[0]
    with pytest.raises(ValueError, match="cycle"):
        single_band_metadata(loop, "local_ee_convolve")
