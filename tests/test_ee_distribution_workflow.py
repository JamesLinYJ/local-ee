"""Independent static values, official clients and physical synthetic CSV.

The existing queue/store/launcher are doubles. This is not browser, deployed
sandbox or raster-engine acceptance.
"""
import csv
import importlib.util
import json
import math
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import USER, install, run_batch


ROOT = Path(__file__).resolve().parents[1]


def workflow_module():
    spec = importlib.util.spec_from_file_location(
        "distribution_summary", ROOT / "examples/46_GEE_python_distribution_summary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def python_results():
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        results = {key: compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})
                   for key, value in workflow_module().build_workflow(ee).items()}
    assert guard.evidence()["attempt_count"] == 0
    return results


def reference_moments(values):
    mean = Fraction(sum(values), len(values))
    centered = [Fraction(x) - mean for x in values]
    m2, m3, m4 = [sum(x**power for x in centered) / len(values) for power in (2, 3, 4)]
    return {"skew": float(m3) / float(m2)**1.5,
            "kurtosis": float(m4 / m2**2 - 3)}


def expected_rows():
    return [
        {"group": 0, "lo": 0, "median": 1, "hi": 1, "mode": 1,
         "mean": 2 / 3, **reference_moments([0, 1, 1])},
        {"group": 1, "lo": 2, "median": 4, "hi": 8, "mode": 2,
         "mean": 14 / 3, **reference_moments([2, 4, 8])},
    ]


def test_distribution_workflow_matches_independent_numeric_reference():
    compiled = python_results()
    assert len(compiled) == 12
    assert all(item["kind"] == "value" for item in compiled.values())
    values = {key: item["value"] for key, item in compiled.items()}
    assert values["quantiles"] == {"lo": 0, "q1": 1, "median": 1.5, "q3": 3.5, "hi": 8}
    assert values["intervalMean"] == pytest.approx(8 / 3)
    assert values["mode"] == 1
    moments = reference_moments([0, 1, 1, 2, 4, 8])
    for key in moments:
        assert values[key] == pytest.approx(moments[key], abs=1e-14)
    resultant = (1 + math.sqrt(2)) / 3
    assert values["circularMean"] == pytest.approx(0, abs=1e-15)
    assert values["circularStddev"] == pytest.approx(math.sqrt(-2 * math.log(resultant)), rel=2e-14)
    assert values["circularVariance"] == pytest.approx(1 - resultant, rel=2e-14)
    assert values["summary"] == pytest.approx({
        "lo": 0, "median": 1.5, "hi": 8, "mode": 1, "mean": 8 / 3, **moments}, abs=1e-14)
    for actual, expected in zip(values["groups"]["groups"], expected_rows(), strict=True):
        assert actual == pytest.approx(expected, abs=1e-14)
    for feature, expected in zip(values["rows"]["features"], expected_rows(), strict=True):
        assert feature["properties"] == pytest.approx(expected, abs=1e-14)
        assert feature["geometry"] is None
    assert values["repeated"] == [3, 30]


def test_official_python_and_javascript_distribution_workflows_match():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for official JavaScript serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const values=ee.List([0,1,1,2,4,8]);
const angles=ee.List([-Math.PI/4,0,Math.PI/4]);
const quantiles=ee.Reducer.percentile([0,25,50,75,100],['lo','q1','median','q3','hi'],null,null,1000);
let summary=ee.Reducer.percentile([0,50,100],['lo','median','hi'],null,null,1000);
for (const reducer of [ee.Reducer.mode(null,null,1000),ee.Reducer.skew(),
 ee.Reducer.kurtosis(),ee.Reducer.intervalMean(0,100,null,null,1000).setOutputs(['mean'])]) {
 summary=summary.combine({reducer2:reducer,sharedInputs:true});
}
const observations=ee.FeatureCollection([0,1,1,2,4,8].map((v,i)=>
 ee.Feature(null,{value:v,group:Math.floor(i/3)})));
const groups=observations.reduceColumns(summary.group(1,'group'),['value','group']);
const rows=ee.FeatureCollection(ee.List(groups.get('groups')).map(row=>ee.Feature(null,ee.Dictionary(row))));
const outputs={quantiles:values.reduce(quantiles),
 intervalMean:values.reduce(ee.Reducer.intervalMean(0,100,null,null,1000)),
 mode:values.reduce(ee.Reducer.mode(null,null,1000)),skew:values.reduce(ee.Reducer.skew()),
 kurtosis:values.reduce(ee.Reducer.kurtosis()),circularMean:angles.reduce(ee.Reducer.circularMean()),
 circularStddev:angles.reduce(ee.Reducer.circularStddev()),
 circularVariance:angles.reduce(ee.Reducer.circularVariance()),
 summary:observations.reduceColumns(summary,['value']),groups,rows,
 repeated:ee.List([[1,10],[3,30],[5,50]]).reduce(ee.Reducer.percentile([50],['middle']).repeat(2))};
if(attempts) throw Error('Unexpected networking');
console.log(JSON.stringify({outputs:Object.fromEntries(Object.entries(outputs)
 .map(([k,v])=>[k,ee.Serializer.encode(v)])),attempts}));
"""
    result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    expected = python_results()
    assert set(decoded["outputs"]) == set(expected)
    for key, expression in decoded["outputs"].items():
        assert compile_expression(expression, [], {}) == expected[key], key


def test_grouped_distribution_rows_export_actual_csv(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        task = fixture.ee.batch.Export.table.toDrive(
            collection=workflow_module().build_workflow(fixture.ee)["rows"],
            description="finite distribution summary", fileFormat="CSV",
            selectors=list(expected_rows()[0]))
        task.start()
        result = run_batch(fixture, task.id)
        assert result.row["status"] == "finished"
        from gee.backend import Jobs

        assets = Jobs().get_result_assets(task.id, USER)
        assert len(assets) == 1
        path = Path(next(iter(assets.values()))["href"])
        assert path.parent == fixture.root / "jobs" / task.id / "out"
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        for actual, expected in zip(rows, expected_rows(), strict=True):
            assert {key: float(value) for key, value in actual.items()} == pytest.approx(
                expected, abs=1e-14)
    assert guard.evidence()["attempt_count"] == 0
