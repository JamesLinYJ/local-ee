"""Owned sample-task IO with real table operations; queue/pixels are fixtures."""
import pytest

from ee_sampling_contract_helpers import _row
from ee_sampling_workflow_helpers import compile_inputs, load_fixture
from engine.ee_sampling_result import SampledFeatureTable
from gee import graph
from gee.sample_table_schema import sampled_columns
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from gee.sampling_values import assemble_sample_features
from gee.services import ee as service
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import FinishedTask, USER, install


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        fixture.source = load_fixture()
        catalog, items, _, _ = compile_inputs(fixture.source)
        for item in items[fixture.source["collection_id"]]:
            item["assets"] = {
                band: {"proj:shape": [3, 4], "proj:epsg": 4326,
                       "proj:transform": [1, 0, 0, 0, -1, 3]}
                for band in fixture.source["catalog_bands"]}
        monkeypatch.setattr(service, "catalog_snapshot", lambda: (catalog, items))
        monkeypatch.setattr(service, "DATA", tmp_path)
        yield fixture
    assert guard.evidence()["attempt_count"] == 0


@pytest.mark.parametrize("overwrite", [False, True])
def test_randomized_sample_context_csv_finalization_and_scoped_getinfo(fixture, overwrite):
    from engine.ee_sample_table_ops import local_ee_sample_table_op

    ee = fixture.ee
    image = ee.Image(fixture.source["items"][0]["id"]).select(fixture.source["input_properties"])
    column = "red" if overwrite else "split"
    sampled = image.sample(dropNulls=False).randomColumn(columnName=column, seed=42)
    selected = sampled.filter(ee.Filter.lt(column, 0.7)).limit(3)
    response = fixture.dispatch({"action": "evaluate", "expression": ee.serializer.encode(
        selected, for_cloud_api=False)})
    row = fixture.store.job(response["job_id"], USER)
    assert row["status"] == "queued"
    processes = row["process"]["process_graph"]
    graph.validate(processes)
    sampler = next(n for n in processes.values() if n["process_id"] == "local_ee_sample_regions")
    spec = decode_sampling_spec(sampler["arguments"]["spec"])
    operations = row["context"]["sample_operations"]
    assert len(operations) == 3
    rows = [_row(row=i, col=0, y=0.5, values=[i + .125, i + .25]) for i in range(12)]
    data = assemble_sample_features(spec, rows)
    table = SampledFeatureTable(data, sampling_columns(spec))
    table.sample_spec, table.sample_spec_verified = sampler["arguments"]["spec"], True
    table.sample_operations, table.sample_operation_work = (), 0
    for operation in operations:
        table = local_ee_sample_table_op({"data": table, "spec": operation}, None)
    actual = table.data
    assert table.columns == sampled_columns(spec, operations)
    assert len(actual["features"]) == 3
    assert all(f["properties"][column] < .7 for f in actual["features"])
    assert actual["properties"] == {"band_order": spec["bands"]}
    if not overwrite:
        assert all(f["properties"]["red"] >= .125 for f in actual["features"])
    folder = fixture.root / "jobs" / row["id"] / "out"
    folder.mkdir(parents=True)
    table.write_assets(folder / "out")
    row["status"] = "running"
    fixture.worker.finish(row, FinishedTask())
    assert row["status"] == "finished"
    restored = fixture.dispatch({"action": "result", "job_id": row["id"]})["value"]
    assert restored == actual
    from openeo_driver.errors import JobNotFoundException

    sibling = {**fixture.account, "job_id": fixture.store.sibling_id}
    with pytest.raises(JobNotFoundException):
        service.dispatch(fixture.backend, sibling, {"action": "result", "job_id": row["id"]})


def test_bad_random_key_never_enqueues(fixture):
    image = fixture.ee.Image(fixture.source["items"][0]["id"])
    value = image.sample().randomColumn(rowKeys=["missing"])
    with pytest.raises(ValueError, match="rowKeys"):
        fixture.dispatch({"action": "evaluate", "expression": fixture.ee.serializer.encode(
            value, for_cloud_api=False)})
    assert fixture.backend.batch_jobs.create_calls == 0
