"""Wave59 multi-step color composition over the Wave57 synthetic scenes."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pytest import MonkeyPatch

from ee_scalar_composition_workflow_helpers import (
    OUTPUT_BANDS,
    WORKFLOW_NAMES,
    compile_with_work,
    evaluate_sample_graph,
    independent_expected,
    javascript_expressions,
    json_wire,
    load_fixture,
    local_sources,
    python_expressions,
    semantic,
)
from gee.compat.earthengine.image_color_ir import MAX_TRANSLATOR_WORK
from gee.graph import validate


def test_two_scene_color_compositions_match_both_sdks_and_independent_pixels(
        monkeypatch: MonkeyPatch):
    fixture = load_fixture()
    python = python_expressions(fixture)
    javascript = javascript_expressions(fixture)
    baseline_path = Path(__file__).resolve().parents[1] / (
        "audit/gee-python-wave59/workflow/before-compositions.json"
    )
    # This ignored audit artifact is captured before compiler changes. JSON
    # normalization avoids a false mismatch from Python tuples versus lists.
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        assert baseline["captured_before_production_changes"] is True
        for scene in fixture["scenes"]:
            scene_id = scene["id"]
            for name in WORKFLOW_NAMES:
                expected = baseline["scenes"][scene_id]["workflows"][name]
                assert json_wire(python[scene_id][name]) == expected[
                    "python"
                ]["expression"]
                assert json_wire(javascript[scene_id][name]) == expected[
                    "javascript"
                ]["expression"]
    catalog, items = local_sources(fixture)
    assert MAX_TRANSLATOR_WORK == 50_000
    assert set(python) == set(javascript) == {
        scene["id"] for scene in fixture["scenes"]
    }

    clients = {}
    for client, expressions in (("python", python), ("javascript", javascript)):
        compiled_scenes, work_scenes = {}, {}
        for scene_id, outputs in expressions.items():
            compiled_scenes[scene_id], work_scenes[scene_id] = {}, {}
            for name in WORKFLOW_NAMES:
                graph, work = compile_with_work(
                    outputs[name], catalog, items, monkeypatch,
                )
                compiled_scenes[scene_id][name] = graph
                work_scenes[scene_id][name] = work
        clients[client] = (compiled_scenes, work_scenes)

    for scene in fixture["scenes"]:
        scene_id = scene["id"]
        expected = independent_expected(scene)
        assert np.flatnonzero(~expected["valid_mask"]).tolist() == scene[
            "masked_pixel_indices"
        ]
        for name in WORKFLOW_NAMES:
            assert semantic(python[scene_id][name]) == semantic(javascript[scene_id][name])
            py_graph = clients["python"][0][scene_id][name]
            js_graph = clients["javascript"][0][scene_id][name]
            assert semantic(py_graph) == semantic(js_graph)
            assert py_graph["kind"] == js_graph["kind"] == "image"
            assert py_graph["bands"] == js_graph["bands"] == OUTPUT_BANDS[name]
            assert py_graph["source_item_ids"] == js_graph["source_item_ids"] == [scene_id]

            for client in ("python", "javascript"):
                graph, work = clients[client][0][scene_id][name], clients[client][1][scene_id][name]
                assert work <= 50_000
                assert len(graph["process_graph"]) <= 500
                assert len(json.dumps(graph["process_graph"], separators=(",", ":"))) <= 1_000_000
                validate(graph["process_graph"])
                process_ids = {
                    node["process_id"] for node in graph["process_graph"].values()
                }
                assert "local_ee_to_double" in process_ids
                if name == "rgb_roundtrip_offset_float_stage_clamp":
                    assert "local_ee_to_float" in process_ids
                actual, names, timed = evaluate_sample_graph(graph, scene, fixture)
                values = actual[0] if timed else actual
                target = expected[name]
                assert values.dtype == np.float64
                assert names == OUTPUT_BANDS[name]
                expected_mask = np.broadcast_to(
                    expected["valid_mask"], values.shape,
                )
                np.testing.assert_array_equal(np.isfinite(values), expected_mask)
                np.testing.assert_allclose(values, target, rtol=0, atol=2e-14, equal_nan=True)

