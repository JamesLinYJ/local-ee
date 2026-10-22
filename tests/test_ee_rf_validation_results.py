"""Real owned JSON/CSV IO and no-follow boundaries; no model fitting here."""
import json
import uuid

import pytest

from engine.ee_json_result import (
    PendingRuntimeTable, PendingRuntimeValue, RuntimeFeatureTable, RuntimeJsonResult,
)
from gee.services.ee_runtime_results import read_result, result_context


HEADERS = ["system:index", "truth", "x", "classification", ".geo"]


def data():
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "id": "kept-id", "geometry": {"type": "Point", "coordinates": [1, 2]},
        "properties": {"truth": 1, "x": 16777217.0, "classification": 0},
    }]}


def job(tmp_path, kind="runtime_table"):
    identifier = str(uuid.uuid4())
    folder = tmp_path / "jobs" / identifier / "out"
    folder.mkdir(parents=True)
    context = result_context({"kind": kind, "bands": HEADERS if kind == "runtime_table" else []})
    return folder, {"id": identifier, "context": {"protocol": "earthengine", **context}, "assets": {}}


@pytest.mark.parametrize("value", [0.75, [2, -1, 0], [[3, 1], [0, 4]], []])
def test_numeric_json_roundtrip_and_exclusive_write(tmp_path, value):
    folder, row = job(tmp_path, "runtime_value")
    result = RuntimeJsonResult(value)
    row["assets"] = result.write_assets(folder / "out")
    assert set(row["assets"]) == {"openEO.json"}
    assert row["assets"]["openEO.json"]["type"] == "application/json"
    assert read_result(tmp_path, row) == value
    with pytest.raises(FileExistsError):
        result.write_assets(folder / "out")


def test_feature_json_preserves_types_geometry_id_and_independent_copy(tmp_path):
    folder, row = job(tmp_path)
    original = data()
    result = RuntimeFeatureTable(original, HEADERS)
    original["features"][0]["properties"]["x"] = 0
    row["assets"] = result.write_assets(folder / "out")
    assert read_result(tmp_path, row) == data()
    result.format = "CSV"
    assets = result.write_assets(folder / "out")
    assert set(assets) == {"openEO.csv"}
    assert 'kept-id,1,16777217.0,0,' in (folder / "openEO.csv").read_text()
    result.format = "GTiff"
    with pytest.raises(ValueError):
        result.write_assets(folder / "out")


def test_empty_feature_result_has_no_fake_rows_and_keeps_declared_csv_header(tmp_path):
    headers = ["system:index", "prediction", ".geo"]
    empty = {"type": "FeatureCollection", "features": []}
    folder, row = job(tmp_path)
    row["context"]["runtime_columns"] = headers
    result = RuntimeFeatureTable(empty, headers)
    row["assets"] = result.write_assets(folder / "out")
    assert read_result(tmp_path, row) == empty
    result.format = "CSV"
    result.write_assets(folder / "out")
    assert (folder / "openEO.csv").read_bytes() == b"system:index,prediction,.geo\r\n"


def test_json_output_rejects_symlinked_job_and_result_file(tmp_path):
    folder, row = job(tmp_path, "runtime_value")
    outside = tmp_path / "outside.json"
    outside.write_text("123")
    (folder / "openEO.json").symlink_to(outside)
    result = RuntimeJsonResult(1)
    with pytest.raises((ValueError, OSError)):
        result.write_assets(folder / "out")
    row["assets"] = {"openEO.json": {}}
    with pytest.raises((ValueError, OSError)):
        read_result(tmp_path, row)
    (folder / "openEO.json").unlink()
    folder.rmdir()
    folder.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        result.write_assets(folder / "out")
    assert outside.read_text() == "123"


@pytest.mark.parametrize("payload", ['NaN', '{"secret":"not-a-metric"}', 'true', '[[[1]]]', '{"a":1,"a":2}'])
def test_reader_rejects_wrong_numeric_shape_or_json(tmp_path, payload):
    folder, row = job(tmp_path, "runtime_value")
    (folder / "openEO.json").write_text(payload)
    row["assets"] = {"openEO.json": {}}
    with pytest.raises(ValueError):
        read_result(tmp_path, row)


def test_reader_requires_task_context_and_exact_table_columns(tmp_path):
    folder, row = job(tmp_path)
    row["assets"] = RuntimeFeatureTable(data(), HEADERS).write_assets(folder / "out")
    row["context"]["runtime_columns"] = HEADERS[:-2] + ["wrong", ".geo"]
    with pytest.raises(ValueError):
        read_result(tmp_path, row)
    row["context"]["protocol"] = "foreign"
    with pytest.raises(ValueError):
        read_result(tmp_path, row)


@pytest.mark.parametrize("pending", [PendingRuntimeValue(), PendingRuntimeTable(tuple(HEADERS))])
def test_pending_results_cannot_fabricate_output(pending, tmp_path):
    assert not hasattr(pending, "data")
    with pytest.raises(ValueError, match="Pending"):
        pending.write_assets(tmp_path)
    with pytest.raises(ValueError, match="Pending"):
        pending.create_flask_response()


@pytest.mark.parametrize("value", [float("inf"), object(), [float("nan")], True, {"secret": "not-a-metric"}, [[[1]]]])
def test_writer_rejects_nonfinite_or_non_json_values(value):
    with pytest.raises(ValueError):
        RuntimeJsonResult(value)
