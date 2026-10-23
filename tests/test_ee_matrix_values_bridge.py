"""Actual cube schema, bounded dry-run traces and pinned evaluator integration."""
import pytest

from ee_sampling_bridge_helpers import _dry_cube, _metadata
from engine import ee_process_adapters as adapters
from engine.ee_cube_admission import validate_cube_trace
from engine.ee_matrix_values import local_ee_matrix_values
from gee.matrix_values_spec import prepare_matrix_values_spec


def _spec(op="inverse", rows=2, cols=2, rhs=0):
    count = rows * cols + (rows * rhs if op == "solve" else 0)
    return prepare_matrix_values_spec(op, rows, cols, rhs, [{"band": i} for i in range(count)])


@pytest.mark.parametrize("op,rows,cols,rhs,count", [
    ("inverse", 2, 2, 0, 4), ("pinverse", 2, 3, 0, 6), ("solve", 3, 2, 2, 4),
    ("cholesky", 8, 8, 0, 64), ("lu", 4, 4, 0, 48),
    ("qr", 7, 5, 0, 60), ("qr", 1, 8, 0, 9), ("svd", 8, 3, 0, 42), ("svd", 3, 8, 0, 42),
])
def test_actual_bridge_forwards_exact_native_spec_and_owned_row_major_schema(
        monkeypatch, op, rows, cols, rhs, count):
    from openeo_driver.datacube import DriverDataCube

    input_count = rows * cols + rows * rhs
    cube = DriverDataCube(metadata=_metadata(tuple(f"band{i}" for i in range(input_count)), temporal=True))
    original = list(cube.metadata.band_names)
    calls = []
    monkeypatch.setattr(adapters, "_apply_native", lambda *args: calls.append(args) or "actual-result")
    encoded = _spec(op, rows, cols, rhs)
    assert local_ee_matrix_values({"data": cube, "spec": encoded}, None) == "actual-result"
    actual, process, args, metadata = calls[0]
    assert actual is cube and process == "local_ee_matrix_values"
    assert args == {"spec": encoded}
    assert metadata.band_names == [f"matrix{i}" for i in range(count)]
    assert metadata.has_temporal_dimension()
    assert metadata.spatial_dimensions == cube.metadata.spatial_dimensions
    assert cube.metadata.band_names == original


@pytest.mark.parametrize("bands", [
    ("band0", "band1", "band2"), ("band1", "band0", "band2", "band3"),
    ("band0", "band1", "band2", "band3", "extra"),
])
def test_actual_cube_rejects_incorrect_band_count_and_order(bands):
    from openeo_driver.datacube import DriverDataCube

    cube = DriverDataCube(metadata=_metadata(bands))
    with pytest.raises(ValueError, match="ordered input bands"):
        local_ee_matrix_values({"data": cube, "spec": _spec()}, None)


def test_dry_run_retains_stale_input_labels_and_real_source_constraints(monkeypatch):
    monkeypatch.setattr(adapters, "_apply_native", lambda *a: pytest.fail("dry-run executed pixels"))
    first, source_a, tracer = _dry_cube(temporal=True, source_id="a")
    second, source_b, _ = _dry_cube(tracer=tracer, temporal=True, source_id="b")
    merged = first.filter_bands(["red"]).merge_cubes(second.filter_bands(["nir"]), None)
    result = local_ee_matrix_values({"data": merged, "spec": _spec()}, None)
    assert result.metadata.band_names == [f"matrix{i}" for i in range(4)]
    assert result.metadata.has_temporal_dimension()
    assert result._data_tracer is tracer
    assert {trace.get_source() for trace in result._traces} == {source_a, source_b}
    assert {item[1]["bands"][0] for item in tracer.get_source_constraints()} == {"red", "nir"}
    assert first.metadata.band_names == second.metadata.band_names == ["red", "nir"]


def test_matrix_dry_run_enforces_500_trace_nodes_and_rejects_cycles():
    cube, _, _ = _dry_cube()
    allowed = cube
    for _ in range(499):
        allowed = allowed._process("preserve", [])
    assert local_ee_matrix_values({"data": allowed, "spec": _spec()}, None)
    overflow = allowed._process("preserve", [])
    with pytest.raises(ValueError, match="trace exceeds 500 nodes"):
        local_ee_matrix_values({"data": overflow, "spec": _spec()}, None)
    cycle = cube._process("preserve", [])
    cycle._traces[0].parent = cycle._traces[0]
    with pytest.raises(ValueError, match="cycle"):
        local_ee_matrix_values({"data": cycle, "spec": _spec()}, None)
    for args in ({"max_nodes": 501}, {"max_roots": True}):
        with pytest.raises(ValueError):
            validate_cube_trace(cube, "local_ee_matrix_values", **args)


def test_pinned_evaluator_preserves_matrix_schema_through_a_second_operation(monkeypatch):
    from test_ee_integer_values_bridge import _collection, _evaluator_env

    evaluate, env, tracer = _evaluator_env(monkeypatch, [_collection("synthetic")])
    graph = {"source": {"process_id": "load_collection", "arguments": {"id": "synthetic"}},
             "matrix": {"process_id": "local_ee_matrix_values", "arguments": {
                 "data": {"from_node": "source"}, "spec": _spec()}},
             "again": {"process_id": "local_ee_matrix_values", "result": True, "arguments": {
                 "data": {"from_node": "matrix"}, "spec": _spec()}}}
    result = evaluate(graph, env=env, do_dry_run=False)
    assert result.metadata.band_names == ["matrix0", "matrix1", "matrix2", "matrix3"]
    assert len(result._traces) == 1
    assert tracer.get_source_constraints()[0][0].arguments[0] == "synthetic"


@pytest.mark.parametrize("args", [{"data": None}, {"data": {}}, {"data": "x"}])
def test_bridge_rejects_non_cube_inputs(args):
    from openeo_driver.errors import ProcessParameterInvalidException

    with pytest.raises(ProcessParameterInvalidException, match="Expected raster cube"):
        local_ee_matrix_values({**args, "spec": _spec()}, None)
