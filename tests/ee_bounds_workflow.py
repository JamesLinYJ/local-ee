"""Offline dual-SDK wires and independent references for bounds workflows."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess

from gee.ee_python_client import configure_local_ee
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-bounds-wave69-v2.json"
PYTHON_EXAMPLE = ROOT / "examples/73_GEE_python_geometry_bounds.py"
JAVASCRIPT_EXAMPLE = ROOT / "examples/javascript/27_几何范围.js"
AUDIT = ROOT / "audit/gee-python-wave69/workflow/v2"

JAVASCRIPT_HARNESS = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Bounds wire capture attempted networking'); }
for (const name of ['node:http', 'node:https']) {
  const api = require(name); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
const tls = require('node:tls'); tls.connect = deny;
global.fetch = deny; global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs'); global.ee = ee;
const algorithms = JSON.parse(fs.readFileSync('vendor/earthengine-js/algorithms.json')).algorithms;
const signatures = Object.fromEntries(algorithms.map(a => [a.name.replace(/^algorithms\//, ''), {
  description: a.description, returns: a.returnType,
  args: (a.arguments || []).map(x => ({name: x.argumentName, type: x.type,
    optional: !!x.optional, description: x.description,
    ...('defaultValue' in x ? {default: x.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = deny;
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const example = require('./examples/javascript/27_几何范围.js');
const workflow = example.buildWorkflow(ee, fixture);
const numeric = example.buildNumericReferences(ee, fixture);
function encodeMap(source) {
  return Object.fromEntries(Object.entries(source).map(([name, value]) =>
    [name, ee.Serializer.encode(value)]));
}
const expressions = {
  workflow: encodeMap(Object.fromEntries(Object.entries(workflow)
    .filter(([name]) => name !== 'explicit_null_controls'))),
  explicit_null_controls: encodeMap(workflow.explicit_null_controls),
  numeric_references: encodeMap(numeric)
};
if (attempts !== 0) throw Error(`SDK attempted ${attempts} network call(s)`);
process.stdout.write(JSON.stringify({expressions, attempts}));
"""


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def load_example():
    spec = importlib.util.spec_from_file_location("bounds_wave69_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_owned(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _encode_python(ee, values):
    return {
        "workflow": {
            name: ee.serializer.encode(value, for_cloud_api=False)
            for name, value in values.items()
            if name != "explicit_null_controls"
        },
        "explicit_null_controls": {
            name: ee.serializer.encode(value, for_cloud_api=False)
            for name, value in values["explicit_null_controls"].items()
        },
    }


def python_capture(fixture=None):
    fixture = fixture or load_fixture()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        if ee.__version__ != "1.7.49":
            raise AssertionError(f"Expected Python SDK 1.7.49, got {ee.__version__}")
        example = load_example()
        workflow = example.build_workflow(ee, fixture)
        numeric = example.build_numeric_references(ee, fixture)
        expressions = _encode_python(ee, workflow)
        expressions["numeric_references"] = {
            name: ee.serializer.encode(value, for_cloud_api=False)
            for name, value in numeric.items()
        }
        evidence = guard.evidence()
    if evidence["attempt_count"]:
        raise AssertionError(f"Python SDK attempted network I/O: {evidence}")
    return {
        "sdk": {"language": "python", "version": ee.__version__,
                "source_commit": "e189e4b89e785019ea5642ea8e80cb644749cd4a"},
        "network_guard": evidence,
        "expressions": json_owned(expressions),
    }


def javascript_capture(fixture=None):
    fixture = fixture or load_fixture()
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required for pinned JavaScript SDK wire capture")
    result = subprocess.run(
        [node, "-e", JAVASCRIPT_HARNESS], cwd=ROOT,
        input=json.dumps(fixture, ensure_ascii=False, allow_nan=False),
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise AssertionError(result.stderr)
    decoded = json.loads(result.stdout)
    if decoded["attempts"]:
        raise AssertionError("JavaScript SDK attempted network I/O")
    return {
        "sdk": {"language": "javascript", "version": "1.7.49",
                "source_commit": "e189e4b89e785019ea5642ea8e80cb644749cd4a"},
        "network_guard": {
            "attempt_count": decoded["attempts"],
            "mode": "deny-and-count fetch, HTTP, HTTPS, TLS, DNS, and socket connectors",
        },
        "expressions": json_owned(decoded["expressions"]),
    }


def local_sources(fixture=None):
    fixture = fixture or load_fixture()
    return load_example().local_sources(fixture)


def canonical_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def root_invocation(expression):
    scope = dict(expression.get("scope", []))

    def resolve(value):
        while isinstance(value, dict) and value.get("type") == "ValueRef":
            value = scope[value["value"]]
        return value

    return resolve(expression["value"])


def _unit(point):
    lon, lat = map(lambda number: number * 3.141592653589793 / 180.0, point)
    return (math.cos(lat) * math.cos(lon),
            math.cos(lat) * math.sin(lon), math.sin(lat))


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right, strict=True))


def _cross(left, right):
    return (left[1] * right[2] - left[2] * right[1],
            left[2] * right[0] - left[0] * right[2],
            left[0] * right[1] - left[1] * right[0])


def _norm(value):
    return math.sqrt(_dot(value, value))


def _angle(left, right):
    return math.atan2(_norm(_cross(left, right)), _dot(left, right))


def great_circle_arc_extrema(start, end):
    """Analytically return endpoints and latitude extrema on a minor arc."""
    first, last = _unit(start), _unit(end)
    normal = _cross(first, last)
    normal_length = _norm(normal)
    if normal_length < 1e-14:
        raise ValueError("Reference arc is coincident or antipodal")
    normal = tuple(value / normal_length for value in normal)
    candidates = [first, last]
    projected_north = (-normal[0] * normal[2],
                       -normal[1] * normal[2], 1.0 - normal[2] ** 2)
    projected_length = _norm(projected_north)
    if projected_length > 1e-14:
        north = tuple(value / projected_length for value in projected_north)
        for candidate in (north, tuple(-value for value in north)):
            if abs(_angle(first, candidate) + _angle(candidate, last)
                   - _angle(first, last)) <= 2e-12:
                candidates.append(candidate)
    return [
        (math.degrees(math.atan2(point[1], point[0])),
         math.degrees(math.asin(max(-1.0, min(1.0, point[2])))))
        for point in candidates
    ]


def analytic_geometry_bounds(geometry):
    """Compute reference extrema without S2, GEOS, or vertex-only bounds."""
    kind = geometry["type"]
    if kind == "Polygon":
        rings = geometry["coordinates"]
        paths = [ring for ring in rings]
    elif kind == "LineString":
        paths = [geometry["coordinates"]]
    else:
        raise ValueError(f"Unsupported analytic reference type: {kind}")
    points = []
    for path in paths:
        if geometry["edge_model"] == "planar":
            points.extend(tuple(map(float, point)) for point in path)
            continue
        for start, end in zip(path, path[1:]):
            points.extend(great_circle_arc_extrema(start, end))
    return [min(point[0] for point in points), min(point[1] for point in points),
            max(point[0] for point in points), max(point[1] for point in points)]
