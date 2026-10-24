"""Different-source empty accumulators keep first support without its pixels.

This is a synthetic process-graph numerical reference, not Spark rasterization.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs
from ee_float64_graph_reference import evaluate_float64_graph
from test_ee_translate import evaluate_graph


def rectangle(west, east):
    return {"type": "Polygon", "coordinates": [[
        [west, 0], [east, 0], [east, 2], [west, 2], [west, 0],
    ]]}


@pytest.mark.parametrize("clip,expected", [
    (None, [11.25, -2.0, np.nan, np.nan]),
    ((0, 3), [11.25, -2.0, np.nan, np.nan]),
    ((1, 4), [np.nan, -2.0, np.nan, np.nan]),
])
@pytest.mark.parametrize("operation", ["identity", "constant_sum", "metadata_sum"])
def test_dropped_first_scene_keeps_only_its_effective_footprint(clip, expected, operation):
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path="vendor/earthengine-js/algorithms.json",
        )
        catalog, original, _ = synthetic_inputs()
        items = deepcopy(original)
        rows = items["sentinel-2-l2a"]
        for item in rows:
            east = 2 if item["id"] == "scene-a" else 4
            item["bbox"] = [0, 0, east, 2]
            item["geometry"] = rectangle(0, east)
        first = ee.Image("scene-a").select([]).set({"title": "first", "metric": 123.5})
        if clip is not None:
            first = first.clip({**rectangle(*clip), "geodesic": False})
        donor = ee.Image("scene-b").select("red").set("title", "donor")
        value = first.addBands(donor)
        if operation == "constant_sum":
            value = value.addBands(ee.Image(7).rename("k")).select("k").toDouble()
            value = value.add(donor.toDouble()).rename("red")
            expected = [x + 7 if np.isfinite(x) else x for x in expected]
        elif operation == "metadata_sum":
            value = value.metadata("metric").toDouble().add(donor.toDouble()).rename("red")
            expected = [x + 123.5 if np.isfinite(x) else x for x in expected]
        wire = ee.serializer.encode(value, for_cloud_api=False)
        result = compile_expression(wire, [catalog], items)
        # No source-a pixel array is supplied: any hidden read of a discarded
        # first band would fail, even if its numeric values happened to agree.
        arrays = {"scene-b": {"red": np.array([11.25, -2.0, 39.5, 40.125])}}
        centers = [[0.5, 1.5], [1.5, 1.5], [2.5, 1.5], [3.5, 1.5]]
        evaluate = evaluate_graph if operation == "identity" else evaluate_float64_graph
        actual, names, timed = evaluate(result, arrays, grid=centers)
        assert names == ["red"] and timed is False
        # Rectangle intersections are derived independently by interval tests;
        # no production footprint helper or GEOS intersection computes these.
        np.testing.assert_allclose(actual, [expected], rtol=0, atol=0, equal_nan=True)
        assert result["source_item_ids"] == ["scene-b"]
        assert result["properties"]["title"] == "first"
        assert result["properties"]["system:index"] == "scene-a"
    assert guard.evidence()["attempt_count"] == 0
