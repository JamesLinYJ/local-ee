"""Pinned offline SDK formulas retaining original planar MultiPolygon atoms."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-planar-multipolygon-wave72-v1.json"
METHODS = ("area", "length", "perimeter", "centroid")


def fixture():
    return json.loads(FIXTURE.read_bytes())


def configured_ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


def encoded(ee, value):
    return json.loads(json.dumps(ee.serializer.encode(value, for_cloud_api=False)))


def wire_hash(wire):
    raw = json.dumps(wire, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def source_feature(ee, name, geometry, rank):
    return ee.Feature({
        "type": "Feature", "id": f"wave72-{name}",
        "properties": {"label": name, "source_rank": rank,
                       "nested": {"labels": [name, "preserved"], "rank": rank}},
        "geometry": deepcopy(geometry),
    })


def targeted_collection(ee, data):
    features = [source_feature(ee, name, data["cases"][name]["geometry"], rank)
                for rank, name in enumerate(data["targeted_workflow"]["input_features"])]
    projection = ee.Projection("EPSG:4326")

    def add_metrics(feature):
        return feature.set({
            "system:index": feature.id(), "feature_id": feature.id(),
            "area": feature.area(proj=projection),
            "length": feature.length(proj=projection),
            "perimeter": feature.perimeter(proj=projection),
            "centroid": feature.centroid(proj=projection).geometry().coordinates(),
        })

    return ee.FeatureCollection(features).map(add_metrics)


def python_wires(ee, data):
    projection = ee.Projection("EPSG:4326")
    controls, originals = {}, {}
    for rank, (name, case) in enumerate(data["cases"].items()):
        geometry = ee.Geometry(case["geometry"])
        feature = source_feature(ee, name, case["geometry"], rank)
        for owner, value in (("Geometry", geometry), ("Feature", feature)):
            for method in METHODS:
                key = f"{name}/{owner}.{method}"
                controls[key] = encoded(ee, getattr(value, method)(proj=projection))
    for name, prefix in (("duplicate", "planar-duplicate-polygon"),
                         ("overlap", "planar-overlap-polygon")):
        geometry = ee.Geometry(data["cases"][name]["geometry"])
        feature = ee.Feature(geometry, {"label": prefix})
        for owner, value in (("Geometry", geometry), ("Feature", feature)):
            for method in METHODS:
                originals[f"{prefix}/{owner}.{method}"] = encoded(
                    ee, getattr(value, method)(proj="EPSG:4326"),
                )
    return {"originals": originals, "controls": controls,
            "workflow": encoded(ee, targeted_collection(ee, data))}


def javascript_wires(data):
    node = shutil.which("node")
    assert node is not None, "Pinned JavaScript SDK checks require existing Node"
    setup = JAVASCRIPT.split("const config = JSON.parse", 1)[0]
    script = setup + r"""
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const projection = ee.Projection('EPSG:4326');
const controls = {}, originals = {};
function sourceFeature(name, geometry, rank) {
  return ee.Feature({type: 'Feature', id: `wave72-${name}`,
    properties: {label: name, source_rank: rank,
      nested: {labels: [name, 'preserved'], rank}}, geometry});
}
for (const [rank, [name, item]] of Object.entries(config.cases).entries()) {
  const geometry = ee.Geometry(item.geometry);
  const feature = sourceFeature(name, item.geometry, rank);
  for (const [owner, value] of [['Geometry', geometry], ['Feature', feature]]) {
    for (const method of ['area', 'length', 'perimeter', 'centroid']) {
      controls[`${name}/${owner}.${method}`] = ee.Serializer.encode(
        value[method]({proj: projection}));
    }
  }
}
for (const [name, prefix] of [['duplicate', 'planar-duplicate-polygon'],
                            ['overlap', 'planar-overlap-polygon']]) {
  const geometry = ee.Geometry(config.cases[name].geometry);
  const feature = ee.Feature(geometry, {label: prefix});
  for (const [owner, value] of [['Geometry', geometry], ['Feature', feature]]) {
    for (const method of ['area', 'length', 'perimeter', 'centroid']) {
      originals[`${prefix}/${owner}.${method}`] = ee.Serializer.encode(
        value[method]({proj: 'EPSG:4326'}));
    }
  }
}
const features = config.targeted_workflow.input_features.map((name, rank) =>
  sourceFeature(name, config.cases[name].geometry, rank));
const workflow = ee.FeatureCollection(features).map(function(feature) {
  return feature.set({
    'system:index': feature.id(), feature_id: feature.id(),
    area: feature.area({proj: projection}),
    length: feature.length({proj: projection}),
    perimeter: feature.perimeter({proj: projection}),
    centroid: feature.centroid({proj: projection}).geometry().coordinates()
  });
});
if (attempts !== 0) throw Error(`SDK attempted ${attempts} network operations`);
process.stdout.write(JSON.stringify({originals, controls,
  workflow: ee.Serializer.encode(workflow), attempts}));
"""
    result = subprocess.run([node, "-e", script], cwd=ROOT, input=json.dumps(data),
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded.pop("attempts") == 0
    return decoded


def expanded(value, scope=None):
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
    return {key: expanded(item, scope) for key, item in value.items()}


def receipt(name, data):
    directory = os.environ.get("GEE_AUDIT_DIR")
    if not directory:
        return
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    with (output / f"wave72-multipolygon-{name}.json").open("x") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")
