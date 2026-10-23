"""Independent finite preparation results, both SDKs, and trusted CSV route.

The integration uses an in-memory queue and test-double task launch. It does
not claim production database, sandbox, service or browser acceptance.
"""
import csv
import importlib.util
import json
import math
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
    "positive": [0.25, 0.8, 1.1], "encoded": [63, 204, 255],
    "selected": {"red": 2, "nir": 8}, "removed": {"red": 2, "nir": 8},
    "number_integer": -12, "array_byte": [0, 0, 1, 127, 255, 255],
    "float_roundtrip": [16777216, 1.25], "inverse_erf": 0.5,
    "digamma_one": -0.57721566490153286060651209,
    "trigamma": [math.pi ** 2 / 6, math.pi ** 2 / 2],
    "rows": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": None, "properties": {"encoded": value}}
        for value in [63, 204, 255]
    ]},
}


def test_new_family_declarations_match_the_source_only_inventory():
    from gee.compat.earthengine.array_casts import ARRAY_CAST_FUNCTIONS
    from gee.compat.earthengine.number_casts import NUMBER_CAST_FUNCTIONS
    from gee.compat.earthengine.static_container_selection import STATIC_CONTAINER_SELECTION_FUNCTIONS
    from gee.compat.earthengine.static_special_math import STATIC_SPECIAL_MATH_FUNCTIONS
    from scripts.ee_inventory.declarations import read_declared_handlers

    declared = read_declared_handlers(ROOT / "gee/ee_translate.py")
    family = (ARRAY_CAST_FUNCTIONS | NUMBER_CAST_FUNCTIONS
              | STATIC_CONTAINER_SELECTION_FUNCTIONS | STATIC_SPECIAL_MATH_FUNCTIONS)
    assert len(family) == 61
    assert family <= declared


def workflow(ee):
    spec = importlib.util.spec_from_file_location(
        "numeric_preparation", ROOT / "examples/40_GEE_python_numeric_preparation.py")
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


def test_numeric_preparation_has_independent_expected_results():
    compiled = python_results()
    for key, expected in EXPECTED.items():
        assert compiled[key]["kind"] == "value"
        actual = compiled[key]["value"]
        if key in {"inverse_erf", "digamma_one", "trigamma"}:
            assert actual == pytest.approx(expected, rel=5e-13, abs=5e-15)
        else:
            assert actual == expected


def test_numeric_preparation_official_python_and_js_outputs_agree():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for official JavaScript serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const positive = ee.List([-0.1,0.25,0.8,1.1]).filter(ee.Filter.gt('item',0));
const encoded = positive.map(value => ee.Number(value).multiply(255).toByte());
const metadata = ee.Dictionary({red:2,nir:8,cloud:90,unused:null});
const values = {positive, encoded, selected:metadata.select(['red','nir']),
 removed:metadata.remove(['cloud','unused']), number_integer:ee.Number(-12.75).toInt16(),
 array_byte:ee.Array([-0.1,0.1,0.5,127.1,255.1,255.9]).byte(),
 float_roundtrip:ee.Array([16777217,1.25]).toFloat().toDouble(),
 inverse_erf:ee.Number(0.5).erf().erfInv(), digamma_one:ee.Number(1).digamma(),
 trigamma:ee.Array([1,0.5]).trigamma(),
 rows:ee.FeatureCollection(encoded.map(value => ee.Feature(null,{encoded:value})))};
const outputs=Object.fromEntries(Object.entries(values).map(([key,value])=>[key,ee.Serializer.encode(value)]));
if(attempts !== 0) throw Error('Unexpected networking');
console.log(JSON.stringify({outputs,attempts}));
"""
    process = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True,
                             text=True, timeout=20)
    assert process.returncode == 0, process.stderr
    results = json.loads(process.stdout)
    assert results["attempts"] == 0
    expected = python_results()
    assert set(results["outputs"]) == set(expected)
    for key, expression in results["outputs"].items():
        assert compile_expression(expression, [], {}) == expected[key]


def test_prepared_rows_export_through_dispatch_worker_and_csv_reader(tmp_path, monkeypatch):
    with OfflineGuard() as guard:
        fixture = install(monkeypatch, tmp_path)
        rows = workflow(fixture.ee)["rows"]
        task = fixture.ee.batch.Export.table.toDrive(
            collection=rows, description="numeric preparation", fileFormat="CSV",
            selectors=["encoded"],
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
            assert list(csv.DictReader(source)) == [{"encoded": str(v)} for v in [63, 204, 255]]
    assert guard.evidence()["attempt_count"] == 0
