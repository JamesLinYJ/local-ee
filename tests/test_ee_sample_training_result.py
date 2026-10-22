"""Exact sampled-feature training and SaveResult output behavior."""
from __future__ import annotations

import uuid
import types

import pytest

from engine import ee_process_adapters as adapters
from engine import ee_sample_training
from engine.ee_sampling_result import PendingSampledTable, SampledFeatureTable
from gee.sampling_spec import sampling_columns
from ee_sampling_bridge_helpers import _dry_cube, _spec, _training_spec


def _training_table(spec_text, features):
    from gee.sampling_spec import decode_sampling_spec

    spec = decode_sampling_spec(spec_text)
    data = {"type": "FeatureCollection", "features": features}
    return SampledFeatureTable(data, sampling_columns(spec))


def _training_features():
    rows = [
        (0, 1, 2), (0, 3, 5),
        (1, 1, 5), (1, 2, 6), (1, 3, 7), (1, 3, 8), (1, 4, 9),
    ]
    return [{
        "type": "Feature",
        "id": f"f{index}_r0_c{index}",
        "geometry": None,
        "properties": {
            "plot_id": f"plot-{index}",
            "landcover": label,
            "red": red,
            "nir": nir,
        },
    } for index, (label, red, nir) in enumerate(rows)]


def test_upstream_dry_run_evaluator_saves_pending_sample_without_output(tmp_path):
    from openeo_driver.processgraph.evaluator import convert_node
    from openeo_driver.processgraph.process_implementations.io import save_result
    from openeo_driver.processes import ProcessRegistry
    from openeo_driver.utils import EvalEnv

    from openeo_driver.processgraph.registry import ENV_DRY_RUN_TRACER, ENV_SAVE_RESULT

    sampled_tables = []

    def sample_regions(args, env):
        table = adapters.local_ee_sample_regions(args, env)
        sampled_tables.append(table)
        return table

    registry = ProcessRegistry(argument_names=["args", "env"])
    registry.add_hidden(sample_regions, name="local_ee_sample_regions")
    registry.add_hidden(save_result)
    processing = types.SimpleNamespace(
        get_process_registry=lambda api_version: registry,
    )
    backend = types.SimpleNamespace(
        processing=processing,
        summarize_exception=lambda error: None,
    )
    training, source, tracer = _dry_cube()
    saved_results = []
    env = EvalEnv({
        "backend_implementation": backend,
        "version": "1.2.0",
        "openeo_api_version": "1.2.0",
        "node_caching": False,
        ENV_DRY_RUN_TRACER: tracer,
        ENV_SAVE_RESULT: saved_results,
    })
    graph = {
        "process_id": "save_result",
        "arguments": {
            "data": {
                "process_id": "local_ee_sample_regions",
                "arguments": {"data": training, "spec": _spec()},
            },
            "format": "CSV",
        },
    }

    result = convert_node(graph, env=env)

    assert isinstance(result, PendingSampledTable)
    assert len(saved_results) == 1
    saved = saved_results[0]
    assert type(saved) is PendingSampledTable
    assert result is saved
    assert len(sampled_tables) == 1
    assert saved is not sampled_tables[0]  # the upstream SaveResult.with_format path copied it
    assert saved.format == "CSV"
    assert saved.columns == result.columns
    assert saved.sample_spec == result.sample_spec
    assert saved.traces == (source,)
    assert saved.data_tracer is tracer
    assert not hasattr(saved, "data")
    assert not hasattr(saved, "features")
    assert len(tracer.get_source_constraints()) == 1
    with pytest.raises(ValueError, match="cannot be written"):
        saved.write_assets(tmp_path / "out")
    with pytest.raises(ValueError, match="cannot be serialized"):
        saved.create_flask_response()
    assert list(tmp_path.iterdir()) == []


def test_actual_table_trains_existing_exact_minimum_distance_model():
    spec = _spec(geometries=False)
    table = _training_table(spec, _training_features())
    model = adapters.local_ee_train_minimum_distance(
        {"data": table, "spec": _training_spec()}, env=None
    )
    assert model["version"] == 1
    assert model["metric"] == "euclidean"
    assert model["schema"] == ["red", "nir"]
    assert model["labels"] == [0, 1]
    assert model["centers"] == [
        [["2", "1"], ["7", "2"]],
        [["13", "5"], ["7", "1"]],
    ]


def test_training_rejects_empty_and_non_sample_table_inputs():
    empty_spec = _spec(features=[])
    from gee.sampling_spec import decode_sampling_spec

    decoded = decode_sampling_spec(empty_spec)
    empty = SampledFeatureTable(
        {"type": "FeatureCollection", "features": []},
        sampling_columns(decoded),
    )
    with pytest.raises(ValueError, match="1..1000 inline Features"):
        adapters.local_ee_train_minimum_distance(
            {"data": empty, "spec": _training_spec()}, env=None
        )
    with pytest.raises(ValueError, match="actual SampledFeatureTable"):
        adapters.local_ee_train_minimum_distance(
            {"data": {"type": "FeatureCollection", "features": _training_features()},
             "spec": _training_spec()},
            env=None,
        )


def test_training_rejects_missing_runtime_label_and_over_budget_model():
    spec = _spec(geometries=False)
    features = _training_features()
    features[0]["properties"]["landcover"] = None
    table = _training_table(spec, features)
    with pytest.raises(ValueError, match="class labels"):
        adapters.local_ee_train_minimum_distance(
            {"data": table, "spec": _training_spec()}, env=None
        )

    table = _training_table(spec, _training_features())
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(ee_sample_training, "MAX_CLASSIFIER_WORK", 1)
        with pytest.raises(ValueError, match="50000-step work budget"):
            adapters.local_ee_train_minimum_distance(
                {"data": table, "spec": _training_spec()}, env=None
            )
    finally:
        monkeypatch.undo()


def test_actual_sampled_table_writes_exclusive_physical_csv_and_empty_header(tmp_path):
    from gee.artifacts import artifact_path
    from gee.sampling_spec import decode_sampling_spec

    spec_text = _spec(geometries=False)
    decoded = decode_sampling_spec(spec_text)
    columns = sampling_columns(decoded)
    root = tmp_path
    job_id = str(uuid.uuid4())
    folder = root / "jobs" / job_id / "out"
    folder.mkdir(parents=True)
    table = SampledFeatureTable(
        {"type": "FeatureCollection", "features": _training_features()},
        columns,
    )
    assets = table.write_assets(folder / "out")
    path = artifact_path(root, job_id, "openEO.csv")
    assert list(assets) == ["openEO.csv"]
    assert assets["openEO.csv"]["file:size"] == path.stat().st_size
    assert path.read_text().splitlines()[0] == ",".join(columns)
    with pytest.raises(FileExistsError):
        table.write_assets(folder / "out")

    empty = SampledFeatureTable({"type": "FeatureCollection", "features": []}, columns)
    empty_id = str(uuid.uuid4())
    empty_folder = root / "jobs" / empty_id / "out"
    empty_folder.mkdir(parents=True)
    empty.write_assets(empty_folder / "out")
    assert (empty_folder / "openEO.csv").read_bytes() == (",".join(columns) + "\r\n").encode()


def test_sample_result_is_csv_only_and_requires_canonical_runner_path(tmp_path):
    from gee.sampling_spec import decode_sampling_spec

    decoded = decode_sampling_spec(_spec(geometries=False))
    table = SampledFeatureTable(
        {"type": "FeatureCollection", "features": []},
        sampling_columns(decoded),
    )
    with pytest.raises(ValueError, match="CSV output only"):
        table.with_format("GTiff").write_assets(tmp_path / "out")
    with pytest.raises(ValueError, match="existing batch out path"):
        table.write_assets(tmp_path / "arbitrary.csv")
