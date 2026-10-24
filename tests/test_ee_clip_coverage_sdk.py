"""Pinned, offline Python/JavaScript SDK wires for default-geodesic clip workflows."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from gee.ee_python_client import configure_local_ee
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-geodesic-clip-wave70-v1.json"
CATALOG = ROOT / "vendor/earthengine-js/algorithms.json"
SDK_COMMIT = "e189e4b89e785019ea5642ea8e80cb644749cd4a"


def _python_values(ee):
    roi = ee.Geometry.Polygon([
        [[100.17, 30.21], [100.83, 30.22], [100.78, 30.78],
         [100.13, 30.79], [100.17, 30.21]],
    ])
    image = ee.ImageCollection("sentinel-2-l2a").first().select("nir")
    clipped = image.clip(roi)
    scalar = clipped.multiply(2)
    unary = clipped.sqrt()
    return {
        "clip_science": clipped,
        "clip_numeric_mask": clipped.mask(),
        "clip_sample_drop_nulls_false": clipped.sample(dropNulls=False),
        "clip_sample_drop_nulls_true": clipped.sample(dropNulls=True),
        "clip_mask_sample_drop_nulls_false": clipped.mask().sample(dropNulls=False),
        "clip_mask_sample_drop_nulls_true": clipped.mask().sample(dropNulls=True),
        "scalar_math_sample_drop_nulls_false": scalar.sample(dropNulls=False),
        "scalar_math_mask_sample_drop_nulls_false": scalar.mask().sample(dropNulls=False),
        "unary_math_sample_drop_nulls_false": unary.sample(dropNulls=False),
        "unary_math_mask_sample_drop_nulls_false": unary.mask().sample(dropNulls=False),
    }


def _javascript_wires():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to verify the pinned JavaScript SDK wires")
    script = r"""
const fs = require('node:fs');
let networkAttempts = 0;
function denyNetwork() { networkAttempts++; throw Error('network is disabled in this SDK wire test'); }
for (const name of ['node:http', 'node:https']) {
  const mod = require(name); mod.request = denyNetwork; mod.get = denyNetwork;
}
const net = require('node:net');
net.connect = denyNetwork; net.createConnection = denyNetwork;
net.Socket.prototype.connect = denyNetwork;
const dns = require('node:dns'); dns.lookup = denyNetwork; dns.resolve = denyNetwork;
global.fetch = denyNetwork;
global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs');
global.ee = ee;
const raw = JSON.parse(fs.readFileSync('vendor/earthengine-js/algorithms.json')).algorithms;
const signatures = Object.fromEntries(raw.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({name: x.argumentName, type: x.type,
    optional: !!x.optional, description: x.description,
    ...('defaultValue' in x ? {default: x.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
        ee.initialize('http://127.0.0.1:1/openeo/1.2', 'http://127.0.0.1:1/openeo/1.2');
ee.data.computeValue = denyNetwork;
const roi = ee.Geometry.Polygon([[
  [100.17, 30.21], [100.83, 30.22], [100.78, 30.78],
  [100.13, 30.79], [100.17, 30.21]
]]);
const image = ee.ImageCollection('sentinel-2-l2a').first().select('nir');
const clipped = image.clip(roi);
const scalar = clipped.multiply(2);
const unary = clipped.sqrt();
const values = {
  clip_science: clipped,
  clip_numeric_mask: clipped.mask(),
  clip_sample_drop_nulls_false: clipped.sample({dropNulls: false}),
  clip_sample_drop_nulls_true: clipped.sample({dropNulls: true}),
  clip_mask_sample_drop_nulls_false: clipped.mask().sample({dropNulls: false}),
  clip_mask_sample_drop_nulls_true: clipped.mask().sample({dropNulls: true}),
  scalar_math_sample_drop_nulls_false: scalar.sample({dropNulls: false}),
  scalar_math_mask_sample_drop_nulls_false: scalar.mask().sample({dropNulls: false}),
  unary_math_sample_drop_nulls_false: unary.sample({dropNulls: false}),
  unary_math_mask_sample_drop_nulls_false: unary.mask().sample({dropNulls: false})
};
if (networkAttempts !== 0) throw Error(`unexpected network attempts: ${networkAttempts}`);
console.log(JSON.stringify(Object.fromEntries(Object.entries(values).map(
  ([name, value]) => [name, ee.Serializer.encode(value)]))));
"""
    completed = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=20,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr)
    return json.loads(completed.stdout)


def _invocations(value):
    found = []
    if isinstance(value, dict):
        if value.get("type") == "Invocation":
            found.append(value)
        for child in value.values():
            found.extend(_invocations(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_invocations(child))
    return found


def _objects_of_type(value, type_name):
    found = []
    if isinstance(value, dict):
        if value.get("type") == type_name:
            found.append(value)
        for child in value.values():
            found.extend(_objects_of_type(child, type_name))
    elif isinstance(value, list):
        for child in value:
            found.extend(_objects_of_type(child, type_name))
    return found


@pytest.fixture(scope="module")
def captured_wires():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48, signatures_path=CATALOG,
        )
        assert ee.__version__ == "1.7.49"
        python = {
            name: json.loads(json.dumps(
                ee.serializer.encode(value, is_compound=True, for_cloud_api=False)
            ))
            for name, value in _python_values(ee).items()
        }
        assert guard.evidence()["attempt_count"] == 0
    return python, _javascript_wires()


def test_original_python_and_javascript_sdk_wires_match_frozen_fixture(captured_wires):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["sdk"]["source_commit"] == SDK_COMMIT
    assert fixture["sdk"]["python"] == fixture["sdk"]["javascript"] == "1.7.49"
    python, javascript = captured_wires
    assert python == fixture["sdk_wires"]["python"]
    assert javascript == fixture["sdk_wires"]["javascript"]
    assert python == javascript
    assert fixture["sdk_wires"]["parity"]["matching"] == 10
    assert fixture["sdk_wires"]["parity"]["total"] == 10


def test_default_clip_geometry_and_sample_arguments_stay_implicit(captured_wires):
    python, javascript = captured_wires
    for wires in (python, javascript):
        for expression in wires.values():
            geometry = _objects_of_type(expression, "Polygon")[0]
            assert geometry["evenOdd"] is True
            assert "geodesic" not in geometry
            assert "proj" not in geometry

        for name, expression in wires.items():
            samples = [item for item in _invocations(expression)
                       if item.get("functionName") == "Image.sample"]
            if "sample" not in name:
                assert samples == []
                continue
            assert len(samples) == 1
            args = samples[0]["arguments"]
            assert "region" not in args
            assert args["dropNulls"] is ("drop_nulls_true" in name)


def test_fixture_records_preimplementation_local_rejections_without_fabricated_results():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    baseline = fixture["before_implementation_local_baseline"]
    expected_names = set(fixture["workflow"]["expressions"])
    outcomes = baseline["compile_outcomes"]
    assert {item["id"] for item in outcomes} == expected_names
    assert all(item["status"] == "rejected" for item in outcomes)
    assert all("spherical raster/reprojection adapter" in item["reason"]
               for item in outcomes)
    assert baseline["network_calls"] == "none"
    state = fixture["verification_state"]
    assert state["actual_local_kernel_readback"] == "not_run"
    assert state["sample_rows"] == "not_generated"
    assert state["physical_csv"] is None
