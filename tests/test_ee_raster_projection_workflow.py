"""Official SDK raster projection DAG against an independent closed form."""
import importlib.util
import json
from pathlib import Path

import numpy as np

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]


def test_synthetic_raster_projection_reconstructs_inputs_with_shared_masks():
    fixture = json.loads((ROOT / "tests/fixtures/ee-raster-projection-v1.json").read_text())
    spec = importlib.util.spec_from_file_location("projection_example",
        ROOT / "examples/11_GEE_python_synthetic_raster_projection.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SYNTHETIC_VERSION == fixture["schema"]
    assert module.TRAINING == fixture["training_observations"]
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["red", "nir"]}}}]
    properties = {"system:index": "scene", "system:time_start": 1000}
    items = {"sentinel-2-l2a": [{"id": "scene", "bbox": [0, 0, 2, 2], "properties": properties}]}
    arrays = {"scene": {band: np.array([np.nan if x is None else x for x in values])
                        for band, values in fixture["raster_bands"].items()}}
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        image = ee.ImageCollection("sentinel-2-l2a").first()
        outputs = module.build_projection(ee, image)
        for name, expression in outputs.items():
            compiled = compile_expression(ee.serializer.encode(expression, for_cloud_api=False), catalog, items)
            values, bands, timed = evaluate_graph(compiled, arrays)
            expected = fixture["independent_reference"][name]
            assert bands == list(expected)
            reference = [[np.nan if value is None else value for value in row] for row in expected.values()]
            np.testing.assert_allclose(values, reference, rtol=2e-14, atol=2e-14, equal_nan=True)
            assert timed is False
            assert compiled["source_item_ids"] == ["scene"]
            assert compiled["properties"] == properties
    assert guard.evidence()["attempt_count"] == 0
