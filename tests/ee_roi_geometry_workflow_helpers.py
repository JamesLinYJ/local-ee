"""Pinned-SDK and hand-computed evidence for the Wave60 ROI workflow."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np

from ee_float64_graph_reference import evaluate_float64_graph
from ee_random_split_parity import JAVASCRIPT, semantic_wire
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-roi-geometry-wave60-v1.json"
PYTHON_EXAMPLE = ROOT / "examples/65_GEE_python_roi_geometry.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/19_研究区叠加与排除.js"
OPERATIONS = (
    "contains", "containedIn", "disjoint", "intersects",
    "intersection", "union", "difference", "symmetricDifference",
)
OVERLAYS = ("intersection", "union", "difference", "symmetricDifference")
REGIONS = ("study", *OVERLAYS)


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def load_example():
    spec = importlib.util.spec_from_file_location("roi_geometry_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def json_wire(value):
    return json.loads(json.dumps(value, ensure_ascii=False))


def semantic(value):
    return semantic_wire(json_wire(value))


def local_sources(fixture):
    collection = fixture["stac"]["collection"]
    return [collection], {collection["id"]: [scene["item"] for scene in fixture["scenes"]]}


def python_expressions(fixture):
    example = load_example()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        overlay = example.build_geometry_workflow(ee, fixture)
        expressions = {
            "geometry": {name: ee.serializer.encode(value, for_cloud_api=False)
                         for name, value in overlay["geometry"].items()},
            "feature": {name: ee.serializer.encode(value, for_cloud_api=False)
                        for name, value in overlay["feature"].items()},
            "boundary": {name: ee.serializer.encode(value, for_cloud_api=False)
                         for name, value in overlay["boundary"].items()},
            "feature_overlays": ee.serializer.encode(
                overlay["feature_overlays"], for_cloud_api=False,
            ),
            "images": {},
        }
        for scene in fixture["scenes"]:
            image = example.scene_image(
                ee, fixture, overlay["regions"]["study"], scene["id"],
            )
            outputs = example.build_image_workflow(ee, image, overlay["regions"])
            expressions["images"][scene["id"]] = {
                name: ee.serializer.encode(value, for_cloud_api=False)
                for name, value in outputs.items()
            }
    assert guard.evidence()["attempt_count"] == 0
    return json_wire(expressions)


def javascript_expressions(fixture):
    node = shutil.which("node")
    assert node is not None, "Node is required for pinned JavaScript SDK parity"
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const example = require('./examples/javascript/19_研究区叠加与排除.js');
const values = example.buildWorkflow(ee, fixture);
function encodeMap(source) {
  return Object.fromEntries(Object.entries(source).map(([name, value]) =>
    [name, ee.Serializer.encode(value)]));
}
const expressions = {
  geometry: encodeMap(values.geometry),
  feature: encodeMap(values.feature),
  boundary: encodeMap(values.boundary),
  feature_overlays: ee.Serializer.encode(values.feature_overlays),
  images: Object.fromEntries(Object.entries(values.images).map(([scene, outputs]) =>
    [scene, encodeMap(outputs)]))
};
if (attempts !== 0) throw Error(`SDK attempted networking ${attempts} times`);
process.stdout.write(JSON.stringify({expressions, attempts}));
"""
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT,
        input=json.dumps(fixture, ensure_ascii=False), capture_output=True,
        text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    return decoded["expressions"]


def compile_outputs(expressions, fixture):
    catalog, items = local_sources(fixture)
    return {
        "geometry": {name: compile_expression(value, catalog, items)
                     for name, value in expressions["geometry"].items()},
        "feature": {name: compile_expression(value, catalog, items)
                    for name, value in expressions["feature"].items()},
        "boundary": {name: compile_expression(value, catalog, items)
                     for name, value in expressions["boundary"].items()},
        "feature_overlays": compile_expression(
            expressions["feature_overlays"], catalog, items,
        ),
        "images": {
            scene_id: {name: compile_expression(value, catalog, items)
                       for name, value in outputs.items()}
            for scene_id, outputs in expressions["images"].items()
        },
    }


def numpy_arrays(scene):
    return {
        name: np.asarray(
            [np.nan if value is None else value for value in values],
            dtype=np.float64,
        )
        for name, values in scene["arrays"].items()
    }


def independent_ndvi(scene, selected_indices):
    """Use only raw band values and the fixture's hand-listed center indices."""
    arrays = numpy_arrays(scene)
    red, nir = arrays["B04"], arrays["B08"]
    valid = np.isfinite(red) & np.isfinite(nir)
    selected = np.zeros(len(red), dtype=bool)
    selected[selected_indices] = True
    expected = np.full(len(red), np.nan, dtype=np.float64)
    np.divide(nir - red, nir + red, out=expected, where=valid & selected)
    return expected, valid & selected


def evaluate_image(graph, scene, fixture):
    arrays = numpy_arrays(scene)
    actual, names, timed = evaluate_float64_graph(
        graph, {scene["id"]: arrays},
        grid=np.asarray(fixture["grid"]["pixel_centers"], dtype=np.float64),
        source_geometries={scene["id"]: scene["item"]["geometry"]},
    )
    return actual[0] if not timed else actual[0, 0], names, timed


def root_invocation(encoded):
    scope = dict(encoded.get("scope", []))

    def resolve(value):
        if isinstance(value, dict) and value.get("type") == "ValueRef":
            return resolve(scope[value["value"]])
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if isinstance(value, dict):
            return {key: resolve(item) for key, item in value.items()}
        return value

    root = resolve(encoded["value"])
    assert root["type"] == "Invocation"
    return root


def baseline_expressions(ee, baseline):
    fixture = baseline["source_fixture"]
    left = fixture["left"]["coordinates"][0]
    right = fixture["right"]["coordinates"][0]
    projection = ee.Projection(fixture["projection"])

    def rectangle(ring):
        xs, ys = [point[0] for point in ring], [point[1] for point in ring]
        return ee.Geometry.Rectangle(
            [min(xs), min(ys), max(xs), max(ys)],
            proj=projection, geodesic=False,
        )

    left_geometry, right_geometry = rectangle(left), rectangle(right)
    left_feature = ee.Feature(left_geometry, fixture["geometry_properties"])
    right_feature = ee.Feature(right_geometry, fixture["right_properties"])
    output = {"geometry": {}, "feature": {}}
    for side, first, second in (
        ("geometry", left_geometry, right_geometry),
        ("feature", left_feature, right_feature),
    ):
        output[side] = {
            name: ee.serializer.encode(getattr(first, name)(second, proj=projection),
                                       for_cloud_api=False)
            for name in OPERATIONS
        }
    return json_wire(output)


def baseline_is_intact():
    path = ROOT / "audit/gee-python-wave60/workflow/before.json"
    if not path.is_file():
        return False
    baseline = json.loads(path.read_text(encoding="utf-8"))
    raw = json.dumps(
        baseline["source_fixture"], sort_keys=True, separators=(",", ":"),
    ).encode()
    assert hashlib.sha256(raw).hexdigest() == baseline["source_fixture_sha256"]
    assert baseline["captured_before_production_changes"] is True
    assert baseline["sdk"]["version"] == "1.7.49"
    assert baseline["offline_guard"]["attempt_count"] == 0
    for side in ("geometry", "feature"):
        assert set(baseline["compile_failures"][side]) == set(OPERATIONS)
        for name in OPERATIONS:
            failure = baseline["compile_failures"][side][name]
            assert failure == {
                "type": "UnsupportedEEError",
                "message": f"Unsupported Earth Engine algorithm: {side.capitalize()}.{name}",
            }
    return True
