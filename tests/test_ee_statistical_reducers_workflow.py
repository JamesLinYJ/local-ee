"""Official client DAGs, independent numerics and real synthetic CSV readback.

The queue/store/native launcher are test doubles; this is not deployed runtime,
browser, sandbox or Google-service acceptance.
"""
import csv
import importlib.util
import json
from fractions import Fraction
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import USER, install, run_batch


ROOT = Path(__file__).resolve().parents[1]
X = [1, 2, 3, 4, 5, 6]
Y = [2, 1, 4, 3, 6, 5]


def workflow_module():
    spec = importlib.util.spec_from_file_location(
        "trends_distributions", ROOT / "examples/44_GEE_python_trends_and_distributions.py")
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


def reference_summary():
    r = Fraction(29, 35)
    # n=6, df=4 has the elementary two-sided t-tail 1 - 3r/2 + r^3/2.
    p = 1 - 3 * r / 2 + r**3 / 2
    return {"r": float(r), "p": float(p), "slope": 1.0, "intercept": 0.0}


def test_independent_trend_covariance_histogram_and_collection_workflow():
    compiled = python_results()
    assert all(item["kind"] == "value" for item in compiled.values())
    values = {key: item["value"] for key, item in compiled.items()}
    assert len(values) == 15
    reference = reference_summary()
    assert values["pearson"] == pytest.approx({k: reference[k] for k in ("r", "p")}, rel=2e-13)
    assert values["summary"] == pytest.approx(reference, rel=2e-13)
    assert values["spearman"] == pytest.approx(float(Fraction(29, 35)), rel=2e-15)
    assert values["kendall"] == pytest.approx(9 / 15, rel=2e-15)
    assert values["kendallOrdinal"] == pytest.approx(9 / 15, rel=2e-15)
    assert values["sen"] == {"slope": 1, "intercept": 0}
    # Exact rational centered cross-products, independent of the online kernel.
    mean_x, mean_y = Fraction(sum(X), 6), Fraction(sum(Y), 6)
    data = [[Fraction(a) - mean_x, Fraction(b) - mean_y] for a, b in zip(X, Y)]
    covariance = [[float(sum(row[i] * row[j] for row in data) / 5)
                   for j in range(2)] for i in range(2)]
    np.testing.assert_allclose(values["covariance"]["array"], covariance, rtol=2e-15)
    np.testing.assert_allclose(values["centeredCovariance"], covariance, rtol=2e-15)
    for eigenvalue, *vector in values["eigen"]:
        np.testing.assert_allclose(np.asarray(covariance) @ vector,
                                   eigenvalue * np.asarray(vector), rtol=2e-15)
    assert [row[0] for row in values["eigen"]] == pytest.approx([6.4, .6], rel=2e-15)
    assert values["histogram"] == [[0, 1], [2, 2], [4, 2], [6, 1]]
    assert values["cumulative"] == [[0, 1], [2, 3], [4, 5], [6, 6]]
    assert values["histogram2D"] == {"counts": [[2, 1], [1, 2]],
                                     "xEdges": [0, 4], "yEdges": [0, 4]}
    assert values["list"] == {"list": [list(pair) for pair in zip(X, Y)]}
    assert values["collected"] == {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None, "properties": {"time": a, "signal": b}}
        for a, b in zip(X, Y)]}
    assert values["rows"]["features"][0]["properties"] == pytest.approx(reference, rel=2e-13)


def test_all_ten_entry_declarations_have_closed_finite_implementations():
    from gee.compat.earthengine.statistical_reducer_leaves import STATISTICAL_REDUCER_NAMES
    from scripts.ee_inventory.declarations import read_declared_handlers

    assert len(STATISTICAL_REDUCER_NAMES) == 10
    assert STATISTICAL_REDUCER_NAMES <= read_declared_handlers(ROOT / "gee/ee_translate.py")


def test_official_python_and_javascript_workflows_are_identical():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for official JavaScript serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const x=[1,2,3,4,5,6], y=[2,1,4,3,6,5];
const pairs=ee.List(x.map((a,i)=>[a,y[i]]));
const observations=ee.FeatureCollection(x.map((a,i)=>
 ee.Feature(null,{x:a,y:y[i],vector:ee.Array([a,y[i]])})));
const centered=ee.List(x.map((a,i)=>ee.Array([a-3.5,y[i]-3.5])));
const covariance=observations.reduceColumns(ee.Reducer.covariance(),['vector']);
const pearson=ee.Reducer.pearsonsCorrelation().setOutputs(['r','p']);
const sen=ee.Reducer.sensSlope().setOutputs(['slope','intercept']);
const summary=observations.reduceColumns(pearson.combine({reducer2:sen,sharedInputs:true}),['x','y']);
const collected=observations.reduceColumns(ee.Reducer.toCollection(['time','signal'])
 .setOutputs(['features']),['x','y']);
const values={pearson:pairs.reduce(pearson),spearman:pairs.reduce(ee.Reducer.spearmansCorrelation()),
 kendall:pairs.reduce(ee.Reducer.kendallsCorrelation(2)),
 kendallOrdinal:ee.List(y).reduce(ee.Reducer.kendallsCorrelation()),sen:pairs.reduce(sen),
 covariance,centeredCovariance:centered.reduce(ee.Reducer.centeredCovariance()),
 eigen:ee.Array(covariance.get('array')).eigen(),
 histogram:ee.List(y).reduce(ee.Reducer.fixedHistogram(0,8,4)),
 cumulative:ee.List(y).reduce(ee.Reducer.fixedHistogram(0,8,4,true)),
 histogram2D:pairs.reduce(ee.Reducer.fixed2DHistogram(0,8,2,0,8,2).setOutputs(['counts','xEdges','yEdges'])),
 list:observations.reduceColumns(ee.Reducer.toList(2),['x','y']),
 collected:ee.FeatureCollection(collected.get('features')),summary,
 rows:ee.FeatureCollection([ee.Feature(null,summary)])};
const outputs=Object.fromEntries(Object.entries(values).map(([k,v])=>[k,ee.Serializer.encode(v)]));
if(attempts) throw Error('Unexpected networking');
console.log(JSON.stringify({outputs,attempts}));
"""
    result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    expected = python_results()
    assert set(decoded["outputs"]) == set(expected)
    for key, value in decoded["outputs"].items():
        assert compile_expression(value, [], {}) == expected[key], key


@pytest.mark.parametrize("key,selectors,expected", [
    ("rows", ["r", "p", "slope", "intercept"], [reference_summary()]),
    ("collected", ["time", "signal"], [{"time": a, "signal": b} for a, b in zip(X, Y)]),
])
def test_statistical_and_collected_tables_export_actual_csv(tmp_path, monkeypatch, key, selectors, expected):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        task = fixture.ee.batch.Export.table.toDrive(
            collection=workflow_module().build_workflow(fixture.ee)[key],
            description="finite trends and distributions", fileFormat="CSV", selectors=selectors)
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
        assert len(rows) == len(expected)
        for actual, wanted in zip(rows, expected):
            assert {name: float(value) for name, value in actual.items()} == pytest.approx(wanted, rel=2e-13)
    assert guard.evidence()["attempt_count"] == 0
