"""Two official SDKs, missing QA masks, and independently specified pixels."""
from __future__ import annotations

from copy import deepcopy
import json

import numpy as np
import pytest

from ee_collection_link_workflow import (
    example, fixture, javascript_graphs, make_ee, python_graphs, sample_arrays,
    semantic_compiled,
)
from ee_float64_graph_reference import evaluate_float64_graph
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


EXPECTED = {
    "linked_a": (["red", "nir", "qa"], [[1, 2, None, 4], [2, 6, 5, 8], [0, 80, None, 10]]),
    "linked_b": (["red", "nir", "qa"], [[2, 3, 4, 5], [6, 9, 8, None], [None] * 4]),
    "linked_c": (["red", "nir", "qa"], [[4, 2, 1, 3], [8, 8, 3, 9], [90, 0, 10, None]]),
    "custom_key_a": (["red", "nir", "qa"], [[1, 2, None, 4], [2, 6, 5, 8], [0, 80, None, 10]]),
    "clear_a": (["red", "nir"], [[1, None, None, 4], [2, None, None, 8]]),
    "keep_a": (["red", "nir", "nir_1", "qa"], [
        [1, 2, None, 4], [2, 6, 5, 8], [20, 60, 50, 80], [0, 80, None, 10],
    ]),
    "overwrite_a": (["red", "nir", "qa"], [
        [1, 2, None, 4], [20, 60, 50, 80], [0, 80, None, 10],
    ]),
}


def assert_sample_outputs(outputs, data):
    arrays = sample_arrays(data)
    geometries = {scene["id"]: scene["item"]["geometry"] for scene in data["scenes"]}
    evidence = {}
    for key, (names, values) in EXPECTED.items():
        compiled = outputs[key]
        actual, actual_names, timed = evaluate_float64_graph(
            compiled, arrays, grid=np.asarray(data["grid"]["centers"]),
            source_geometries=geometries,
        )
        if timed:
            assert actual.shape[0] == 1
            actual = actual[0]
        expected = np.asarray([
            [np.nan if value is None else value for value in row] for row in values
        ])
        assert actual_names == names == compiled["bands"]
        np.testing.assert_allclose(actual, expected, rtol=0, atol=0, equal_nan=True)
        evidence[key] = {"bands": names, "cells": int(expected.size),
                         "finite_cells": int(np.isfinite(expected).sum()),
                         "masked_cells": int(np.isnan(expected).sum()),
                         "max_absolute_error": 0}
    return evidence


def test_python_and_javascript_workflows_have_identical_local_graphs_and_pixels():
    data = fixture()
    python, python_wire = python_graphs(data)
    javascript, javascript_wire = javascript_graphs(data)
    assert set(python) == set(javascript) == set(EXPECTED) | {
        "linked_collection", "keep_collection", "version_a", "version_b",
        "primary_index_after_link", "primary_actual_id_after_link",
    }
    assert semantic_compiled(python) == semantic_compiled(javascript)
    assert_sample_outputs(python, data)
    assert_sample_outputs(javascript, data)
    assert python["version_a"]["value"] == {"major": 1, "tags": ["synthetic"]}
    assert python["version_b"]["value"] is None
    assert python["primary_index_after_link"]["value"] == "a"
    assert python["primary_actual_id_after_link"]["value"] == "p-a"
    assert set(python["linked_a"]["source_item_ids"]) == {"p-a", "q-a"}
    assert set(python["linked_b"]["source_item_ids"]) == {"p-b"}
    # Existing collection summaries expose EE indexes; actual raster load IDs
    # and Image.id are checked separately above.
    for key, expected_ids in (("linked_collection", ["a", "b", "c"]),
                              ("keep_collection", ["a", "c"])):
        output = python[key]
        assert output["source_item_ids"] == expected_ids
        assert len(output["features"]) == len(expected_ids)
        assert all(row["properties"]["side"] == "primary" for row in output["features"])
    assert all("qa_version" not in row["properties"]
               for row in python["keep_collection"]["features"])
    # Both helper implementations must actually emit the new pinned algorithm.
    assert "Image.linkCollection" in json.dumps(python_wire)
    assert "ImageCollection.combine" in json.dumps(javascript_wire)
    assert all(len(value.get("process_graph", {})) <= 500 for value in python.values())


@pytest.mark.parametrize("mutation", ["time", "asset_grid", "item_grid", "footprint"])
def test_link_and_combine_reject_incompatible_actual_source_metadata(mutation):
    data = fixture()
    target = next(scene for scene in data["scenes"] if scene["id"] == "q-a")["item"]
    if mutation == "time":
        target["properties"]["system:time_start"] += 1
    elif mutation == "asset_grid":
        target["assets"]["qa"]["proj:transform"][2] += .5
    elif mutation == "item_grid":
        target["properties"]["proj:transform"][2] += .5
    else:
        target["geometry"]["coordinates"][0][1][0] -= .5
    catalog, items = example().declared_local_data(data)
    with OfflineGuard():
        ee = make_ee()
        values = example().build_workflow(ee, data)
        for key in ("linked_a", "keep_a", "overwrite_a"):
            expression = ee.serializer.encode(values[key], for_cloud_api=False)
            with pytest.raises(UnsupportedEEError):
                compile_expression(expression, catalog, items)


def test_same_expression_rechecks_catalog_mutation_in_a_fresh_compile():
    data = fixture()
    with OfflineGuard():
        ee = make_ee()
        expression = ee.serializer.encode(
            example().build_workflow(ee, data)["linked_a"], for_cloud_api=False,
        )
    catalog, items = example().declared_local_data(data)
    assert compile_expression(expression, catalog, items)["bands"] == ["red", "nir", "qa"]
    altered = deepcopy(items)
    altered["sentinel-2-l2a"][3]["assets"]["qa"]["proj:transform"][2] += .25
    with pytest.raises(UnsupportedEEError):
        compile_expression(expression, catalog, altered)


def test_unaccepted_datasets_remain_rejected_before_link_compilation():
    data = fixture()
    catalog = [{**deepcopy(data["catalog"][0]), "id": cid}
               for cid in ("local-primary-v1", "local-quality-v1")]
    items = {
        "local-primary-v1": [scene["item"] for scene in data["scenes"]
                             if scene["item"]["properties"]["side"] == "primary"],
        "local-quality-v1": [scene["item"] for scene in data["scenes"]
                             if scene["item"]["properties"]["side"] == "qa"],
    }
    with OfflineGuard():
        ee = make_ee()
        primary = ee.ImageCollection("local-primary-v1").select(["red", "nir"])
        quality = ee.ImageCollection("local-quality-v1")
        values = {
            "linked_a": primary.linkCollection(quality, "qa", "qa_version").first(),
            "keep_a": primary.combine(quality.select(["nir", "qa"])).first(),
            "overwrite_a": primary.combine(quality.select(["nir", "qa"]), True).first(),
        }
        for value in values.values():
            with pytest.raises(UnsupportedEEError, match="compatibility acceptance"):
                compile_expression(
                    ee.serializer.encode(value, for_cloud_api=False), catalog, items,
                )


@pytest.mark.parametrize("hidden_mismatch", ["time", "footprint"])
def test_actual_selected_band_lineage_cannot_hide_behind_a_valid_image_wrapper(hidden_mismatch):
    data = fixture()
    hidden = next(scene["item"] for scene in data["scenes"] if scene["id"] == "q-c")
    if hidden_mismatch == "footprint":
        hidden["properties"]["system:time_start"] = 1704067200000
        hidden["properties"]["datetime"] = "2024-01-01T00:00:00Z"
        hidden["geometry"]["coordinates"][0][1][0] -= .5
    catalog, items = example().declared_local_data(data)
    with OfflineGuard():
        ee = make_ee()
        primary = ee.ImageCollection("sentinel-2-l2a").filter(
            ee.Filter.eq("side", "primary"),
        ).select(["red", "nir"])
        mixed = ee.Image("q-a").select("nir").addBands(ee.Image("q-c").select("qa"))
        secondary = ee.ImageCollection.fromImages([mixed])
        values = [
            ee.Image(primary.first()).linkCollection(secondary, "qa"),
            primary.combine(secondary).first(),
        ]
        for value in values:
            with pytest.raises(UnsupportedEEError, match="timestamp|footprint"):
                compile_expression(
                    ee.serializer.encode(value, for_cloud_api=False), catalog, items,
                )


def test_pinned_python_default_arguments_are_elided_and_use_algorithm_defaults():
    data = fixture()
    catalog, items = example().declared_local_data(data)
    with OfflineGuard():
        ee = make_ee()
        base = ee.ImageCollection("sentinel-2-l2a")
        primary = base.filter(ee.Filter.eq("side", "primary")).select(["red", "nir"])
        quality = base.filter(ee.Filter.eq("side", "qa"))
        values = {
            "band_only": ee.Image(primary.first()).linkCollection(quality, "qa"),
            "no_selection": ee.Image(primary.first()).linkCollection(quality),
            "combine_default": primary.combine(quality.select(["nir", "qa"])).first(),
        }
        outputs = {}
        for name, value in values.items():
            wire = ee.serializer.encode(value, for_cloud_api=False)
            # Legacy serialization omits the SDK wrapper's optional None args.
            def invocations(node):
                if isinstance(node, dict):
                    if node.get("functionName") in {"Image.linkCollection", "ImageCollection.combine"}:
                        yield node
                    for child in node.values():
                        yield from invocations(child)
                elif isinstance(node, (list, tuple)):
                    for child in node:
                        yield from invocations(child)
            for call in invocations(wire):
                assert "matchPropertyName" not in call["arguments"]
                assert "overwrite" not in call["arguments"]
            outputs[name] = compile_expression(wire, catalog, items)
    assert outputs["band_only"]["bands"] == ["red", "nir", "qa"]
    assert outputs["no_selection"]["bands"] == ["red", "nir"]
    assert outputs["combine_default"]["bands"] == ["red", "nir", "nir_1", "qa"]
