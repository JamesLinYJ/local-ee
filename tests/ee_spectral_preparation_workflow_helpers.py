"""Pinned-SDK harness and independent sample-grid references for wave57."""
from __future__ import annotations

from fractions import Fraction
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
FIXTURE_PATH = ROOT / "tests/fixtures/ee-spectral-preparation-wave57-v1.json"
PYTHON_EXAMPLE = ROOT / "examples/62_GEE_python_spectral_preparation.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/16_光谱处理.js"
AUDIT_ROOT = ROOT / "audit/gee-python-wave57/workflow-verified"
COLLECTION_ID = "sentinel-2-l2a"
OUTPUT_BANDS = {
    "rgb_to_hsv": ["hue", "saturation", "value"],
    "rgb_roundtrip": ["red", "green", "blue"],
    "red_lut": ["red_lut"],
    "green_polynomial": ["green_polynomial"],
    "unmixed_fractions": ["unmix_0", "unmix_1", "unmix_2"],
}


def load_example():
    spec = importlib.util.spec_from_file_location(
        "spectral_preparation_example", PYTHON_EXAMPLE,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def local_sources(fixture):
    example = load_example()
    return example.declared_local_data(fixture)


def python_graphs(fixture):
    example = load_example()
    catalog, items = local_sources(fixture)
    compiled, expressions = {}, {}
    with OfflineGuard() as guard:
        ee = make_ee()
        for scene in fixture["scenes"]:
            image = example.scene_image(ee, fixture, scene["id"])
            outputs = example.build_workflow(ee, image, fixture)
            encoded = {
                name: ee.serializer.encode(value, for_cloud_api=False)
                for name, value in outputs.items()
            }
            expressions[scene["id"]] = encoded
            compiled[scene["id"]] = {
                name: compile_expression(expression, catalog, items)
                for name, expression in encoded.items()
            }
    assert guard.evidence()["attempt_count"] == 0
    return compiled, expressions


def _javascript_script():
    prelude = JAVASCRIPT.split("const config =", 1)[0]
    return prelude + r"""
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const example = require('./examples/javascript/16_光谱处理.js');
const expressions = {};
for (const scene of fixture.scenes) {
  const image = example.sceneImage(ee, fixture, scene.id);
  const outputs = example.buildWorkflow(ee, image, fixture);
  expressions[scene.id] = Object.fromEntries(Object.entries(outputs).map(
    ([name, value]) => [name, ee.Serializer.encode(value)]));
}
if (attempts !== 0) throw Error(`SDK swallowed ${attempts} network attempts`);
process.stdout.write(JSON.stringify({expressions, attempts}));
"""


def javascript_graphs(fixture):
    node = shutil.which("node")
    if node is None:
        import pytest
        pytest.skip("Node is required for pinned JavaScript SDK spectral parity")
    process = subprocess.run(
        [node, "-e", _javascript_script()], cwd=ROOT,
        input=json.dumps(fixture, ensure_ascii=False), capture_output=True,
        text=True, timeout=30,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["attempts"] == 0
    catalog, items = local_sources(fixture)
    compiled = {
        scene_id: {
            name: compile_expression(expression, catalog, items)
            for name, expression in outputs.items()
        }
        for scene_id, outputs in result["expressions"].items()
    }
    return compiled, result["expressions"]


def numpy_arrays(scene):
    return {
        name: np.asarray(
            [np.nan if value is None else value for value in values],
            dtype=np.float64,
        )
        for name, values in scene["arrays"].items()
    }


def evaluate_sample_graph(compiled, scene, fixture):
    item = scene["item"]
    return evaluate_float64_graph(
        compiled, {scene["id"]: numpy_arrays(scene)},
        grid=np.asarray(fixture["stac"]["grid"]["pixel_centers"], dtype=np.float64),
        source_geometries={scene["id"]: item["geometry"]},
    )


def _exact(value):
    """Model the binary64 value passed through the pinned SDK wire."""
    return Fraction.from_float(float(value))


def _hsv(red, green, blue):
    maximum, minimum = max(red, green, blue), min(red, green, blue)
    delta = maximum - minimum
    if delta == 0:
        hue = Fraction(0)
    elif maximum == red:
        hue = ((green - blue) / delta) % 6 / 6
    elif maximum == green:
        hue = ((blue - red) / delta + 2) / 6
    else:
        hue = ((red - green) / delta + 4) / 6
    saturation = Fraction(0) if maximum == 0 else delta / maximum
    return hue, saturation, maximum


def _lut(value, xs, ys):
    if value <= xs[0]:
        return ys[0]
    if value >= xs[-1]:
        return ys[-1]
    for index in range(1, len(xs)):
        if value <= xs[index]:
            left, right = index - 1, index
            return ys[left] + (value - xs[left]) * (ys[right] - ys[left]) / (xs[right] - xs[left])
    raise AssertionError("LUT reference did not locate a finite input")


def independent_color_and_calibration(fixture, scene):
    arrays = numpy_arrays(scene)
    red, green, blue = (arrays[name] for name in ("B04", "B03", "B02"))
    pixel_count = len(red)
    outputs = {
        "rgb_to_hsv": np.full((3, pixel_count), np.nan),
        "rgb_roundtrip": np.full((3, pixel_count), np.nan),
        "red_lut": np.full((1, pixel_count), np.nan),
        "green_polynomial": np.full((1, pixel_count), np.nan),
    }
    controls = fixture["calibration"]
    xs = [_exact(value) for value in controls["lut_input"]]
    ys = [_exact(value) for value in controls["lut_output"]]
    coefficients = [_exact(value) for value in controls["polynomial_coefficients_ascending"]]
    for pixel in range(pixel_count):
        channels = [red[pixel], green[pixel], blue[pixel]]
        if not np.isfinite(channels).all():
            continue
        r, g, b = map(_exact, channels)
        hsv = _hsv(r, g, b)
        outputs["rgb_to_hsv"][:, pixel] = [float(value) for value in hsv]
        outputs["rgb_roundtrip"][:, pixel] = channels
        x = _exact(red[pixel])
        outputs["red_lut"][0, pixel] = float(_lut(x, xs, ys))
        x = _exact(green[pixel])
        outputs["green_polynomial"][0, pixel] = float(
            sum(coefficient * x ** degree for degree, coefficient in enumerate(coefficients))
        )
    return outputs


def verify_fraction_fixture(fixture):
    reference = fixture["independent_reference"]
    endmembers = [[Fraction(text) for text in row]
                  for row in reference["endmembers_rational"]]
    assert Fraction(reference["endmember_determinant"]) == Fraction(-3, 10)
    for scene in fixture["scenes"]:
        arrays = numpy_arrays(scene)
        fractions = [[None if value is None else Fraction(value)
                      for value in row]
                     for row in scene["true_fractions"]]
        for pixel, abundance in enumerate(fractions):
            if abundance[0] is None:
                assert all(np.isnan(arrays[band][pixel])
                           for band in fixture["source_band_order"])
                continue
            assert all(value >= 0 for value in abundance)
            assert sum(abundance) == 1
            for band_index, band in enumerate(fixture["source_band_order"]):
                predicted = sum(abundance[k] * endmembers[k][band_index]
                                for k in range(3))
                assert Fraction(str(arrays[band][pixel])) == predicted


def semantic_compiled(compiled):
    return semantic_wire(compiled)
