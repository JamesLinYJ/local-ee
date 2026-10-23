"""Declared training schema through SDKs, row operations and literal CSV IO."""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_random_split_parity import semantic_wire
from ee_random_split_workflow_helpers import local_metadata
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.table_graph import execute_table_graph, table_input_graph, validate_table_graph
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def fixtures():
    return (json.loads((FIXTURES / "ee-training-schema-v1.json").read_text()),
            json.loads((FIXTURES / "ee-image-sample-rf-v1.json").read_text()))


def example():
    spec = importlib.util.spec_from_file_location(
        "training_schema_example", ROOT / "examples/35_GEE_python_training_schema.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compile_outputs():
    fixture, source = fixtures()
    module = example()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        outputs = {"inline": module.inline_training(ee, fixture),
                   "sampled": module.sampled_training(ee, source)}
        compiled = {mode: {
            name: compile_expression(ee.serializer.encode(value, for_cloud_api=False),
                                     *local_metadata(source))
            for name, value in values.items()
        } for mode, values in outputs.items()}
    assert guard.evidence()["attempt_count"] == 0
    return compiled


def test_implicit_inline_schema_retains_order_and_actual_minimum_distance_values():
    fixture, _ = fixtures()
    compiled = compile_outputs()["inline"]
    for key in ("metadata", "automatic_schema", "explicit_schema", "forest_schema"):
        assert compiled[key]["value"] == fixture["band_order"]
    actual = compiled["predictions"]["value"]
    assert actual == compiled["explicit_predictions"]["value"]
    predictions = [row["properties"]["prediction"] for row in actual["features"]]
    # The fixture's centers come from independent raw property means, with
    # schema order reversed relative to the original feature dictionaries.
    from fractions import Fraction

    centers = []
    for label in (0, 1):
        rows = [r for r in fixture["rows"] if r[fixture["class_property"]] == label]
        centers.append([sum(Fraction(r[name]) for r in rows) / len(rows)
                        for name in fixture["band_order"]])
    assert centers == fixture["reference_centers_in_schema_order"]
    expected = []
    for query in fixture["queries"]:
        vector = [Fraction(query[name]) for name in fixture["band_order"]]
        distances = [sum((x - center)**2 for x, center in zip(vector, row))
                     for row in centers]
        assert distances[0] != distances[1]
        expected.append(min(range(2), key=distances.__getitem__))
    assert predictions == expected == fixture["reference_predictions"]
    assert compiled["collection"]["value"]["properties"] == {
        "band_order": fixture["band_order"], "fixture": fixture["schema"],
    }


def test_sample_schema_and_image_graph_match_explicit_declared_band_order():
    _, source = fixtures()
    compiled = compile_outputs()["sampled"]
    for name in ("metadata", "forest_schema", "minimum_schema"):
        assert compiled[name]["value"] == source["sample_bands"]
    assert semantic_wire(compiled["classified"]) == semantic_wire(compiled["explicit_classified"])
    for descriptor in compiled.values():
        if "process_graph" not in descriptor:
            continue
        validate(descriptor["process_graph"])
        trainers = [node for node in descriptor["process_graph"].values()
                    if node["process_id"] in (
                        "local_ee_train_smile_rf_samples", "local_ee_train_minimum_distance",
                    )]
        assert trainers
        for trainer in trainers:
            spec = json.loads(trainer["arguments"]["spec"])
            assert spec["schema"] == source["sample_bands"]
            assert spec["class_property"] == source["class_property"]
    # The metadata lists every sampled band, even a numeric label. No inferred
    # class-column removal or accidental inclusion of the new split column.
    assert source["class_property"] in compiled["forest_schema"]["value"]
    assert "split" not in compiled["forest_schema"]["value"]


def test_collection_metadata_stays_data_through_literal_csv_writer(tmp_path):
    fixture, _ = fixtures()
    data = compile_outputs()["inline"]["collection"]["value"]
    opaque = {"process_id": "not-a-process", "from_node": "not-a-node",
              "process_graph": {"fake": {"from_node": "also-data"}}}
    data["properties"]["provenance"] = opaque
    selected = ["nir", "red", "landcover"]
    graph = table_input_graph(data, selected)
    graph["gee_table"]["result"] = False
    graph["save"] = {"process_id": "save_result",
                     "arguments": {"data": {"from_node": "gee_table"}, "format": "CSV"},
                     "result": True}
    decoded, columns = validate_table_graph(graph)
    assert decoded["properties"]["provenance"] == opaque and columns == selected
    job = tmp_path / "data/jobs/00000000-0000-4000-8000-000000000030"
    (job / "out").mkdir(parents=True)
    assert execute_table_graph(graph, job)
    with (job / "out/openEO.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(fixture["rows"])
    assert [{k: float(row[k]) for k in selected} for row in rows] == [
        {k: float(row[k]) for k in selected} for row in fixture["rows"]
    ]


JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Training schema parity attempted networking'); }
for (const name of ['node:http', 'node:https']) {
  const api = require(name); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny; global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs'); global.ee = ee;
const raw = JSON.parse(fs.readFileSync('vendor/earthengine-js/algorithms.json')).algorithms;
const signatures = Object.fromEntries(raw.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({name: x.argumentName, type: x.type,
    optional: !!x.optional, description: x.description,
    ...('defaultValue' in x ? {default: x.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = deny;
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ee-training-schema-v1.json'));
const source = JSON.parse(fs.readFileSync('tests/fixtures/ee-image-sample-rf-v1.json'));
const rows = fixture.rows.map((row, i) => ee.Feature(null, row).set('system:index', `site-${i}`));
const collection = ee.FeatureCollection(rows).set({
  band_order: fixture.band_order, fixture: fixture.schema
});
const prepared = collection.randomColumn('split', 30).filter(ee.Filter.lt('split', 1)).limit(rows.length);
const md = ee.Classifier.minimumDistance().train(prepared, fixture.class_property);
const explicitMD = ee.Classifier.minimumDistance().train(prepared, fixture.class_property, fixture.band_order);
const rf = ee.Classifier.smileRandomForest({numberOfTrees:5, seed:30}).train(prepared, fixture.class_property);
const queries = ee.FeatureCollection(fixture.queries.map(row => ee.Feature(null, row)));
const inline = {
  collection: prepared, metadata: prepared.get('band_order'), automatic_schema: md.schema(),
  explicit_schema: explicitMD.schema(), forest_schema: rf.schema(),
  predictions: queries.classify(md, 'prediction'), explicit_predictions: queries.classify(explicitMD, 'prediction')
};
const image = ee.Image(source.scene_id).select(source.sample_bands);
const clean = image.sample({seed:source.sample_seed,dropNulls:false})
  .filter(ee.Filter.notNull(source.sample_bands)).randomColumn('split',30).filter(ee.Filter.lt('split',1));
const forest = ee.Classifier.smileRandomForest({numberOfTrees:5,seed:30}).train(clean,source.class_property);
const explicit = ee.Classifier.smileRandomForest({numberOfTrees:5,seed:30}).train(clean,source.class_property,source.sample_bands);
const minimum = ee.Classifier.minimumDistance().train(clean,source.class_property);
const sampled = {
  metadata:clean.get('band_order'),forest_schema:forest.schema(),minimum_schema:minimum.schema(),
  classified:image.classify(forest),explicit_classified:image.classify(explicit),
  minimum_classified:image.classify(minimum),predictions:clean.classify(forest,'prediction')
};
const outputs = Object.fromEntries(Object.entries({inline,sampled}).map(([mode,values]) =>
  [mode,Object.fromEntries(Object.entries(values).map(([key,value]) => [key,ee.Serializer.encode(value)]))]));
if (attempts !== 0) throw Error(`SDK swallowed ${attempts} network attempts`);
console.log(JSON.stringify({outputs,attempts}));
"""


def test_official_python_and_javascript_optional_schema_graphs_match():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the pinned official JS SDK parity")
    result = subprocess.run([node, "-e", JAVASCRIPT], cwd=ROOT,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["attempts"] == 0
    _, source = fixtures()
    compiled = {mode: {
        name: compile_expression(expression, *local_metadata(source))
        for name, expression in values.items()
    } for mode, values in document["outputs"].items()}
    assert semantic_wire(compiled) == semantic_wire(compile_outputs())
