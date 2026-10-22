"""Coupled observation rankings checked against independent rational rows."""
from fractions import Fraction
from datetime import datetime
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import Point, shape

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


ROOT = Path(__file__).resolve().parents[1]


def inputs():
    data = json.loads((ROOT / "tests/fixtures/ee-quality-sorted-observations-v1.json").read_text())
    items, arrays = [], {}
    for frame in data["frames"]:
        items.append({
            "id": frame["id"], "geometry": data["scene_geometry"], "bbox": data["bbox"],
            "properties": {"datetime": frame["time"], "system:index": frame["id"],
                           "system:time_start": int(datetime.fromisoformat(
                               frame["time"].replace("Z", "+00:00")).timestamp() * 1000)},
        })
        arrays[frame["id"]] = {
            band: np.asarray([np.nan if value is None else value for value in frame[band]])
            for band in data["bands"]
        }
    local = {
        "catalog": [{"id": data["collection_id"], "cube:dimensions": {
            "bands": {"values": data["bands"]},
        }}],
        "items": {data["collection_id"]: items}, "arrays": arrays,
        "grid": np.asarray(data["pixel_centers"]),
        "geometries": {frame["id"]: data["scene_geometry"] for frame in data["frames"]},
    }
    return data, local


def example():
    path = ROOT / "examples/25_GEE_python_quality_sorted_observations.py"
    spec = importlib.util.spec_from_file_location("quality_sorted_observations", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def independent_reference(data):
    ordered = np.full((8, len(data["pixel_centers"])), np.nan)
    best_mean = np.full((1, len(data["pixel_centers"])), np.nan)
    geometry = shape(data["scene_geometry"])
    identities = []
    for sample, point in enumerate(data["pixel_centers"]):
        if (not geometry.covers(Point(point)) or any(
                frame[band][sample] is None
                for frame in data["frames"] for band in data["bands"])):
            identities.append(None)
            continue
        rows = []
        for frame in data["frames"]:
            red, nir = Fraction(frame["red"][sample]), Fraction(frame["nir"][sample])
            rows.append((Fraction(frame["cloud_score"][sample]),
                         frame["id"], (nir - red) / (nir + red), frame["day"]))
        rows.sort(key=lambda row: row[0])
        identities.append([row[1] for row in rows])
        ordered[:, sample] = [float(value) for row in rows for value in row[2:]]
        mean = sum((row[2] for row in rows[:2]), Fraction(0)) / 2
        assert str(mean) == data["hand_reference"]["best_mean_by_pixel"][sample]
        best_mean[0, sample] = float(mean)
    assert identities == data["hand_reference"]["sorted_scene_ids_by_pixel"]
    return {"ordered": ordered, "best_two": ordered[:4], "best_mean": best_mean}


def run_workflow():
    data, local = inputs()
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        module = example()
        assert module.SYNTHETIC_VERSION == data["schema"]
        outputs = module.build_outputs()
        references = independent_reference(data)
        evidence = {}
        for name, output in outputs.items():
            if name != "best_mean":
                count = 4 if name == "ordered" else 2
                output = output.arrayFlatten([[f"rank_{i}" for i in range(count)], ["ndvi", "day"]])
            encoded = ee.serializer.encode(output, for_cloud_api=False)
            compiled = compile_expression(encoded, local["catalog"], local["items"])
            validate(compiled["process_graph"])
            actual, names, timed = evaluate_graph(compiled, local["arrays"], grid=local["grid"],
                                                 source_geometries=local["geometries"])
            assert not timed
            expected = references[name]
            np.testing.assert_allclose(actual, expected, rtol=2e-6, atol=2e-6, equal_nan=True)
            assert compiled["source_item_ids"] == [frame["id"] for frame in data["frames"]]
            assert np.isnan(actual[:, 2:]).all()
            valid = np.isfinite(expected)
            evidence[name] = {
                "nodes": len(compiled["process_graph"]), "bands": names,
                "max_abs_error": float(np.max(np.abs(actual[valid] - expected[valid]))),
                "mask_mismatches": int(np.count_nonzero(np.isfinite(actual) != valid)),
                "sample_values": [[None if not np.isfinite(value) else float(value) for value in row] for row in actual],
            }
        assert guard.evidence()["attempt_count"] == 0
    return {"schema": data["schema"], "network": guard.evidence(), "outputs": evidence}


def test_versioned_quality_ranking_preserves_pairs_ties_dates_and_masks():
    run_workflow()
