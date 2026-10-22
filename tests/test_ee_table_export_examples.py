"""Actual example and JS wrapper controls using the trusted synthetic queue.

Only the database and transport/process launch are replaced. Python executes
the shipped example; Node executes the shipped JS runner with a captured local
transport. Payloads reach the real service and produce real CSV artifacts.
These controls do not establish native isolation or browser acceptance.
"""
import csv
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile

import pytest

from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import install, run_batch


ROOT = Path(__file__).resolve().parents[1]


def read_csv(fixture, row):
    from gee.backend import Jobs
    assets = Jobs().get_result_assets(row["id"], row["user_id"])
    assert len(assets) == 1
    asset = next(iter(assets.values()))
    with Path(asset["href"]).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_shipped_classification_example_exports_all_three_metrics(tmp_path, monkeypatch, capsys):
    reference = json.loads((ROOT / "tests/fixtures/ee-distance-metric-validation-v1.json").read_text())
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        runpy.run_path(str(ROOT / "examples/27_GEE_python_classification_csv.py"))
        assert len(fixture.store.rows) == 3
        for row, metric in zip(fixture.store.rows.values(), reference["distance_metrics"]):
            assert row["status"] == "queued"
            run_batch(fixture, row["id"])
            assert row["status"] == "finished"
            rows = read_csv(fixture, row)
            assert [int(r["predicted"]) for r in rows] == reference["independent_reference"][metric]["predictions"]
            assert [r["sample_id"] for r in rows] == [r["sample_id"] for r in reference["validation"]]
            for index, value in enumerate(rows):
                geometry = json.loads(value[".geo"])
                assert geometry == {"type": "Point", "coordinates": [100 + index * 0.01, 30]}
            assert list(row["assets"]) == [f"classification_{metric}.csv"]
    assert guard.evidence()["attempt_count"] == 0
    output = capsys.readouterr().out
    assert all(f"{metric} 验证准确率" in output for metric in reference["distance_metrics"])


CAPTURE_TRANSPORT = r"""
const fs = require('node:fs');
const path = require('node:path');
let attempts = 0;
function deny() { attempts++; throw Error('Trusted JS export attempted networking'); }
for (const name of ['node:http', 'node:https']) {
  const module = require(name); module.request = deny; module.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny;
const payloads = [];
require('node:child_process').spawnSync = (program, args, options) => {
  if (program !== process.execPath || path.basename(args[0]) !== 'transport.cjs') {
    throw Error('Unexpected child process');
  }
  const payload = JSON.parse(options.input);
  payloads.push(payload);
  const value = payload.action === 'export_table'
    ? {job_id: '00000000-0000-0000-0000-000000000002'}
    : {value: {state: 'READY'}};
  return {status: 0, stdout: JSON.stringify({ok: true, value}), stderr: ''};
};
process.on('exit', () => fs.writeFileSync(process.env.TABLE_CAPTURE,
  JSON.stringify({payloads, network_attempts: attempts})));
"""


JS_CLASSIFICATION = r"""
const training = ee.FeatureCollection([[0,3,0],[1,2,2]].map(row =>
  ee.Feature(null, {label:row[0], nir:row[1], red:row[2]})));
const classifier = ee.Classifier.minimumDistance('cosine').train(training, 'label', ['nir','red']);
const predicted = ee.FeatureCollection([[0.25,0.25],[8,3.6],[-2,-2]].map((row,index) =>
  ee.Feature(ee.Geometry.Point([100+index,30]),
    {'system:index':'sample-'+index, nir:row[0],red:row[1],note:'雪,"甲"\n第二行'})))
  .classify(classifier,'prediction');
const options = {collection:predicted, description:'js_classification',
  fileNamePrefix:'js_result', fileFormat:'CSV', selectors:'prediction,note,.geo'};
const job = EXPORT_CALL;
job.start();
if (job.status().state !== 'READY') throw Error('Unexpected task state');
"""


@pytest.mark.parametrize("call", [
    "Export.table.toDrive(options)",
    "Export.table.toDrive(predicted, options.description, undefined, options.fileNamePrefix, 'CSV', options.selectors)",
])
def test_existing_js_runner_exports_classified_features(call, tmp_path, monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for official JS runner control")
    with tempfile.TemporaryDirectory(dir=tmp_path) as temporary:
        runtime = Path(temporary)
        (runtime / "vendor").mkdir()
        for name in ("earthengine.cjs", "algorithms.json"):
            shutil.copyfile(ROOT / "vendor/earthengine-js" / name, runtime / "vendor" / name)
        shutil.copyfile(ROOT / "runtimes/eejs/runner.cjs", runtime / "runner.cjs")
        (runtime / "capture.cjs").write_text(CAPTURE_TRANSPORT)
        (runtime / "script.js").write_text(JS_CLASSIFICATION.replace("EXPORT_CALL", call))
        capture = runtime / "requests.json"
        result = subprocess.run([node, "--require", str(runtime / "capture.cjs"),
                                 str(runtime / "runner.cjs"), str(runtime / "script.js")],
                                cwd=ROOT, env={"TABLE_CAPTURE": str(capture)},
                                capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        evidence = json.loads(capture.read_text())
        assert evidence["network_attempts"] == 0
        assert [p["action"] for p in evidence["payloads"]] == ["export_table", "start", "status"]

        with OfflineGuard() as guard:
            fixture = install(monkeypatch, tmp_path)
            fixture.store.parents[fixture.store.parent_id]["language"] = "javascript"
            for payload in evidence["payloads"]:
                if payload["action"] == "export_table":
                    response = fixture.dispatch(payload)
                    job_id = response["job_id"]
                else:
                    payload["job_id"] = job_id
                    response = fixture.dispatch(payload)
            assert response["value"]["state"] == "READY"
            result = run_batch(fixture, job_id)
            assert result.row["language"] == "javascript"
            rows = read_csv(fixture, result.row)
            assert [int(r["prediction"]) for r in rows] == [1, 1, 0]
            assert all(r["note"] == '雪,"甲"\n第二行' for r in rows)
            assert [json.loads(r[".geo"])["coordinates"] for r in rows] == [[100,30],[101,30],[102,30]]
        assert guard.evidence()["attempt_count"] == 0


def test_empty_collection_exports_a_header_and_completes(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        task = fixture.ee.batch.Export.table.toDrive(
            fixture.ee.FeatureCollection([]), description="empty_table")
        task.start()
        result = run_batch(fixture, task.id)
        assert result.row["status"] == "finished"
        assert read_csv(fixture, result.row) == []
        from gee.backend import Jobs
        assets = Jobs().get_result_assets(task.id, result.row["user_id"])
        with Path(next(iter(assets.values()))["href"]).open(newline="") as stream:
            assert list(csv.reader(stream)) == [["system:index", ".geo"]]
    assert guard.evidence()["attempt_count"] == 0


@pytest.mark.parametrize("invalid_format", [[], {}, False])
def test_invalid_format_types_fail_before_a_task_is_created(invalid_format, tmp_path, monkeypatch):
    from gee.ee_translate import UnsupportedEEError
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        expression = fixture.ee.serializer.encode(fixture.ee.FeatureCollection([]), for_cloud_api=False)
        with pytest.raises(UnsupportedEEError, match="Unsupported local export format"):
            fixture.dispatch({"action": "export_table", "expression": expression,
                              "options": {"fileFormat": invalid_format}})
        assert fixture.backend.batch_jobs.create_calls == 0
    assert guard.evidence()["attempt_count"] == 0
