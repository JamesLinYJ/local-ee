"""Independent fixtures, SDK wires and numerical references for Wave65 sampling."""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import struct


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-weighted-sampling-wave65-v1.json"
PYTHON_EXAMPLE = ROOT / "examples/69_GEE_python_masked_samples.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/23_带权掩膜取样.js"


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def load_python_example():
    spec = importlib.util.spec_from_file_location("wave65_python_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _float32(value):
    return struct.unpack("!f", struct.pack("!f", float(value)))[0]


def independent_projected_tiles(fixture: dict) -> dict:
    """Project fixture values without calling the Scala mask or sampling code."""
    output = {}
    for tile in fixture["tiles"]:
        key = f"{tile['col']},{tile['row']}"
        rows = {}
        for raw_band, mask_band in zip(tile["raw_bands"], tile["mask_bands"]):
            values = []
            for raw, weight in zip(raw_band["values"], mask_band["values"]):
                if raw is None or weight is None or weight <= 0:
                    values.append(None)
                    continue
                value = _float32(raw) if raw_band["cell_type"] == "float32-stage" else raw
                values.append(float(value))
            rows[raw_band["name"]] = values
        output[key] = rows
    return output


def independent_positive_tiles(fixture: dict) -> dict:
    """Treat every mask as one while preserving source NoData and cast stages."""
    output = {}
    for tile in fixture["tiles"]:
        key = f"{tile['col']},{tile['row']}"
        rows = {}
        for raw_band in tile["raw_bands"]:
            rows[raw_band["name"]] = [
                None if raw is None else float(
                    _float32(raw) if raw_band["cell_type"] == "float32-stage" else raw
                )
                for raw in raw_band["values"]
            ]
        output[key] = rows
    return output


def expected_rows(projected: dict, *, drop_nulls: bool = False) -> list[dict]:
    bands = ["class_id", "red", "wide_float", "nir"]
    rows = []
    for row in range(2):
        for col in range(4):
            tile_key = f"{col // 2},{row // 2}"
            tile_col = col % 2
            tile_row = row % 2
            index = tile_row * 2 + tile_col
            values = [projected[tile_key][band][index] for band in bands]
            if drop_nulls and any(value is None for value in values):
                continue
            rows.append({
                "feature": 0,
                "row": row,
                "col": col,
                "x": col + 0.5,
                "y": 1.5 - row,
                "values": values,
            })
    return rows


def _semantic_wire(value, key=None):
    """Normalize SDK numeric JSON and canonical JSON values embedded as strings."""
    if key in {"spec", "rows"} and type(value) is str:
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            pass
    if type(value) is dict:
        return {name: _semantic_wire(item, name) for name, item in value.items()}
    if type(value) in (list, tuple):
        return [_semantic_wire(item) for item in value]
    if type(value) in (int, float) and not isinstance(value, bool):
        return ("number", float(value).hex())
    return value


JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Wave65 sampling attempted networking'); }
for (const module of ['node:http', 'node:https']) {
  const api = require(module); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny;
global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs');
global.ee = ee;
const fixture = JSON.parse(fs.readFileSync(
  'tests/fixtures/ee-weighted-sampling-wave65-v1.json', 'utf8'));
const raw = JSON.parse(fs.readFileSync('vendor/earthengine-js/algorithms.json', 'utf8')).algorithms;
const signatures = Object.fromEntries(raw.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({name: x.argumentName, type: x.type,
    optional: !!x.optional, description: x.description,
    ...('defaultValue' in x ? {default: x.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = deny;
const example = require('./examples/javascript/23_带权掩膜取样.js');
const outputs = example.buildWorkflow(
  ee, ee.Image(fixture.source_id), ee.FeatureCollection(fixture.sample_regions), fixture);
const encoded = Object.fromEntries(Object.entries(outputs).map(([name, value]) =>
  [name, ee.Serializer.encode(value)]));
if (attempts !== 0) throw Error('JavaScript SDK swallowed a network attempt');
console.log(JSON.stringify({attempts, encoded}));
"""


def javascript_wires() -> dict:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required for official JavaScript SDK parity")
    result = subprocess.run(
        [node, "-e", JAVASCRIPT], cwd=ROOT, capture_output=True, text=True, timeout=25,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    payload = json.loads(result.stdout)
    if payload["attempts"] != 0:
        raise AssertionError("JavaScript SDK attempted a network request")
    return payload["encoded"]


def python_wires_and_descriptors(ee, example, fixture: dict):
    from gee.ee_translate import compile_expression

    catalog, items = example.synthetic_metadata()
    image = ee.Image(fixture["source_id"])
    regions = ee.FeatureCollection(fixture["sample_regions"])
    outputs = example.build_workflow(ee, image, regions, fixture)
    wires = {
        name: ee.serializer.encode(value, for_cloud_api=False)
        for name, value in outputs.items()
    }
    descriptors = {
        name: compile_expression(wire, catalog, items)
        for name, wire in wires.items()
    }
    return wires, descriptors


def assert_rows_match(actual: list[dict], expected: list[dict]) -> None:
    assert len(actual) == len(expected)
    for row, reference in zip(actual, expected):
        assert set(row) == {"feature", "row", "col", "x", "y", "values"}
        assert (row["feature"], row["row"], row["col"]) == (
            reference["feature"], reference["row"], reference["col"],
        )
        assert math.isclose(row["x"], reference["x"], rel_tol=0, abs_tol=0)
        assert math.isclose(row["y"], reference["y"], rel_tol=0, abs_tol=0)
        assert len(row["values"]) == len(reference["values"])
        for observed, wanted in zip(row["values"], reference["values"]):
            if wanted is None:
                assert observed is None
            else:
                assert observed == wanted
