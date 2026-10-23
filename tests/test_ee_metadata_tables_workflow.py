"""Cross-family official-client computation and actual trusted CSV readback.

Queue/database and native launch remain test doubles; this is portable
synthetic integration, not browser, sandbox or Google-service acceptance.
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
EXPECTED = {
    "parts": ["S2", "20200229", "tile"], "matched_date": ["20200229"],
    "renamed_scene": "S2-20200229-tile", "parsed_date": 1582934400000,
    "next_year": "2021-02-28", "month_range": [1580515200000, 1583020800000],
    "minutes_per_day": 1440, "bits": [1, 1, 0, 1], "cut": [[3, 4]],
    "masked": [10, 30], "index": 0.6, "selected": {"B2": 2, "B3": 3},
    "rows": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None,
         "properties": {"label": label, "score": score, "scaled": scaled}}
        for label, score, scaled in [(1, 0.2, 20), (2, 0.6, 60)]
    ]},
}


def workflow(ee):
    spec = importlib.util.spec_from_file_location(
        "metadata_tables", ROOT / "examples/41_GEE_python_metadata_tables.py")
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


def test_wave36_declarations_match_source_only_inventory():
    from gee.compat.earthengine.array_selection import ARRAY_SELECTION_FUNCTIONS
    from gee.compat.earthengine.date_calendar import SUPPORTED_DATE_CALENDAR_FUNCTIONS
    from gee.compat.earthengine.feature_table_selection import FEATURE_TABLE_SELECTION_METHODS
    from gee.compat.earthengine.number_expression import NUMBER_EXPRESSION_FUNCTIONS
    from gee.compat.earthengine.string_regex import STRING_REGEX_FUNCTIONS
    from scripts.ee_inventory.declarations import read_declared_handlers

    families = (ARRAY_SELECTION_FUNCTIONS | SUPPORTED_DATE_CALENDAR_FUNCTIONS
                | FEATURE_TABLE_SELECTION_METHODS | NUMBER_EXPRESSION_FUNCTIONS
                | STRING_REGEX_FUNCTIONS)
    assert len(families) == 14
    assert families <= read_declared_handlers(ROOT / "gee/ee_translate.py")


def test_metadata_preparation_independent_expected_results():
    for key, result in python_results().items():
        assert result["kind"] == "value"
        if key == "index":
            assert result["value"] == pytest.approx(EXPECTED[key], abs=2e-16)
        else:
            assert result["value"] == EXPECTED[key], key


def test_metadata_preparation_python_js_results_agree():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for official JavaScript serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const scene=ee.String('S2_20200229_tile'), parts=scene.split('_');
const date=ee.Date.parse('yyyyMMdd',ee.String(parts.get(1)));
// The pinned JS SDK does not publish the hidden Python static binding.
const columns=ee.FeatureCollection(ee.call('Collection.fromColumns',
 [['forest','water','forest','other'],[0.2,0.6,0.2,0.9]],['label','score']));
const rows=columns.distinct(['label','score']).remap(['forest','water'],[1,2],'label')
 .map(f=>f.set('scaled',ee.Number.expression('score * 100',{score:f.get('score')}).toInt()));
const values={parts,matched_date:scene.match('[0-9]{8}'),renamed_scene:scene.replace('_','-','g'),
 parsed_date:date.millis(),next_year:date.update({year:2021}).format('yyyy-MM-dd'),
 month_range:date.getRange('month'),minutes_per_day:ee.Date.unitRatio('day','minute'),
 bits:ee.Array.bitsToArray(13),cut:ee.Array([[1,2],[3,4]]).cut([1,-1]),
 masked:ee.Array([10,20,30]).mask(ee.Array([1,0,1])),
 index:ee.Number.expression('(v.nir-v.red)/(v.nir+v.red)',{v:{nir:0.8,red:0.2}}),
 selected:ee.Dictionary({B2:2,B3:3,cloud:90}).select(['B[23]']),rows};
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


def test_prepared_metadata_rows_export_through_worker_and_csv_reader(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        task = fixture.ee.batch.Export.table.toDrive(
            collection=workflow(fixture.ee)["rows"], description="metadata table preparation",
            fileFormat="CSV", selectors=["label", "score", "scaled"],
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
            assert list(csv.DictReader(source)) == [
                {"label": "1", "score": "0.2", "scaled": "20"},
                {"label": "2", "score": "0.6", "scaled": "60"},
            ]
    assert guard.evidence()["attempt_count"] == 0
