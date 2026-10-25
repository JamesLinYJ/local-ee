"""Serialize the three unchanged historical full measure workflows offline."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from ee_measures_workflow import (
    load_fixture, load_geometrycollection_workflow_fixture, physical_measurement_collection,
)
from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-measure-reuse-wave73-v1.json"
JAVASCRIPT_WIRE_SHA256 = {
    "wgs84_full4": "d60057c21a82fd82de0de4dd2e69e632a6c57901074d7e5a145cb8e8e401f5aa",
    "planar_multipolygon_full6": "2867f0264ec499d3f8a040dbbd114f317c7aefa5bedf88c97a300310a70b7d4e",
    "planar_geometrycollection_full6": "c85c56de461bf9b89fdf9c39dd5aff9f54e4e74b70e5f0ac1582302d76766ffb",
}


def fixture():
    return json.loads(FIXTURE.read_bytes())


def original_fixture():
    return load_geometrycollection_workflow_fixture(load_fixture())


def configured_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def original_collection(ee, record):
    return physical_measurement_collection(ee, original_fixture(), record["route"])


def encoded(ee, value):
    return json.loads(json.dumps(ee.serializer.encode(value, for_cloud_api=False)))


def wire_hash(wire):
    raw = json.dumps(wire, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def expanded(value, scope=None):
    """Resolve ValueRefs and normalize only official optional null arguments."""
    scope = {} if scope is None else scope
    if isinstance(value, list):
        return [expanded(child, scope) for child in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") == "CompoundValue":
        scope.update(value["scope"])
        return expanded(value["value"], scope)
    if value.get("type") == "ValueRef":
        return expanded(scope[value["value"]], scope)
    result = {key: expanded(item, scope) for key, item in value.items()}
    if result.get("type") == "Invocation":
        result["arguments"] = {key: item for key, item in result["arguments"].items()
                               if not (key in {"maxError", "proj"} and item is None)}
    return result


def javascript_wires(data):
    node = shutil.which("node")
    assert node is not None, "Pinned official JavaScript SDK requires existing Node"
    setup = JAVASCRIPT.split("const config = JSON.parse", 1)[0]
    script = setup + r"""
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const outputs = {};
const projection = ee.Projection('EPSG:4326');
for (const [name, record] of Object.entries(config.workflows)) {
  const route = record.route;
  const features = record.config.input_features.map((caseName, rank) => {
    const geometry = JSON.parse(JSON.stringify(config.cases[caseName].geometry));
    if (route.startsWith('explicit_epsg4326_planar') &&
        !['Point', 'MultiPoint'].includes(geometry.type)) geometry.geodesic = false;
    return ee.Feature({type: 'Feature', id: `wave71-${caseName}`,
      properties: {label: caseName, source_rank: rank}, geometry});
  });
  const collection = ee.FeatureCollection(features).map(function(feature) {
    const geometry = feature.geometry();
    const values = {'system:index': feature.id(), feature_id: feature.id()};
    if (route.startsWith('default_wgs84')) {
      for (const method of ['area', 'length', 'perimeter']) {
        values[`geometry_${method}_default`] = geometry[method]();
        values[`feature_${method}_default`] = feature[method]();
        values[`geometry_${method}_null`] = geometry[method](null, null);
        values[`feature_${method}_null`] = feature[method](null, null);
      }
      const geometryCentroid = geometry.centroid();
      const featureCentroid = feature.centroid();
      values.geometry_centroid_default = geometryCentroid.coordinates();
      values.feature_centroid_default = featureCentroid.geometry().coordinates();
      return featureCentroid.set(values);
    }
    for (const method of ['area', 'length', 'perimeter']) {
      values[`geometry_${method}_epsg4326`] = geometry[method]({proj: projection});
      values[`feature_${method}_epsg4326`] = feature[method]({proj: projection});
    }
    const geometryCentroid = geometry.centroid({proj: projection});
    const featureCentroid = feature.centroid({proj: projection});
    values.geometry_centroid_epsg4326 = geometryCentroid.coordinates();
    values.feature_centroid_epsg4326 = featureCentroid.geometry().coordinates();
    return featureCentroid.set(values);
  });
  outputs[name] = ee.Serializer.encode(collection);
}
if (attempts !== 0) throw Error(`SDK attempted ${attempts} network operations`);
process.stdout.write(JSON.stringify({outputs, attempts}));
"""
    result = subprocess.run([node, "-e", script], cwd=ROOT, input=json.dumps(data),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    assert {name: wire_hash(wire) for name, wire in decoded["outputs"].items()} == JAVASCRIPT_WIRE_SHA256
    return decoded["outputs"]


def receipt(name, data):
    directory = os.environ.get("GEE_AUDIT_DIR")
    if not directory:
        return
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    with (output / f"wave73-measure-reuse-{name}.json").open("x") as stream:
        json.dump(data, stream, sort_keys=True, indent=2)
        stream.write("\n")
