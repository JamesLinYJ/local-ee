"""Every native output dimension must roundtrip through both pinned SDKs."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_binary import invoke_geometry_binary
from gee.compat.earthengine import spherical_native as native
from gee.compat.earthengine.public_values import public_value
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


def public_geometries(planar=False):
    point = {"type": "Point", "coordinates": [45, 45]}
    line = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    raw = {
        "point": point,
        "points": {"type": "MultiPoint", "coordinates": [[10, 20], [30, 40]]},
        "line": line,
        "polygon": {"type": "Polygon", "coordinates": [
            [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
        ]},
        "mixed": {"type": "GeometryCollection", "geometries": [point, line]},
    }
    empty = {"type": "GeometryCollection", "geometries": []}
    if planar:
        values = {}
        for name, value in raw.items():
            if value["type"] not in {"Point", "MultiPoint"}:
                value = {**value, "geodesic": False}
            values[name] = public_value(invoke_geometry_binary(
                Translator([], {}, {}), "Geometry.union",
                {"left": value, "right": empty, "proj": "EPSG:4326"},
            ))
        return values
    return {name: public_value(native.run("union", value, empty,
                                         output_positions=100, output_children=100))
            for name, value in raw.items()}


@pytest.mark.parametrize("planar", [False, True])
def test_native_output_flags_match_each_pinned_python_constructor(planar):
    values = public_geometries(planar)
    for name in ("point", "points"):
        assert "geodesic" not in values[name] and "evenOdd" not in values[name]
    assert values["line"]["geodesic"] is (not planar) and "evenOdd" not in values["line"]
    assert values["polygon"]["geodesic"] is (not planar)
    if planar:
        assert "evenOdd" not in values["polygon"]
    else:
        assert values["polygon"]["evenOdd"] is False
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path="vendor/earthengine-js/algorithms.json")
        for value in values.values():
            geometry = ee.Geometry(value)
            wire = ee.serializer.encode(geometry, for_cloud_api=False)
            assert compile_expression(wire, [], {})["value"] == value
    assert guard.evidence()["attempt_count"] == 0


@pytest.mark.parametrize("planar", [False, True])
def test_native_output_dimensions_roundtrip_through_pinned_javascript_sdk(planar):
    values = public_geometries(planar)
    prefix = JAVASCRIPT.split("const config = JSON.parse", 1)[0]
    script = prefix + """
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const outputs = Object.fromEntries(Object.entries(input).map(([name, value]) =>
  [name, ee.Serializer.encode(ee.Geometry(value))]));
process.stdout.write(JSON.stringify({outputs, attempts}));
"""
    node = shutil.which("node")
    assert node is not None
    result = subprocess.run([node, "-e", script], input=json.dumps(values),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    decoded = json.loads(result.stdout)
    assert decoded["attempts"] == 0
    for name, wire in decoded["outputs"].items():
        assert compile_expression(wire, [], {})["value"] == values[name]
