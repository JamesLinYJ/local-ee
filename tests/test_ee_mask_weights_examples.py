"""The published mask examples compile the same real official-client graphs."""
from __future__ import annotations

import json
from pathlib import Path
import runpy
import shutil
import subprocess

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


def test_published_fractional_mask_examples_match_both_official_clients():
    example = runpy.run_path(str(ROOT / "examples/68_GEE_python_mask_weights.py"))
    catalog, items = example["synthetic_catalog"]()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        values = example["build_workflow"](
            ee, ee.Image(ee.ImageCollection("sentinel-2-l2a").first()),
        )
        python_results = {name: compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), catalog, items,
        ) for name, value in values.items()}
    assert guard.evidence()["attempt_count"] == 0

    script = JAVASCRIPT.split("const config = JSON.parse", 1)[0] + """
const example = require('./examples/javascript/22_小数掩膜权重.js');
const values = example.buildWorkflow(ee, ee.Image(ee.ImageCollection('sentinel-2-l2a').first()));
const wires = Object.fromEntries(Object.entries(values).map(([name, image]) =>
  [name, ee.Serializer.encode(image)]));
process.stdout.write(JSON.stringify({wires, attempts}));
"""
    node = shutil.which("node")
    assert node is not None
    completed = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True,
                               text=True, timeout=30, check=True)
    javascript = json.loads(completed.stdout)
    assert javascript["attempts"] == 0
    assert set(javascript["wires"]) == set(python_results)
    for name, wire in javascript["wires"].items():
        result = compile_expression(wire, catalog, items)
        assert result == python_results[name]
        validate(result["process_graph"])
        assert result["kind"] == "image" and not result["has_time_dimension"]
        assert result["source_item_ids"] == ["mask-demo"]
    assert python_results["weights_by_band"]["bands"] == ["red", "nir"]
    assert python_results["selected_weight"]["bands"] == ["nir_weight"]
