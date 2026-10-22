"""Real task/result IO with fixture queue and pixels; not native batch acceptance."""
from __future__ import annotations

import copy

import pytest

from ee_sampling_contract_helpers import _row
from ee_sampling_workflow_helpers import compile_inputs, load_fixture
from engine.ee_sampling_result import SampledFeatureTable
from gee import graph
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


def expression(fixture, **options):
    image = fixture.ee.Image(fixture.source["items"][0]["id"]).select(
        fixture.source["input_properties"])
    return fixture.ee.serializer.encode(image.sample(**options), for_cloud_api=False)


@pytest.mark.parametrize("empty", [False, True])
def test_v2_sample_task_csv_finalization_getinfo_and_parent_permissions(fixture, empty):
    response = fixture.dispatch({"action": "evaluate", "expression": expression(
        fixture, dropNulls=False, geometries=True, numPixels=0 if empty else 20)})
    row = fixture.store.job(response["job_id"], USER)
    assert row["status"] == "queued"
    assert row["context"]["source_job_id"] == fixture.store.parent_id
    graph.validate(row["process"]["process_graph"])
    sampler = next(n for n in row["process"]["process_graph"].values()
                   if n["process_id"] == "local_ee_sample_regions")
    text = sampler["arguments"]["spec"]
    assert row["context"]["sample_spec"] == text
    spec = decode_sampling_spec(text)
    assert spec["version"] == 2 and spec["properties"] == []
    rows = [] if empty else [_row(values=[None, 1.0000000000000002])]
    data = assemble_sample_features(spec, rows)
    table = SampledFeatureTable(data, sampling_columns(spec))
    table.sample_spec, table.sample_spec_verified = text, True
    table.sample_operations, table.sample_operation_work = (), 0
    folder = fixture.root / "jobs" / row["id"] / "out"
    folder.mkdir(parents=True)
    table.write_assets(folder / "out")
    row["status"] = "running"
    fixture.worker.finish(row, FinishedTask())
    assert row["status"] == "finished"
    actual = fixture.dispatch({"action": "result", "job_id": row["id"]})["value"]
    assert actual == data
    assert actual["properties"] == {"band_order": spec["bands"]}
    from openeo_driver.errors import JobNotFoundException

    for account in ({**fixture.account, "job_id": fixture.store.sibling_id},
                    {"user_id": "other", "scope": "session"}):
        with pytest.raises(JobNotFoundException):
            service.dispatch(fixture.backend, account, {"action": "result", "job_id": row["id"]})


def test_v2_graph_rejects_extra_sampler_options_and_wrong_table_source(fixture):
    response = fixture.dispatch({"action": "evaluate", "expression": expression(fixture)})
    process = fixture.store.job(response["job_id"], USER)["process"]["process_graph"]
    sampler = next(key for key, n in process.items() if n["process_id"] == "local_ee_sample_regions")
    extra = copy.deepcopy(process)
    extra[sampler]["arguments"]["options"] = {"drop_nulls": False}
    with pytest.raises(ValueError):
        graph.validate(extra)
    invalid = copy.deepcopy(process)
    invalid[sampler]["arguments"]["data"] = {"from_node": sampler}
    with pytest.raises(ValueError):
        graph.validate(invalid)
