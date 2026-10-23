"""Official SDK computations and physical synthetic CSV result readback.

The task store and native launcher are test doubles; these checks do not stand
in for deployed services, a browser, native isolation or Google comparisons.
"""
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import statistics
import subprocess

import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import USER, install, run_batch


ROOT = Path(__file__).resolve().parents[1]
ROWS = [
    {"zone": "north", "min": 1, "max": 3, "variance": 1, "count": 2},
    {"zone": "south", "min": 5, "max": 5, "variance": 0, "count": 1},
]


def workflow_module():
    spec = importlib.util.spec_from_file_location(
        "reducer_statistics", ROOT / "examples/43_GEE_python_reducer_statistics.py")
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


def test_independent_scalar_statistics_and_composed_table_results():
    values = [1, 3, 5]
    expected = {
        "minMax": {"min": min(values), "max": max(values)},
        "product": 15, "stdDev": statistics.pstdev(values),
        "variance": statistics.pvariance(values), "sampleVariance": statistics.variance(values),
        "countEvery": 3, "countDistinct": 3, "countDistinctNonNull": 3,
        "firstNonNull": 1, "lastNonNull": 5, "countRuns": 3,
        "frequencyHistogram": {"1": 1, "3": 1, "5": 1},
        "allNonZero": 1, "anyNonZero": 1, "and": 1, "or": 1,
        "bitwiseAnd": 1, "bitwiseOr": 7,
        "repeated": {"variance": [statistics.pvariance(values), statistics.pvariance([10, 30, 50])]},
        "named": {"x_min": 1, "x_max": 5, "y_min": 10, "y_max": 50},
        "grouped": {"groups": ROWS}, "outputs": ["min", "max", "variance", "count"],
        "rows": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": None, "properties": row} for row in ROWS
        ]},
    }
    results = python_results()
    assert set(results) == set(expected)
    for key, result in results.items():
        assert result["kind"] == "value"
        if key in {"stdDev", "variance", "sampleVariance"}:
            assert result["value"] == pytest.approx(expected[key], rel=2e-15)
        elif key == "repeated":
            assert result["value"]["variance"] == pytest.approx(expected[key]["variance"], rel=2e-15)
        else:
            assert result["value"] == expected[key], key


def test_all_new_declarations_match_real_leaf_and_expansion_implementations():
    from gee.compat.earthengine.finite_reducer_leaves import finite_leaf_outputs
    from scripts.ee_inventory.declarations import read_declared_handlers

    leaves = finite_leaf_outputs()
    assert set(leaves) == set(workflow_module().LEAVES)
    names = {"Reducer." + name for name in leaves} | {"Reducer.repeat", "Reducer.forEach"}
    assert len(names) == 20
    assert names <= read_declared_handlers(ROOT / "gee/ee_translate.py")


def test_official_python_and_js_clients_produce_identical_values():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for official JavaScript serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const observations=ee.FeatureCollection([
 ee.Feature(null,{zone:'north',x:1,y:10}),ee.Feature(null,{zone:'north',x:3,y:30}),
 ee.Feature(null,{zone:'south',x:5,y:50})]);
const summary=ee.Reducer.minMax().combine({reducer2:ee.Reducer.variance(),sharedInputs:true})
 .combine({reducer2:ee.Reducer.countEvery(),sharedInputs:false});
const grouped=observations.reduceColumns(summary.group({groupField:1,groupName:'zone'}),['x','zone']);
const rows=ee.FeatureCollection(ee.List(grouped.get('groups')).map(g=>ee.Feature(null,ee.Dictionary(g))));
const leaves=['minMax','product','stdDev','variance','sampleVariance','countEvery',
 'countDistinct','countDistinctNonNull','firstNonNull','lastNonNull','countRuns',
 'frequencyHistogram','allNonZero','anyNonZero','and','or','bitwiseAnd','bitwiseOr'];
const values=Object.fromEntries(leaves.map(name=>[name,ee.List([1,3,5]).reduce(ee.ApiFunction._call('Reducer.'+name))]));
Object.assign(values,{repeated:observations.reduceColumns(ee.Reducer.variance().repeat(2),['x','y']),
 named:observations.reduceColumns(ee.Reducer.minMax().forEach(['x','y']),['x','y']),
 grouped,rows,outputs:summary.getOutputs()});
const outputs=Object.fromEntries(Object.entries(values).map(([k,v])=>[k,ee.Serializer.encode(v)]));
if(attempts) throw Error('Unexpected networking');
console.log(JSON.stringify({outputs,attempts}));
"""
    process = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True,
                             text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    actual = json.loads(process.stdout)
    assert actual["attempts"] == 0
    expected = python_results()
    assert set(actual["outputs"]) == set(expected)
    for key, expression in actual["outputs"].items():
        assert compile_expression(expression, [], {}) == expected[key], key


def test_grouped_statistic_rows_use_worker_and_physical_csv_reader(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        task = fixture.ee.batch.Export.table.toDrive(
            collection=workflow_module().build_workflow(fixture.ee)["rows"],
            description="finite grouped statistics", fileFormat="CSV",
            selectors=["zone", "min", "max", "variance", "count"],
        )
        task.start()
        result = run_batch(fixture, task.id)
        assert result.row["status"] == "finished"
        from gee.backend import Jobs

        assets = Jobs().get_result_assets(task.id, USER)
        assert len(assets) == 1
        output = Path(next(iter(assets.values()))["href"])
        assert output.parent == fixture.root / "jobs" / task.id / "out"
        with output.open(newline="") as source:
            rows = list(csv.DictReader(source))
        assert len(rows) == 2
        assert [dict(row, **{key: float(row[key]) for key in row if key != "zone"})
                for row in rows] == ROWS
    assert guard.evidence()["attempt_count"] == 0
