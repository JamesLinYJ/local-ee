"""Pinned Python and JavaScript SDK wires for geometry measurements."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
import subprocess

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-geometry-measures-wave71-v1.json"
METHODS = ("area", "length", "perimeter", "centroid")
OWNERS = ("Geometry", "Feature")
MODES = ("omitted", "explicit_null", "explicit_epsg4326")


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _python_outputs(fixture):
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2",
            "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        projection = ee.Projection("EPSG:4326")
        outputs = {}
        for name, case in fixture["cases"].items():
            geometry_json = case["geometry"]
            geometry = ee.Geometry(geometry_json)
            feature = ee.Feature({
                "type": "Feature",
                "id": f"wave71-{name}",
                "properties": {"label": name, "source_rank": len(outputs)},
                "geometry": geometry_json,
            })
            for owner, value in (("Geometry", geometry), ("Feature", feature)):
                for method in METHODS:
                    for mode in MODES:
                        if mode == "omitted":
                            expression = getattr(value, method)()
                        elif mode == "explicit_null":
                            expression = getattr(value, method)(
                                maxError=None, proj=None,
                            )
                        else:
                            expression = getattr(value, method)(proj=projection)
                        outputs[(owner, name, method, mode)] = json.loads(json.dumps(
                            ee.serializer.encode(expression, for_cloud_api=False)
                        ))
        assert guard.evidence()["attempt_count"] == 0
    return outputs


def _javascript_outputs(fixture):
    node = shutil.which("node")
    assert node is not None, "Node is required for the pinned JavaScript SDK wire check"
    setup = JAVASCRIPT.split("const config = JSON.parse", 1)[0]
    script = setup + r"""
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const projection = ee.Projection('EPSG:4326');
const outputs = [];
for (const [name, item] of Object.entries(fixture.cases)) {
  const geometry = ee.Geometry(item.geometry);
  const feature = ee.Feature({
    type: 'Feature', id: `wave71-${name}`,
    properties: {label: name, source_rank: outputs.length},
    geometry: item.geometry
  });
  for (const [owner, value] of [['Geometry', geometry], ['Feature', feature]]) {
    for (const method of ['area', 'length', 'perimeter', 'centroid']) {
      for (const [mode, args] of [
        ['omitted', []], ['explicit_null', [null, null]],
        ['explicit_epsg4326', [null, projection]]
      ]) {
        outputs.push({owner, name, method, mode,
          wire: ee.Serializer.encode(value[method](...args))});
      }
    }
  }
}
if (attempts !== 0) throw Error(`SDK attempted ${attempts} network calls`);
process.stdout.write(JSON.stringify({outputs, attempts}));
"""
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT, input=json.dumps(fixture),
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    return {
        (row["owner"], row["name"], row["method"], row["mode"]): row["wire"]
        for row in decoded["outputs"]
    }


def _expand_wire(value, scope=None):
    """Resolve SDK CompoundValue references into an ordinary invocation tree."""
    scope = {} if scope is None else scope
    if isinstance(value, list):
        return [_expand_wire(child, scope) for child in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") == "CompoundValue":
        scope.update(value.get("scope", []))
        return _expand_wire(value["value"], scope)
    if value.get("type") == "ValueRef":
        return _expand_wire(scope[value["value"]], scope)
    if value.get("type") == "Invocation":
        arguments = {
            key: _expand_wire(item, scope)
            for key, item in value.get("arguments", {}).items()
        }
        # The Python SDK drops optional nulls while JS preserves explicitly
        # supplied nulls in its wire. Both mean "use the documented default".
        arguments = {
            key: item for key, item in arguments.items()
            if not (key in {"maxError", "proj"} and item is None)
        }
        return {
            "type": "Invocation",
            "functionName": value["functionName"],
            "arguments": arguments,
        }
    return {key: _expand_wire(item, scope) for key, item in value.items()}


def test_sdk_inventory_uses_the_complete_pinned_geometry_measure_signatures():
    fixture = _fixture()
    import ee

    assert ee.__version__ == fixture["official_api"]["python_sdk"].split()[-1]
    lock_path = ROOT / "vendor/earthengine-js/upstream-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock["version"] == fixture["official_api"]["javascript_sdk"].split()[-1]
    assert lock["source_commit"] == fixture["official_api"]["source_commit"]
    bundle_hash = hashlib.sha256(
        (ROOT / "vendor/earthengine-js/earthengine.cjs").read_bytes()
    ).hexdigest()
    algorithm_hash = hashlib.sha256(
        (ROOT / "vendor/earthengine-js/algorithms.json").read_bytes()
    ).hexdigest()
    assert bundle_hash == fixture["official_api"]["javascript_bundle_sha256"]
    assert bundle_hash == lock["files"]["earthengine.cjs"]
    assert algorithm_hash == fixture["official_api"]["pinned_algorithm_sha256"]
    assert algorithm_hash == lock["files"]["algorithms.json"]
    pinned = json.loads((ROOT / "vendor/earthengine-js/algorithms.json").read_text())
    algorithms = {item["name"]: item for item in pinned["algorithms"]}
    for owner in OWNERS:
        for method in METHODS:
            record = algorithms[f"algorithms/{owner}.{method}"]
            args = record["arguments"]
            assert record["returnType"] == ("Geometry" if method == "centroid" and owner == "Geometry"
                                              else "Feature" if method == "centroid"
                                              else "Float")
            assert [argument["argumentName"] for argument in args] == [
                "geometry" if owner == "Geometry" else "feature",
                "maxError", "proj",
            ]
            assert args[1]["optional"] and args[1]["defaultValue"] is None
            assert args[2]["optional"] and args[2]["defaultValue"] is None
            assert record["description"].strip()
    assert fixture["official_api"]["source_commit"] == "e189e4b89e785019ea5642ea8e80cb644749cd4a"


def test_python_and_javascript_sdk_wires_match_for_all_methods_and_projection_forms():
    fixture = _fixture()
    python = _python_outputs(fixture)
    javascript = _javascript_outputs(fixture)
    assert set(python) == set(javascript)
    for key in sorted(python):
        assert _expand_wire(python[key]) == _expand_wire(javascript[key]), key
        expanded = _expand_wire(python[key])
        assert expanded["functionName"] == f"{key[0]}.{key[2]}"
        assert key[0].lower() in expanded["arguments"]
    # The explicit Projection invocation is present only for the projected
    # case; omitted and null projections both retain the pinned API default.
    projected = _expand_wire(python[("Geometry", "octant_triangle", "area", "explicit_epsg4326")])
    assert projected["arguments"]["proj"]["functionName"] == "Projection"
    default = _expand_wire(python[("Geometry", "octant_triangle", "area", "omitted")])
    assert "proj" not in default["arguments"]
    assert "maxError" not in default["arguments"]
