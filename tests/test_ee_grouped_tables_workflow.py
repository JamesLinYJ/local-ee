"""Official-client grouped computation and actual synthetic CSV readback.

Database/queue storage and native task launching are test doubles. These tests
do not establish browser, production sandbox or Google-service acceptance.
"""
import csv
import importlib.util
import json
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
GROUPS = [
    {"zone": 1, "average": 11, "total": 22, "n": 2},
    {"zone": 2, "average": 21, "total": 42, "n": 2},
]
EXPECTED = {
    "values": [10, 12, 20, 22], "count": 4, "mean": 16,
    "sample_variance": 104 / 3, "population_variance": 26,
    "histogram": {"1": 2, "2": 2}, "distinct_zones": 2,
    "groups": {"groups": GROUPS}, "output_names": ["average", "total", "n"],
    "overlap_start": "2020-03-01", "overlap_end": "2020-03-02",
    "union": [1582848000000, 1583366400000], "contains_leap_day": True,
    "rows": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None, "properties": group} for group in GROUPS
    ]},
}


def workflow(ee):
    spec = importlib.util.spec_from_file_location(
        "grouped_tables", ROOT / "examples/42_GEE_python_grouped_tables.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_workflow(ee)


def python_results():
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        result = {key: compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})
                  for key, value in workflow(ee).items()}
    assert guard.evidence()["attempt_count"] == 0
    return result


def test_wave37_declarations_match_source_only_inventory():
    from gee.compat.earthengine.aggregate_statistics import AGGREGATE_STATISTICS_NAMES
    from gee.compat.earthengine.date_ranges import DATE_RANGE_METHODS
    from scripts.ee_inventory.declarations import read_declared_handlers

    families = AGGREGATE_STATISTICS_NAMES | DATE_RANGE_METHODS | {
        "Collection.flatten", "Reducer.combine", "Reducer.group",
        "Reducer.setOutputs", "Reducer.getOutputs",
    }
    assert len(families) == 28
    assert families <= read_declared_handlers(ROOT / "gee/ee_translate.py")


def test_opaque_values_do_not_become_static_conditions_or_public_json():
    from gee.compat.earthengine.ir import UnsupportedEEError

    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        nested = ee.FeatureCollection([ee.FeatureCollection([ee.Feature(None, {"v": 1})])])
        values = [nested, ee.DateRange.unbounded(), ee.Reducer.sum().group()]
        encode = lambda value: ee.serializer.encode(value, for_cloud_api=False)
        for value in values:
            with pytest.raises(UnsupportedEEError):
                compile_expression(encode(value), [], {})
            with pytest.raises(UnsupportedEEError, match="static.*condition"):
                compile_expression(encode(ee.Algorithms.If(value, 1, 0)), [], {})
        with pytest.raises(UnsupportedEEError, match="finite DateRange"):
            compile_expression(encode(ee.FeatureCollection([]).filter(
                ee.Filter.dateRangeContains(leftValue=ee.DateRange.unbounded(),
                                            rightField="system:time_start"))), [], {})
    assert guard.evidence()["attempt_count"] == 0


def test_grouped_tables_independent_expected_results():
    for key, result in python_results().items():
        assert result["kind"] == "value"
        if key in {"sample_variance", "population_variance"}:
            assert result["value"] == pytest.approx(EXPECTED[key], rel=2e-15)
        else:
            assert result["value"] == EXPECTED[key], key


def test_grouped_tables_python_js_results_agree():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for official JavaScript serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const stations=ee.FeatureCollection([
 ee.Feature(null,{zone:1,value:10}),ee.Feature(null,{zone:2,value:20})]);
const observations=stations.map(s=>ee.FeatureCollection([
 s,s.set('value',ee.Number(s.get('value')).add(2))])).flatten();
const stats=ee.Reducer.mean().combine({reducer2:ee.Reducer.sum(),sharedInputs:true})
 .combine({reducer2:ee.Reducer.count(),sharedInputs:true})
 .setOutputs(['average','total','n']);
const groups=observations.reduceColumns(stats.group({groupField:1,groupName:'zone'}),['value','zone']);
const rows=ee.FeatureCollection(ee.List(groups.get('groups')).map(g=>ee.Feature(null,ee.Dictionary(g))));
const first=ee.DateRange('2020-02-28','2020-03-02'),second=ee.DateRange('2020-03-01','2020-03-05');
const overlap=first.intersection(second);
const values={values:observations.aggregate_array('value'),count:observations.aggregate_count('value'),
 mean:observations.aggregate_mean('value'),sample_variance:observations.aggregate_sample_var('value'),
 population_variance:observations.aggregate_total_var('value'),histogram:observations.aggregate_histogram('zone'),
 distinct_zones:observations.aggregate_count_distinct('zone'),groups,output_names:stats.getOutputs(),
 overlap_start:overlap.start().format('yyyy-MM-dd'),overlap_end:overlap.end().format('yyyy-MM-dd'),
 union:first.union(second),contains_leap_day:first.contains(ee.Date('2020-02-29')),rows};
const outputs=Object.fromEntries(Object.entries(values).map(([k,v])=>[k,ee.Serializer.encode(v)]));
if(attempts) throw Error('Unexpected networking');
console.log(JSON.stringify({outputs,attempts}));
"""
    process = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True,
                             text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["attempts"] == 0
    expected = python_results()
    assert set(result["outputs"]) == set(expected)
    for key, expression in result["outputs"].items():
        assert compile_expression(expression, [], {}) == expected[key]


def test_grouped_rows_export_through_worker_and_csv_reader(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        task = fixture.ee.batch.Export.table.toDrive(
            collection=workflow(fixture.ee)["rows"], description="grouped metadata summary",
            fileFormat="CSV", selectors=["zone", "average", "total", "n"],
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
        assert [{key: float(value) for key, value in row.items()} for row in rows] == GROUPS
    assert guard.evidence()["attempt_count"] == 0
