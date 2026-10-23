"""Bridge and upstream dry-run schema checks for integer image values."""
import pytest

from ee_sampling_bridge_helpers import _dry_cube, _metadata
from engine import ee_process_adapters as adapters
from engine.ee_integer_values import local_ee_integer_values
from gee.integer_values_spec import constant_operand, prepare_integer_values_spec


def _unary_spec():
    return prepare_integer_values_spec("bit_not", [{"band": 0}])


def _binary_spec():
    return prepare_integer_values_spec("bit_and", [{"band": 0}, {"band": 1}])


def _constant_spec():
    return prepare_integer_values_spec("bit_or", [{"band": 0}, constant_operand(1)])


def _collection(collection_id):
    return {"id": collection_id, "cube:dimensions": {
        "x": {"type": "spatial", "axis": "x", "extent": [0, 4], "reference_system": 4326},
        "y": {"type": "spatial", "axis": "y", "extent": [0, 3], "reference_system": 4326},
        "t": {"type": "temporal", "extent": ["2025-01-01", "2025-01-02"]},
        "bands": {"type": "bands", "values": ["red", "nir"]},
    }}


def _evaluator_env(monkeypatch, collections):
    # Importing ProcessGraphDeserializer registers the pinned standard handlers.
    from openeo_driver import ProcessGraphDeserializer  # noqa: F401
    from openeo_driver.backend import CollectionCatalog, OpenEoBackendImplementation
    from openeo_driver.dry_run import DryRunDataTracer
    from openeo_driver.processgraph import registry
    from openeo_driver.processgraph.evaluator import evaluate
    from openeo_driver.utils import EvalEnv

    for processes in (registry.process_registry_100, registry.process_registry_2xx):
        monkeypatch.setattr(processes, "_processes", dict(processes._processes))
    adapters.register_local_ee_processes()
    monkeypatch.setattr(
        adapters, "_apply_native",
        lambda *args, **kwargs: pytest.fail("dry-run must not fabricate or execute pixels"),
    )
    tracer = DryRunDataTracer()
    backend = OpenEoBackendImplementation(
        catalog=CollectionCatalog(collections), processing=registry.ConcreteProcessing(),
    )
    env = EvalEnv({
        "backend_implementation": backend,
        "openeo_api_version": "1.2.0",
        registry.ENV_DRY_RUN_TRACER: tracer,
        "node_caching": False,
    })
    return evaluate, env, tracer


def test_dry_run_returns_only_output_schema_and_preserves_selected_source_trace():
    from openeo_driver.dry_run import DryRunDataCube

    cube, source, tracer = _dry_cube(bands=("red", "nir"), temporal=True)
    selected = cube.filter_bands(["nir"])
    assert selected.metadata.band_names == ["red", "nir"]  # Pinned driver leaves it stale.

    result = local_ee_integer_values({"data": selected, "spec": _unary_spec()}, None)

    assert isinstance(result, DryRunDataCube)
    assert result.metadata.band_names == ["v"]
    assert result.metadata.has_temporal_dimension()
    assert result._data_tracer is tracer and result._traces[0].get_source() is source
    assert cube.metadata.band_names == selected.metadata.band_names == ["red", "nir"]
    assert tracer.get_source_constraints()[0][1]["bands"] == ["nir"]


def test_dry_run_merge_preserves_all_sources_without_guessing_operand_order():
    first, source_a, tracer = _dry_cube(bands=("red", "nir"), source_id="source-a")
    second, source_b, _ = _dry_cube(
        tracer=tracer, bands=("red", "nir"), source_id="source-b",
    )
    merged = first.filter_bands(["red"]).merge_cubes(
        second.filter_bands(["nir"]), None,
    )

    result = local_ee_integer_values({"data": merged, "spec": _binary_spec()}, None)

    assert result.metadata.band_names == ["v"]
    assert result._data_tracer is tracer
    assert len(result._traces) == len(merged._traces) == 2
    assert {trace.get_source() for trace in result._traces} == {source_a, source_b}
    assert {entry[1]["bands"][0] for entry in tracer.get_source_constraints()} == {
        "red", "nir",
    }


def test_dry_run_does_not_validate_stale_band_count_or_names():
    cube, _, _ = _dry_cube(bands=("red", "nir"))
    two_selected = cube.filter_bands(["nir", "red"])
    unknown_selected = cube.filter_bands(["upstream-rename-is-not-visible"])

    assert local_ee_integer_values(
        {"data": two_selected, "spec": _unary_spec()}, None,
    ).metadata.band_names == ["v"]
    assert local_ee_integer_values(
        {"data": unknown_selected, "spec": _unary_spec()}, None,
    ).metadata.band_names == ["v"]


def test_dry_run_still_requires_a_canonical_spec_and_band_dimension():
    from openeo.metadata import CollectionMetadata, SpatialDimension
    from openeo_driver.dry_run import DryRunDataCube

    cube, _, tracer = _dry_cube(bands=("red",))
    with pytest.raises(ValueError):
        local_ee_integer_values({"data": cube, "spec": "{}"}, None)

    no_bands = DryRunDataCube(
        traces=list(cube._traces), data_tracer=tracer,
        metadata=CollectionMetadata(metadata={}, dimensions=[
            SpatialDimension("x", (0, 4)), SpatialDimension("y", (0, 3)),
        ]),
    )
    with pytest.raises(ValueError, match="requires a band dimension"):
        local_ee_integer_values({"data": no_bands, "spec": _unary_spec()}, None)


def test_actual_cube_requires_exact_compiler_order_and_forwards_spec_without_mutation(monkeypatch):
    from openeo_driver.datacube import DriverDataCube

    cube = DriverDataCube(metadata=_metadata(("band0", "band1"), temporal=True))
    original_names = list(cube.metadata.band_names)
    calls = []

    def apply_native(actual, process_id, arguments, metadata):
        calls.append((actual, process_id, arguments, metadata))
        return "native-return"

    monkeypatch.setattr(adapters, "_apply_native", apply_native)
    assert local_ee_integer_values({"data": cube, "spec": _binary_spec()}, None) == "native-return"

    actual, process_id, arguments, metadata = calls[0]
    assert actual is cube
    assert process_id == "local_ee_integer_values"
    assert arguments == {"spec": _binary_spec()}
    assert metadata.band_names == ["v"]
    assert metadata.has_temporal_dimension()
    assert metadata.spatial_dimensions == cube.metadata.spatial_dimensions
    assert cube.metadata.band_names == original_names


@pytest.mark.parametrize("bands", [("band1", "band0"), ("band0",), ("band1",)])
def test_actual_cube_rejects_wrong_input_band_order_or_count(bands):
    from openeo_driver.datacube import DriverDataCube

    cube = DriverDataCube(metadata=_metadata(bands))
    with pytest.raises(ValueError, match="ordered input bands: band0, band1"):
        local_ee_integer_values({"data": cube, "spec": _binary_spec()}, None)


def test_dry_run_trace_walk_is_bounded_and_cycle_checked():
    cube, _, _ = _dry_cube(bands=("red",))
    allowed = cube.filter_bands(["red"])
    for _ in range(498):
        allowed = allowed._process("process_type", [])
    assert local_ee_integer_values({"data": allowed, "spec": _unary_spec()}, None)

    too_deep = cube.filter_bands(["red"])
    for _ in range(499):
        too_deep = too_deep._process("process_type", [])
    with pytest.raises(ValueError, match="trace exceeds 500 nodes"):
        local_ee_integer_values({"data": too_deep, "spec": _unary_spec()}, None)

    cyclic = cube._process("process_type", [])
    cyclic._traces[0].parent = cyclic._traces[0]
    with pytest.raises(ValueError, match="trace contains a cycle"):
        local_ee_integer_values({"data": cyclic, "spec": _unary_spec()}, None)

    dangling = cube.filter_bands(["red"])
    dangling._traces[0].parent = None
    with pytest.raises(ValueError, match="does not reach a data source"):
        local_ee_integer_values({"data": dangling, "spec": _unary_spec()}, None)


def test_dry_run_trace_walk_memoizes_shared_ancestry_and_counts_sources(monkeypatch):
    from openeo_driver.dry_run import DataSource, DataTrace, DryRunDataCube, DryRunDataTracer

    tracer = DryRunDataTracer()
    source = tracer.add_trace(DataSource("load_collection", {"id": "shared"}))
    shared = DataTrace(source, "shared_filter", {})
    for _ in range(249):
        shared = DataTrace(shared, "preserving", {})
    roots = [DataTrace(shared, "branch", {}) for _ in range(249)]
    cube = DryRunDataCube(traces=roots, data_tracer=tracer, metadata=_metadata(("red",)))
    overflow = DryRunDataCube(
        traces=roots + [DataTrace(shared, "branch", {})],
        data_tracer=tracer, metadata=_metadata(("red",)),
    )

    parent_slot = DataTrace.parent
    parent_reads = [0]

    def get_parent(trace):
        parent_reads[0] += 1
        return parent_slot.__get__(trace, DataTrace)

    def set_parent(trace, value):
        parent_slot.__set__(trace, value)

    monkeypatch.setattr(DataTrace, "parent", property(get_parent, set_parent))
    result = local_ee_integer_values({"data": cube, "spec": _binary_spec()}, None)
    assert result.metadata.band_names == ["v"]
    assert parent_reads[0] < 600  # Shared ancestry is visited once per call.

    with pytest.raises(ValueError, match="trace exceeds 500 nodes"):
        local_ee_integer_values({"data": overflow, "spec": _binary_spec()}, None)


def test_real_process_registry_evaluates_two_branch_merge_and_preserves_sources(monkeypatch):
    from openeo_driver.dry_run import DryRunDataCube

    evaluate, env, tracer = _evaluator_env(
        monkeypatch, [_collection("synthetic-a"), _collection("synthetic-b")],
    )
    graph = {
        "source_a": {"process_id": "load_collection", "arguments": {"id": "synthetic-a"}},
        "left": {"process_id": "filter_bands", "arguments": {
            "data": {"from_node": "source_a"}, "bands": ["red"],
        }},
        "left_name": {"process_id": "rename_labels", "arguments": {
            "data": {"from_node": "left"}, "dimension": "bands", "target": ["band0"],
        }},
        "source_b": {"process_id": "load_collection", "arguments": {"id": "synthetic-b"}},
        "right": {"process_id": "filter_bands", "arguments": {
            "data": {"from_node": "source_b"}, "bands": ["nir"],
        }},
        "right_name": {"process_id": "rename_labels", "arguments": {
            "data": {"from_node": "right"}, "dimension": "bands", "target": ["band1"],
        }},
        "merged": {"process_id": "merge_cubes", "arguments": {
            "cube1": {"from_node": "left_name"}, "cube2": {"from_node": "right_name"},
        }},
        "values": {"process_id": "local_ee_integer_values", "result": True,
                   "arguments": {"data": {"from_node": "merged"}, "spec": _binary_spec()}},
    }

    result = evaluate(graph, env=env, do_dry_run=False)

    assert isinstance(result, DryRunDataCube)
    assert result.metadata.band_names == ["v"]
    assert len(result._traces) == 2
    constraints = tracer.get_source_constraints()
    assert {entry[0].arguments[0] for entry in constraints} == {
        "synthetic-a", "synthetic-b",
    }
    assert {entry[1]["bands"][0] for entry in constraints} == {"red", "nir"}


def test_real_process_registry_evaluates_nested_scalar_chain_as_pending_schema(monkeypatch):
    from openeo_driver.dry_run import DryRunDataCube

    evaluate, env, tracer = _evaluator_env(monkeypatch, [_collection("synthetic")])
    graph = {
        "source": {"process_id": "load_collection", "arguments": {"id": "synthetic"}},
        "select": {"process_id": "filter_bands", "arguments": {
            "data": {"from_node": "source"}, "bands": ["red"],
        }},
        "input_name": {"process_id": "rename_labels", "arguments": {
            "data": {"from_node": "select"}, "dimension": "bands", "target": ["band0"],
        }},
        "first": {"process_id": "local_ee_integer_values", "arguments": {
            "data": {"from_node": "input_name"}, "spec": _unary_spec(),
        }},
        "second_input_name": {"process_id": "rename_labels", "arguments": {
            "data": {"from_node": "first"}, "dimension": "bands", "target": ["band0"],
        }},
        "second": {"process_id": "local_ee_integer_values", "result": True,
                    "arguments": {"data": {"from_node": "second_input_name"},
                                  "spec": _constant_spec()}},
    }

    result = evaluate(graph, env=env, do_dry_run=False)

    assert isinstance(result, DryRunDataCube)
    assert result.metadata.band_names == ["v"]
    assert len(result._traces) == 1
    constraints = tracer.get_source_constraints()
    assert len(constraints) == 1
    assert constraints[0][0].arguments[0] == "synthetic"
    assert constraints[0][1]["bands"] == ["red"]
