"""Wave68 official SDK wires and offline local bandless accumulation workflow."""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from ee_bandless_reference import expected_pixels, load_fixture, local_metadata
from ee_bandless_sdk import canonical_graph, load_python_example, official_wires
from ee_weighted_sampling_helpers import _semantic_wire
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_translate import evaluate_graph


def _walk(value):
    if isinstance(value, dict):
        if value.get("type") == "Invocation":
            yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _client_semantics(wire):
    value = canonical_graph(wire)

    def normalize(node):
        if isinstance(node, dict):
            if node.get("type") == "Invocation" and node.get("functionName") == "Image.addBands":
                node["arguments"].setdefault("names", None)
            for child in node.values():
                normalize(child)
        elif isinstance(node, list):
            for child in node:
                normalize(child)

    normalize(value)
    return _semantic_wire(value)


def _reference_rows(spec, values, fixture):
    transform = fixture["grid"]["transform"]
    rows = []
    for row in range(fixture["grid"]["rows"]):
        for col in range(fixture["grid"]["columns"]):
            index = row * fixture["grid"]["columns"] + col
            x = transform[0] * (col + 0.5) + transform[2]
            y = transform[4] * (row + 0.5) + transform[5]
            rows.append({
                "feature": 0, "row": row, "col": col, "x": x, "y": y,
                "values": [values[band][index] for band in spec["bands"]],
            })
    return rows


def test_official_python_and_javascript_sdk_wires_are_frozen_offline():
    fixture = load_fixture()
    python, javascript = official_wires(fixture)
    expected = fixture["sdk_wire_sha256"]
    assert python["network_attempts"] == javascript["network_attempts"] == 0
    assert python["wire_sha256"] == expected["python"]
    assert javascript["wire_sha256"] == expected["javascript"]
    assert set(python["wires"]) == set(javascript["wires"]) == set(expected["python"])

    for name in python["wires"]:
        assert _client_semantics(python["wires"][name]) == _client_semantics(
            javascript["wires"][name]
        ), name
    empty_invocations = list(_walk(canonical_graph(python["wires"]["empty"])))
    assert any(node["functionName"] == "Image.select"
               and node["arguments"]["bandSelectors"] == []
               for node in empty_invocations)
    assert "List.iterate" in {
        node["functionName"] for node in _walk(canonical_graph(python["wires"]["accumulated"]))
    }
    assert "Collection.iterate" in {
        node["functionName"] for node in _walk(canonical_graph(python["wires"]["collection_iterate"]))
    }

def test_two_scene_accumulator_getinfo_graph_values_and_synthetic_csv_readback(
    tmp_path, monkeypatch,
):
    from engine.ee_sampling_result import SampledFeatureTable
    from gee.services import ee as ee_service
    from gee.sampling_values import assemble_sample_features
    from table_export_support import FinishedTask, install
    fixture = load_fixture()
    expected = expected_pixels(fixture)
    assert expected == fixture["reference"]["science_values"]
    catalog, items, arrays, centers, geometries = local_metadata(fixture)

    with OfflineGuard() as guard:
        runtime = install(monkeypatch, tmp_path)
        monkeypatch.setattr(ee_service, "DATA", tmp_path)
        monkeypatch.setattr(ee_service, "catalog_snapshot", lambda: (catalog, items))
        outputs = load_python_example().build_workflow(runtime.ee, fixture)

        # The zero-band seed has schema only. Image() itself retains its one
        # masked constructor band, so its metadata accessor remains distinct.
        assert outputs["empty"].bandNames().getInfo() == []
        assert runtime.ee.Image().bandNames().getInfo() == ["constant"]
        assert outputs["empty"].getInfo()["bands"] == []
        assert outputs["empty_metadata"].getInfo()["properties"] == fixture["reference"]["copied_properties"]
        assert outputs["source_empty_metadata"].getInfo()["properties"] == fixture["reference"]["copied_properties"]
        assert outputs["empty_add_source"].getInfo()["bands"] == [
            {"id": "red"}, {"id": "nir"},
        ]
        assert outputs["science"].getInfo()["bands"] == [
            {"id": name} for name in fixture["reference"]["science_band_order"]
        ]

        wires = {name: runtime.ee.serializer.encode(value, for_cloud_api=False)
                 for name, value in outputs.items()}
        with pytest.raises(
            UnsupportedEEError, match="Zero-band Images contain no raster bands",
        ):
            compile_expression(wires["empty"], catalog, items)

        compiled = {
            name: compile_expression(wires[name], catalog, items)
            for name in ("empty_add_source", "source_add_empty", "ordered_add",
                         "collision_default", "collision_overwrite", "accumulated",
                         "science", "collection_iterate")
        }
        assert compiled["empty_add_source"]["source_item_ids"] == ["wave68-scene-a"]
        assert compiled["source_add_empty"]["source_item_ids"] == ["wave68-scene-a"]
        assert compiled["collision_default"]["bands"] == ["nir", "red", "red_1", "nir_1"]
        assert compiled["collision_overwrite"]["bands"] == fixture["reference"]["overwrite_band_order"]
        assert compiled["collision_overwrite"]["source_item_ids"] == ["wave68-scene-b"]
        assert compiled["accumulated"]["bands"] == fixture["reference"]["accumulated_band_order"]
        assert compiled["science"]["bands"] == fixture["reference"]["science_band_order"]
        assert compiled["science"]["source_item_ids"] == [
            scene["id"] for scene in fixture["scenes"]
        ]

        for name, expected_names in (
            ("empty_add_source", ["red", "nir"]),
            ("source_add_empty", ["red", "nir"]),
            ("ordered_add", ["nir", "red"]),
            ("accumulated", fixture["reference"]["accumulated_band_order"]),
            ("science", fixture["reference"]["science_band_order"]),
            ("collection_iterate", fixture["reference"]["accumulated_band_order"]),
        ):
            evaluated = evaluate_graph(
                compiled[name], arrays, grid=centers, source_geometries=geometries,
            )
            assert evaluated[1] == expected_names
            assert evaluated[2] is False
            wanted = {band: expected[band] for band in expected_names}
            np.testing.assert_allclose(
                evaluated[0], np.asarray([
                    [np.nan if value is None else value for value in wanted[band]]
                    for band in expected_names
                ]), equal_nan=True,
            )
        for name, expected_names, expected_values in (
            ("collision_default", ["nir", "red", "red_1", "nir_1"], {
                "nir": fixture["scenes"][0]["values"]["nir"],
                "red": fixture["scenes"][0]["values"]["red"],
                "red_1": fixture["scenes"][1]["values"]["red"],
                "nir_1": fixture["scenes"][1]["values"]["nir"],
            }),
            ("collision_overwrite", fixture["reference"]["overwrite_band_order"],
             fixture["reference"]["overwrite_values"]),
        ):
            evaluated = evaluate_graph(
                compiled[name], arrays, grid=centers, source_geometries=geometries,
            )
            assert evaluated[1] == expected_names
            np.testing.assert_allclose(
                evaluated[0], np.asarray([
                    [np.nan if value is None else value for value in expected_values[band]]
                    for band in expected_names
                ]), equal_nan=True,
            )

        # The CSV lifecycle is real, but rows are injected from the independent
        # fixture reference; this is not native raster-kernel execution.
        completed = {}

        def getinfo_from_reference_rows(_expression):
            response = runtime.dispatch({"action": "evaluate", "expression": wires["samples"]})
            assert response.get("pending") is True
            job = runtime.store.job(response["job_id"], runtime.account["user_id"])
            spec_text = job["context"]["sample_spec"]
            spec = decode_sampling_spec(spec_text)
            rows = _reference_rows(spec, expected, fixture)
            data = assemble_sample_features(spec, rows)
            table = SampledFeatureTable(data, sampling_columns(spec))
            table.sample_spec = spec_text
            table.sample_spec_verified = True
            table.sample_operations = ()
            table.sample_operation_work = 0
            folder = tmp_path / "jobs" / job["id"] / "out"
            folder.mkdir(parents=True)
            table.write_assets(folder / "out")
            job["status"] = "running"
            runtime.worker.finish(job, FinishedTask())
            assert job["status"] == "finished"

            csv_path = folder / "openEO.csv"
            with csv_path.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream)
                assert reader.fieldnames == sampling_columns(spec)
                csv_rows = list(reader)
            assert len(csv_rows) == 4
            completed.update(spec=spec, csv_rows=csv_rows, csv_path=csv_path)
            return runtime.dispatch({"action": "result", "job_id": job["id"]})["value"]

        monkeypatch.setattr(runtime.ee.data, "computeValue", getinfo_from_reference_rows)
        readback = outputs["samples"].getInfo()
        spec = completed["spec"]
        csv_rows = completed["csv_rows"]
        assert completed["csv_path"].is_file()
        assert len(readback["features"]) == 4
        for index, (row, feature) in enumerate(zip(csv_rows, readback["features"])):
            assert feature["id"] == f"f0_r{index // 2}_c{index % 2}"
            for band in spec["bands"]:
                wanted = expected[band][index]
                assert feature["properties"][band] == wanted
                assert row[band] == ("" if wanted is None else str(wanted))

    assert guard.evidence()["attempt_count"] == 0
