"""Actual SDK composition for native math graphs and finite static QA helpers."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "qa_bits": [1, 0, 4, 0], "qa_count": [1, 0, 1, 0], "dot": 25,
    "identity": [[1, 0], [0, 1]], "padded": [1, 2, -1, -1], "qa_value": 4,
}
# Use the existing accepted catalog ID for this versioned synthetic metadata;
# this test does not grant a new physical dataset an EE acceptance alias.
CATALOG = [{"id": "sentinel-2-l2a", "cube:dimensions": {
    "bands": {"values": ["cosine", "sine"]}}}]
ITEMS = {"sentinel-2-l2a": [{
    "id": "numeric-coeff", "bbox": [0, 0, 1, 1],
    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
    "properties": {"system:index": "numeric-coeff", "system:time_start": 1000},
}]}


def python_outputs():
    spec = importlib.util.spec_from_file_location(
        "pixel_numeric_example", ROOT / "examples/39_GEE_python_pixel_math.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        values = module.build_workflow(ee, ee.Image("numeric-coeff"))
        results = {key: compile_expression(ee.serializer.encode(value, for_cloud_api=False),
                                          CATALOG, ITEMS) for key, value in values.items()}
    assert guard.evidence()["attempt_count"] == 0
    return results


def test_numeric_example_static_results_and_actual_native_process_graphs():
    outputs = python_outputs()
    for name, expected in EXPECTED.items():
        assert outputs[name]["kind"] == "value"
        assert outputs[name]["value"] == expected
    expected_math = {"phase": {"atan2"}, "phase_turn": {"atan2"},
                     "phase_and_gamma": {"atan2", "gamma"}, "bounded_asin": {"asin"}}
    for name, operations in expected_math.items():
        output = outputs[name]
        validate(output["process_graph"])
        actual = {node["arguments"]["operation"] for node in output["process_graph"].values()
                  if node["process_id"] == "local_ee_pixel_math"}
        assert actual == operations
        assert output["source_item_ids"] == ["numeric-coeff"]
    assert outputs["phase_and_gamma"]["bands"] == ["phase", "gamma_one"]


def test_python_and_javascript_clients_share_all_ten_numeric_workflow_outputs():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for pinned JavaScript serialization")
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const image = ee.Image('numeric-coeff').toFloat();
const cosine = image.select('cosine');
const sine = image.select('sine');
const phase = cosine.atan2(sine).rename('phase');
const qa = ee.Array([1,2,4,8]).bitwiseAnd(ee.Array([5,5,5,5]));
const values = {phase, phase_turn:phase.unitScale(-Math.PI,Math.PI).rename('phase_turn'),
 phase_and_gamma:phase.addBands(ee.Image.constant(1).gamma().rename('gamma_one')),
 bounded_asin:sine.clamp(-1,1).asin().rename('bounded_asin'),
 qa_bits:qa, qa_count:qa.bitCount(), dot:ee.Array([3,4]).dotProduct(ee.Array([3,4])),
 identity:ee.Array.identity(2), padded:ee.Array([1,2]).pad([4],-1),
 qa_value:ee.Number.parse('101',2).bitwise_and(4)};
console.log(JSON.stringify({attempts, outputs:Object.fromEntries(
 Object.entries(values).map(([key,value])=>[key,ee.Serializer.encode(value)]))}));
"""
    completed = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True,
                               text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    results = json.loads(completed.stdout)
    assert results["attempts"] == 0
    expected = python_outputs()
    assert set(results["outputs"]) == set(expected)
    for name, expression in results["outputs"].items():
        assert compile_expression(expression, CATALOG, ITEMS) == expected[name]


def test_math_image_receiver_preserves_metadata_map_detection():
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        mapped = ee.ImageCollection("sentinel-2-l2a").map(
            lambda image: image.select("cosine").atan().set(
                "stamp", image.select("sine").erf().date().millis()))
        value = mapped.aggregate_array("stamp")
        result = compile_expression(ee.serializer.encode(value, for_cloud_api=False), CATALOG, ITEMS)
    assert guard.evidence()["attempt_count"] == 0
    assert result["kind"] == "value"
    assert result["value"] == [1000]


def test_legacy_identity_map_does_not_charge_a_math_scan_for_4000_items():
    # Within the existing ingestion cap. A no-op compact map does not need
    # per-item math binding and must retain its prior compilation budget.
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {
        "bands": {"values": ["blue", "green", "red", "nir", "SCL"]}}}]
    items = {"sentinel-2-l2a": [{"id": f"item-{index}", "properties": {}}
                               for index in range(4000)]}
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        mapped = ee.ImageCollection("sentinel-2-l2a").map(lambda image: image)
        expression = ee.serializer.encode(mapped.size(), for_cloud_api=False)
        result = compile_expression(expression, catalog, items)
    assert guard.evidence()["attempt_count"] == 0
    assert result["value"] == 4000


def test_unrelated_math_hint_does_not_charge_full_source_ids_for_identity_map():
    from gee.compat.earthengine.decoder import Translator
    from gee.compat.earthengine.ir import Image, Pixel, Source
    from gee.compat.earthengine.pixel_math_graph import requires_per_item_pixel_math

    translator = Translator([], {}, {})
    translator._pixel_math_seen = True
    source = Source("sentinel-2-l2a", tuple(f"item-{index}" for index in range(4000)),
                    ("blue", "green", "red", "nir", "SCL"))
    image = Image([(name, Pixel("band", (source, name))) for name in source.names], {}, source)
    assert requires_per_item_pixel_math(image, translator) is False
    assert translator.steps < 100
