"""Pinned SDK spectral workflow graphs and independent synthetic references."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path

import numpy as np
import pytest

from ee_spectral_preparation_workflow_helpers import (
    FIXTURE_PATH,
    OUTPUT_BANDS,
    independent_color_and_calibration,
    javascript_graphs,
    load_example,
    make_ee,
    python_graphs,
    semantic_compiled,
    verify_fraction_fixture,
)
from ee_spectral_preparation_native_helper import (
    consume_native_unmix_result,
    persist_native_report,
    run_native_probe,
)
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_has_two_explicit_grids_and_exact_fraction_mixtures():
    data = fixture()
    assert data["schema"] == "local-ee-synthetic-spectral-preparation/v1"
    assert data["stac"]["grid"] == {
        "crs": "EPSG:32649",
        "transform": [10, 0, 500000, 0, -10, 10],
        "shape": [1, 6],
        "pixel_centers": [[500005 + 10 * i, 5] for i in range(6)],
        "width_m": 10,
        "height_m": 10,
    }
    assert [scene["id"] for scene in data["scenes"]] == [
        "spectral-west-v1", "spectral-east-v1",
    ]
    assert [scene["masked_pixel_indices"] for scene in data["scenes"]] == [[5], [1]]
    assert all(scene["item"]["properties"]["proj:transform"] ==
               data["stac"]["grid"]["transform"] for scene in data["scenes"])
    verify_fraction_fixture(data)

    assert data["native_probe"]["schema"] == "local-ee-spectral-unmix-native/v1"
    native_cases = {case["label"]: case for case in data["native_probe"]["cases"]}
    for scene in data["scenes"]:
        case = native_cases[scene["id"]]
        assert case["expected_bands"] == ["unmix0", "unmix1", "unmix2"]
        assert len(case["input_bands"]) == len(data["source_band_order"])
        assert len(case["expected_values"]) == len(case["expected_bands"])
        for source_band, native_band in zip(
            data["source_band_order"], case["input_bands"],
        ):
            expected_source = scene["arrays"][source_band]
            assert len(native_band) == len(expected_source) == 6
            for actual, expected in zip(native_band, expected_source):
                expected = float("nan") if expected is None else float(expected)
                assert (np.isnan(float(actual)) and np.isnan(expected)) or actual == format(
                    expected, ".17g",
                )
        for pixel, fractions in enumerate(scene["true_fractions"]):
            for component, fraction in enumerate(fractions):
                actual = case["expected_values"][component][pixel]
                if fraction is None:
                    assert actual == "NaN"
                else:
                    assert np.isclose(
                        float(actual), float(Fraction(fraction)),
                        rtol=0, atol=2e-12,
                    )


def test_pinned_python_and_javascript_compile_identical_scene_graphs():
    data = fixture()
    python, python_expressions = python_graphs(data)
    javascript, javascript_encoded = javascript_graphs(data)
    assert set(python) == set(javascript) == {scene["id"] for scene in data["scenes"]}
    for scene_id in python:
        assert set(python[scene_id]) == set(javascript[scene_id]) == set(OUTPUT_BANDS)
        assert semantic_compiled(python[scene_id]) == semantic_compiled(javascript[scene_id])
        for name, expected_bands in OUTPUT_BANDS.items():
            output = python[scene_id][name]
            assert output["kind"] == "image"
            assert output["bands"] == expected_bands
            assert output["source_item_ids"] == [scene_id]
            assert len(output["process_graph"]) <= 500

        unmix_graph = python[scene_id]["unmixed_fractions"]["process_graph"]
        native_nodes = [node for node in unmix_graph.values()
                        if node["process_id"] == "local_ee_unmix"]
        assert len(native_nodes) == 1
        assert json.loads(native_nodes[0]["arguments"]["spec"]) == json.loads(
            data["native_probe"]["cases"][0]["spec"]
        )
        # Python retains tuples in a few legacy serializer scopes while JS
        # returns JSON arrays. Normalize through the actual wire format before
        # asserting exact equality.
        python_wire = json.loads(json.dumps(
            python_expressions[scene_id]["unmixed_fractions"], sort_keys=True,
        ))
        javascript_wire = json.loads(json.dumps(
            javascript_encoded[scene_id]["unmixed_fractions"], sort_keys=True,
        ))
        assert javascript_wire == python_wire


def test_rgb_hsv_lut_and_polynomial_values_match_fraction_sample_reference():
    from ee_spectral_preparation_workflow_helpers import (
        evaluate_sample_graph,
        independent_color_and_calibration,
    )

    data = fixture()
    python, _python_expressions = python_graphs(data)
    javascript, _javascript_encoded = javascript_graphs(data)
    for scene in data["scenes"]:
        scene_id = scene["id"]
        expected = independent_color_and_calibration(data, scene)
        # Only closed pixel graphs are sample-interpreted here. The compact
        # unmix producer is validated from actual native tile output separately.
        for name in ("rgb_to_hsv", "rgb_roundtrip", "red_lut", "green_polynomial"):
            for compiled in (python[scene_id][name], javascript[scene_id][name]):
                actual, band_names, timed = evaluate_sample_graph(compiled, scene, data)
                assert band_names == OUTPUT_BANDS[name]
                values = actual[0] if timed else actual
                np.testing.assert_allclose(
                    values, expected[name], rtol=0, atol=2e-12, equal_nan=True,
                )
        west_mask, east_mask = [entry["masked_pixel_indices"][0]
                                for entry in data["scenes"]]
        other_mask = east_mask if scene_id == "spectral-west-v1" else west_mask
        rgb, _names, timed = evaluate_sample_graph(
            python[scene_id]["rgb_to_hsv"], scene, data,
        )
        if timed:
            rgb = rgb[0]
        assert np.isnan(rgb[:, west_mask if scene_id == "spectral-west-v1" else east_mask]).all()
        assert np.isfinite(rgb[:, other_mask]).all()


def test_unmix_sample_graph_consumes_actual_native_tile_outputs():
    data = fixture()
    python, _python_expressions = python_graphs(data)
    javascript, _javascript_encoded = javascript_graphs(data)
    report = run_native_probe(data)
    assert report["schema"] == "local-ee-spectral-unmix-native-result/v1"
    assert report["case_count"] >= 2
    assert report["output_cells"] >= 36
    assert report["invalid_spec_count"] >= 0
    assert report["rejected_input_count"] >= 0
    assert "SPECTRAL_UNMIX_KERNEL_OK cases=" in report["summary"]
    receipt = persist_native_report(report)
    assert receipt.is_file()

    native_by_scene = {
        result["label"]: result for result in report["actual_outputs"]
    }
    assert {scene["id"] for scene in data["scenes"]} <= set(native_by_scene)
    for scene in data["scenes"]:
        scene_id = scene["id"]
        native_case = native_by_scene[scene_id]
        assert native_case["band_names"] == ["unmix0", "unmix1", "unmix2"]
        for sdk_graphs in (python, javascript):
            actual = consume_native_unmix_result(
                sdk_graphs[scene_id]["unmixed_fractions"],
                scene,
                data,
                native_case,
            )
            assert actual.shape == (3, 6)


def test_unmix_invalid_dimensions_arguments_and_shared_graph_budget_reject():
    data = fixture()
    catalog, items = load_example().declared_local_data(data)
    with OfflineGuard() as guard:
        ee = make_ee()
        source = ee.ImageCollection(data["stac"]["collection"]["id"]).filter(
            ee.Filter.eq("system:index", data["scenes"][0]["id"]),
        ).first().select(
            data["source_band_order"], data["prepared_band_order"],
        )

        bad_columns = ee.serializer.encode(
            source.unmix([[0.2, 0.3]], sumToOne=True, nonNegative=True),
            for_cloud_api=False,
        )
        with pytest.raises(UnsupportedEEError, match="endmember|band|dimension|column"):
            compile_expression(bad_columns, catalog, items)

        bad_flag = ee.serializer.encode(
            source.unmix(data["unmix"]["endmembers"], sumToOne=1, nonNegative=True),
            for_cloud_api=False,
        )
        with pytest.raises((UnsupportedEEError, TypeError, ValueError)):
            compile_expression(bad_flag, catalog, items)

        encoded = ee.serializer.encode(
            source.unmix(data["unmix"]["endmembers"], sumToOne=True, nonNegative=True),
            for_cloud_api=False,
        )
        malformed = deepcopy(encoded)
        for _scope, node in malformed.get("scope", []):
            if isinstance(node, dict) and node.get("functionName") == "Image.unmix":
                node["arguments"]["unexpected"] = 1
                break
        else:
            raise AssertionError("Pinned SDK graph omitted Image.unmix")
        with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
            compile_expression(malformed, catalog, items)

        many = ee.Dictionary({
            f"fraction_{index}": source.unmix(
                data["unmix"]["endmembers"], sumToOne=True, nonNegative=True,
            )
            for index in range(510)
        })
        oversized = ee.serializer.encode(many, for_cloud_api=False)
        with pytest.raises(UnsupportedEEError, match="500|budget|limit|work"):
            compile_expression(oversized, catalog, items)
    assert guard.evidence()["attempt_count"] == 0
