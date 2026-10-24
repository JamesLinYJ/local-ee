"""Pinned-SDK composition graphs and independent pixel references."""
from __future__ import annotations

import colorsys
from fractions import Fraction
import importlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np

from ee_float64_graph_reference import evaluate_float64_graph
from ee_random_split_parity import JAVASCRIPT, semantic_wire
from gee.ee_python_client import configure_local_ee
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests/fixtures/ee-spectral-preparation-wave57-v1.json"
PYTHON_EXAMPLE = ROOT / "examples/64_GEE_python_scalar_composition.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/18_颜色组合与定标.js"
WORKFLOW_NAMES = (
    "hsv_value_half_then_rgb",
    "rgb_roundtrip_offset_float_stage_clamp",
)
OUTPUT_BANDS = {name: ["red", "green", "blue"] for name in WORKFLOW_NAMES}


def load_fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def load_example():
    spec = importlib.util.spec_from_file_location(
        "scalar_composition_example", PYTHON_EXAMPLE,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_sources(fixture):
    collection = fixture["stac"]["collection"]
    return [collection], {collection["id"]: [
        scene["item"] for scene in fixture["scenes"]
    ]}


def python_expressions(fixture):
    example = load_example()
    expressions = {}
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert ee.__version__ == "1.7.49"
        for scene in fixture["scenes"]:
            image = example.scene_image(ee, fixture, scene["id"])
            outputs = example.build_workflow(ee, image, fixture)
            expressions[scene["id"]] = {
                name: ee.serializer.encode(value, for_cloud_api=False)
                for name, value in outputs.items()
            }
    assert guard.evidence()["attempt_count"] == 0
    return expressions


def javascript_expressions(fixture):
    node = shutil.which("node")
    assert node is not None, "Node is required for pinned JavaScript SDK parity"
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const example = require('./examples/javascript/18_颜色组合与定标.js');
const expressions = {};
for (const scene of fixture.scenes) {
  const image = example.sceneImage(ee, fixture, scene.id);
  const outputs = example.buildWorkflow(ee, image, fixture);
  expressions[scene.id] = Object.fromEntries(Object.entries(outputs).map(
    ([name, value]) => [name, ee.Serializer.encode(value)]));
}
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


def compile_with_work(expression, catalog, items, monkeypatch):
    compile_module = importlib.import_module("gee.compat.earthengine.compile")
    original = compile_module.Translator
    instances = []

    class CapturingTranslator(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)

    with monkeypatch.context() as patch:
        patch.setattr(compile_module, "Translator", CapturingTranslator)
        compiled = compile_module.compile_expression(expression, catalog, items)
    assert len(instances) == 1
    return compiled, instances[0].steps


def numpy_arrays(scene):
    return {
        name: np.asarray(
            [np.nan if value is None else value for value in values],
            dtype=np.float64,
        )
        for name, values in scene["arrays"].items()
    }


def evaluate_sample_graph(compiled, scene, fixture):
    return evaluate_float64_graph(
        compiled, {scene["id"]: numpy_arrays(scene)},
        grid=np.asarray(fixture["stac"]["grid"]["pixel_centers"], dtype=np.float64),
        source_geometries={scene["id"]: scene["item"]["geometry"]},
    )


def independent_expected(scene):
    arrays = numpy_arrays(scene)
    rgb = (arrays["B04"], arrays["B03"], arrays["B02"])
    valid = np.isfinite(np.vstack(rgb)).all(axis=0)
    half = np.full((3, len(valid)), np.nan, dtype=np.float64)
    calibrated = np.full((3, len(valid)), np.nan, dtype=np.float64)
    offset = Fraction.from_float(0.05)
    low, high = Fraction(0), Fraction.from_float(0.65)

    for pixel in np.flatnonzero(valid):
        source_rgb = tuple(float(channel[pixel]) for channel in rgb)
        hsv = colorsys.rgb_to_hsv(*source_rgb)
        half_value = float(Fraction.from_float(hsv[2]) * Fraction(1, 2))
        half[:, pixel] = colorsys.hsv_to_rgb(hsv[0], hsv[1], half_value)

        roundtrip = colorsys.hsv_to_rgb(*hsv)
        for channel, value in enumerate(roundtrip):
            after_offset = Fraction.from_float(float(value)) + offset
            as_float32 = np.float32(float(after_offset))
            widened = Fraction.from_float(float(as_float32))
            calibrated[channel, pixel] = float(min(high, max(low, widened)))

    return {
        "valid_mask": valid,
        "hsv_value_half_then_rgb": half,
        "rgb_roundtrip_offset_float_stage_clamp": calibrated,
    }


def semantic(value):
    # The pinned Python serializer keeps tuples in memory, while the saved
    # baseline and JavaScript SDK expose the JSON wire form with lists.
    return semantic_wire(json_wire(value))


def json_wire(value):
    """Normalize SDK values to the JSON wire representation."""
    return json.loads(json.dumps(value))
