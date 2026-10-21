"""Official SDK -> nearest neighbors -> pixel graph with independent controls."""
import importlib.util
import json
from pathlib import Path

import numpy as np

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]


def test_versioned_nearest_neighbor_interpolation_preserves_sources_and_masks():
    fixture = json.loads((ROOT / "tests/fixtures/ee-temporal-interpolation-v1.json").read_text())
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    items = [{"id": row["id"], "bbox": [0, 0, 2, 2], "geometry": geometry,
              "properties": {"system:index": row["id"], "role": row["role"],
                  "system:time_start": fixture["base_millis"] + row["day"] * fixture["day_millis"]}}
             for row in fixture["rows"]]
    metadata = [{"id": "sentinel-2-l2a", "cube:dimensions": {"bands": {"values": ["signal"]}}}]
    spec = importlib.util.spec_from_file_location(
        "temporal_example", ROOT / "examples/09_GEE_python_temporal_interpolation.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        source = ee.ImageCollection("sentinel-2-l2a")
        expression = module.build_interpolation(
            ee, source.filter(ee.Filter.eq("role", "target")),
            source.filter(ee.Filter.eq("role", "observation")),
            fixture["window_days"] * fixture["day_millis"]).first()
        compiled = compile_expression(ee.serializer.encode(expression, for_cloud_api=False),
                                      metadata, {"sentinel-2-l2a": items})
        timestamp = compile_expression(ee.serializer.encode(
            expression.get("system:time_start"), for_cloud_api=False),
            metadata, {"sentinel-2-l2a": items})["value"]
    expected = fixture["independent_reference"]
    assert set(compiled["source_item_ids"]) == {expected["previous"], expected["following"]}
    arrays = {row["id"]: {"signal": np.array([np.nan if x is None else x for x in row["signal"]])}
              for row in fixture["rows"]}
    values, bands, timed = evaluate_graph(compiled, arrays)
    assert bands == ["interpolated"] and timed is False
    expected_pixels = [np.nan if value is None else value for value in expected["signal"]]
    np.testing.assert_allclose(values, [expected_pixels], equal_nan=True)
    assert timestamp == fixture["base_millis"] + 2 * fixture["day_millis"]
    # This hand reference requires BOTH selected neighbors to be valid. A
    # farther observation and the target's own 100-valued pixels cannot fill it.
    assert guard.evidence()["attempt_count"] == 0
