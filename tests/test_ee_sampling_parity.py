"""Pinned Python/JavaScript serializer parity for sampled training graphs."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_sampling_workflow_helpers import compile_inputs, load_fixture
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
METRICS = ("euclidean", "manhattan", "cosine")
JAVASCRIPT = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Sampling parity attempted networking'); }
for (const name of ['node:http', 'node:https']) {
  const api = require(name); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny; global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs'); global.ee = ee;
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ee-sampling-training-v1.json'));
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
const regions = ee.FeatureCollection(fixture.training_features);
const samples = ee.Image('wave24-sampling-a').select(fixture.input_properties).sampleRegions({
  collection: regions, properties: fixture.sample_properties, geometries: true
});
const outputs = {sample: ee.Serializer.encode(samples)};
for (const metric of ['euclidean', 'manhattan', 'cosine']) {
  const classifier = ee.Classifier.minimumDistance(metric, 1).train({
    features: samples, classProperty: fixture.class_property,
    inputProperties: fixture.input_properties
  });
  outputs[metric] = ee.Serializer.encode(
    ee.ImageCollection(fixture.collection_id).map(image =>
      image.select(['nir', 'red']).classify({classifier, outputName: fixture.output_name}))
  );
}
if (attempts) throw Error('Networking attempts: ' + attempts);
console.log(JSON.stringify({outputs, attempts}));
"""


@pytest.fixture(scope="module")
def serialized():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for actual official JavaScript serialization")
    process = subprocess.run([node, "-e", JAVASCRIPT], cwd=ROOT,
                             capture_output=True, text=True, timeout=15)
    assert process.returncode == 0, process.stderr
    javascript = json.loads(process.stdout)
    assert javascript["attempts"] == 0
    return javascript["outputs"]


def _compile_python(expression_builder):
    data = load_fixture()
    catalog, items, *_ = compile_inputs(data)
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        descriptor = compile_expression(
            ee.serializer.encode(expression_builder(ee, data), for_cloud_api=False),
            catalog, items,
        )
    assert guard.evidence()["attempt_count"] == 0
    return descriptor


def _sample_expression(ee, data):
    return ee.Image("wave24-sampling-a").select(data["input_properties"]).sampleRegions(
        collection=ee.FeatureCollection(data["training_features"]),
        properties=data["sample_properties"], geometries=True,
    )


def _mapped_expression(ee, data, metric):
    samples = _sample_expression(ee, data)
    classifier = ee.Classifier.minimumDistance(metric=metric, kNearest=1).train(
        features=samples, classProperty=data["class_property"],
        inputProperties=data["input_properties"],
    )
    return ee.ImageCollection(data["collection_id"]).map(
        lambda image: image.select(["nir", "red"]).classify(
            classifier, outputName=data["output_name"],
        ),
    )


def _assert_training_branch(result, data, metric):
    validate(result["process_graph"])
    assert result["kind"] == "collection"
    assert result["bands"] == [data["output_name"]]
    assert set(result["source_item_ids"]) == {item["id"] for item in data["items"]}

    graph = result["process_graph"]
    samplers = [(key, node) for key, node in graph.items()
                if node["process_id"] == "local_ee_sample_regions"]
    trainers = [(key, node) for key, node in graph.items()
                if node["process_id"] == "local_ee_train_minimum_distance"]
    assert len(samplers) == len(trainers) == 1
    sampler_id, sampler = samplers[0]
    trainer_id, trainer = trainers[0]
    assert trainer["arguments"]["data"] == {"from_node": sampler_id}
    assert trainer["arguments"]["spec"]
    assert json.loads(trainer["arguments"]["spec"]) == {
        "version": 1, "metric": metric,
        "class_property": data["class_property"],
        "schema": data["input_properties"],
    }
    sample_spec = json.loads(sampler["arguments"]["spec"])
    assert sample_spec["grid"] == {"scale": None, "crs": None}

    pending = [sampler["arguments"]["data"]["from_node"]]
    visited = set()
    loads = []
    processes = set()
    while pending:
        node_id = pending.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        node = graph[node_id]
        processes.add(node["process_id"])
        if node["process_id"] == "load_collection":
            loads.append(node["arguments"])
            continue

        def visit(value):
            if isinstance(value, dict):
                if set(value) == {"from_node"}:
                    pending.append(value["from_node"])
                else:
                    for child in value.values():
                        visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(node["arguments"])

    assert len(loads) == 1
    assert loads[0]["_gee_item_ids"] == ["wave24-sampling-a"]
    assert loads[0]["spatial_extent"] == {"west": 0, "south": 0, "east": 4, "north": 3}
    assert "resample_spatial" not in processes
    classifiers = [node for node in graph.values()
                   if node["process_id"] == "local_ee_minimum_distance"]
    assert classifiers
    assert all(node["arguments"]["model"] == {"from_node": trainer_id}
               for node in classifiers)


def test_official_python_and_js_direct_sample_table_descriptors_match(serialized):
    python = _compile_python(_sample_expression)
    assert python == compile_expression(serialized["sample"], *compile_inputs(load_fixture())[:2])
    validate(python["process_graph"])
    assert python["kind"] == "sample_table"


@pytest.mark.parametrize("metric", METRICS)
def test_official_python_and_js_sampled_training_classification_graphs_match(serialized, metric):
    data = load_fixture()
    python = _compile_python(lambda ee, fixture: _mapped_expression(ee, fixture, metric))
    javascript = compile_expression(serialized[metric], *compile_inputs(data)[:2])
    assert python == javascript
    _assert_training_branch(python, data, metric)
