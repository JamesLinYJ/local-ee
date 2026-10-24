"""Pinned SDK and independent spherical references for Wave61."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

from ee_random_split_parity import JAVASCRIPT, semantic_wire
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-spherical-wave61-v1.json"
BASELINE_PATH = ROOT / "audit/gee-python-wave61/root/before-defaults.json"
PYTHON_EXAMPLE = ROOT / "examples/66_GEE_python_spherical_geometry.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/20_球面几何.js"
OPERATIONS = (
    "contains", "containedIn", "disjoint", "intersects",
    "intersection", "union", "difference", "symmetricDifference",
)
OVERLAYS = ("intersection", "union", "difference", "symmetricDifference")


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def load_example():
    spec = importlib.util.spec_from_file_location("spherical_geometry_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_wire(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def semantic(value):
    return semantic_wire(json_wire(value))


def python_expressions(fixture):
    example = load_example()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        omitted = example.encode_workflow(ee, example.build_workflow(ee, fixture))
        explicit_null = example.encode_workflow(
            ee, example.build_workflow(ee, fixture, explicit_null_projection=True),
        )
    assert guard.evidence()["attempt_count"] == 0
    return {"omitted": json_wire(omitted), "null": json_wire(explicit_null)}


def javascript_expressions(fixture):
    node = shutil.which("node")
    assert node is not None, "Node is required for pinned JavaScript SDK parity"
    prefix = JAVASCRIPT.split("const config = JSON.parse", 1)[0]
    script = prefix + r"""
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const example = require('./examples/javascript/20_球面几何.js');
const omitted = example.encodeWorkflow(ee, example.buildWorkflow(ee, fixture));
const explicitNull = example.encodeWorkflow(ee,
  example.buildWorkflow(ee, fixture, {explicitNullProjection: true}));
process.stdout.write(JSON.stringify({omitted, null: explicitNull, attempts}));
"""
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT,
        input=json.dumps(fixture, ensure_ascii=False), capture_output=True,
        text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    return {"omitted": decoded["omitted"], "null": decoded["null"]}


def javascript_roundtrip(outputs, fixture):
    """Reconstruct compiler GeoJSON in the pinned JS SDK and encode consumers."""
    node = shutil.which("node")
    assert node is not None, "Node is required for pinned JavaScript SDK roundtrip"
    prefix = JAVASCRIPT.split("const config = JSON.parse", 1)[0]
    script = prefix + r"""
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const expressions = {geometry: {}, feature_ids: {}};
for (const [name, value] of Object.entries(input.geometry)) {
  const geometry = ee.Geometry(value);
  const point = ee.Geometry.Point(input.points[name]);
  expressions.geometry[name] = ee.Serializer.encode(geometry.contains(point));
}
for (const [name, value] of Object.entries(input.features)) {
  expressions.feature_ids[name] = ee.Serializer.encode(ee.Feature(value).id());
}
process.stdout.write(JSON.stringify({expressions, attempts}));
"""
    geometry_values = {
        name: json_wire(outputs["geometry"][name]["value"])
        for name in OVERLAYS
    }
    feature_values = {
        name: json_wire(outputs["feature"][name]["value"])
        for name in OVERLAYS
    }
    point_values = {"intersection": [179, 0], "union": [172, 0],
                    "difference": [172, 0], "symmetricDifference": [172, 0]}
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT,
        input=json.dumps({"geometry": geometry_values, "features": feature_values,
                          "points": point_values}, ensure_ascii=False),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    return decoded["expressions"]


def compile_outputs(expressions):
    return {
        "geometry": {
            name: compile_expression(value, [], {})
            for name, value in expressions["geometry"].items()
        },
        "feature": {
            name: compile_expression(value, [], {})
            for name, value in expressions["feature"].items()
        },
        "probes": {
            name: compile_expression(value, [], {})
            for name, value in expressions["probes"].items()
        },
        "boundary": {
            name: compile_expression(value, [], {})
            for name, value in expressions["boundary"].items()
        },
        "feature_overlays": compile_expression(expressions["feature_overlays"], [], {}),
    }


def root_invocation(encoded):
    scope = dict(encoded.get("scope", []))

    def resolve(value):
        while isinstance(value, dict) and value.get("type") == "ValueRef":
            value = scope[value["value"]]
        if isinstance(value, list):
            return [resolve(child) for child in value]
        if isinstance(value, dict):
            return {key: resolve(child) for key, child in value.items()}
        return value

    root = resolve(encoded["value"])
    assert root["type"] == "Invocation"
    return root


def spherical_winding(point, ring):
    """Signed spherical winding from unit-vector tangent-plane angles.

    This is independent of S2 and GEOS: every coordinate is mapped to a unit
    vector, projected into the query point's tangent plane, and accumulated
    with atan2. The sign distinguishes the directed left side of an oriented
    loop; absolute winding is used for even/odd loops.
    """
    query = _unit(point)
    total = 0.0
    for first, second in zip(ring, ring[1:]):
        a, b = _unit(first), _unit(second)
        a = _normalize(_subtract(a, _scale(query, _dot(query, a))))
        b = _normalize(_subtract(b, _scale(query, _dot(query, b))))
        total += _atan2(_dot(query, _cross(a, b)), _dot(a, b))
    return total


def _signed_ring_area(ring):
    """Signed spherical triangle excess with a unit-vector fan reference."""
    vertices = [_unit(position) for position in ring[:-1]]
    reference = _normalize(tuple(sum(point[axis] for point in vertices)
                                 for axis in range(3)))
    total = 0.0
    for a, b in zip(vertices, vertices[1:] + vertices[:1]):
        determinant = _dot(reference, _cross(a, b))
        denominator = 1 + _dot(reference, a) + _dot(a, b) + _dot(b, reference)
        total += 2 * _atan2(determinant, denominator)
    return total


def spherical_ring_area(ring):
    """Return the independent signed unit-sphere area in steradians."""
    return _signed_ring_area(ring)


def max_coordinate_error_degrees(actual, reference):
    """Measure maximum absolute lon/lat component error for a short path."""
    if len(actual) != len(reference) or not actual:
        raise ValueError("Coordinate paths must have the same nonzero length")
    if any(len(a) != 2 or len(r) != 2 for a, r in zip(actual, reference)):
        raise ValueError("Coordinate paths must contain longitude/latitude pairs")
    return max(abs(float(a[axis]) - float(r[axis]))
               for a, r in zip(actual, reference) for axis in range(2))


def _unit(point):
    import math

    longitude, latitude = map(math.radians, point)
    return (math.cos(latitude) * math.cos(longitude),
            math.cos(latitude) * math.sin(longitude), math.sin(latitude))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _scale(a, amount):
    return tuple(amount * x for x in a)


def _normalize(a):
    import math

    length = math.sqrt(_dot(a, a))
    if length < 1e-14:
        raise ValueError("reference point lies on a ring vertex")
    return tuple(x / length for x in a)


def _atan2(y, x):
    import math
    return math.atan2(y, x)


def _on_minor_arc(point, first, second):
    import math

    p, a, b = _unit(point), _unit(first), _unit(second)

    def angle(x, y):
        return math.atan2(math.sqrt(_dot(_cross(x, y), _cross(x, y))), _dot(x, y))

    return abs(angle(a, p) + angle(p, b) - angle(a, b)) <= 2e-10


def spherical_contains(geometry, point):
    """Independent point membership for fixture polygonal spherical outputs."""
    kind = geometry["type"]
    if kind == "Feature":
        return geometry.get("geometry") is not None and spherical_contains(
            geometry["geometry"], point,
        )
    if kind == "GeometryCollection":
        return any(spherical_contains(child, point) for child in geometry["geometries"])
    if kind == "Point":
        return _on_minor_arc(point, geometry["coordinates"], geometry["coordinates"])
    if kind == "Polygon":
        rings = geometry["coordinates"]
        even_odd = geometry.get("evenOdd", True)
        if even_odd:
            return sum(
                spherical_winding(point, ring) * (1 if _signed_ring_area(ring) > 0 else -1)
                > 3.141592653589793
                for ring in rings
            ) % 2 == 1
        return sum(spherical_winding(point, ring) for ring in rings) > \
            3.141592653589793
    if kind == "MultiPolygon":
        return any(spherical_contains({"type": "Polygon", "coordinates": polygon,
                                       "evenOdd": geometry.get("evenOdd", True)}, point)
                   for polygon in geometry["coordinates"])
    raise AssertionError(f"Point reference does not support output type {kind}")


def verify_baseline_rejects():
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline["base"] == "1318361024db8d1a3560e0f0156e9d416bbe16ae"
    assert baseline["sdk_attempts"]["attempt_count"] == 0
    assert len(baseline["records"]) == 16
    expected = {f"{family}.{operation}" for family in ("Geometry", "Feature")
                for operation in OPERATIONS}
    assert {entry["name"] for entry in baseline["records"]} == expected
    assert all(
        entry["error_type"] == "UnsupportedEEError"
        and "omitted/null proj is spherical" in entry["error"]
        for entry in baseline["records"]
    )
    return hashlib.sha256(BASELINE_PATH.read_bytes()).hexdigest()
