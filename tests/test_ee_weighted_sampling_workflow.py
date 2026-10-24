"""Wave65 fractional-mask sampling from the audited native tile kernels to CSV."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from ee_weighted_sampling_helpers import (
    ROOT,
    assert_rows_match,
    expected_rows,
    independent_positive_tiles,
    independent_projected_tiles,
    javascript_wires,
    load_fixture,
    load_python_example,
    python_wires_and_descriptors,
    _semantic_wire,
)
from gee.ee_python_client import configure_local_ee
from gee.image_sampling_spec import is_image_sample
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from gee.sampling_values import assemble_sample_features
from scripts.ee_python_api.offline import OfflineGuard
from ee_weighted_sampling_native import native_probe
from table_export_support import FinishedTask, install


def _case_map(native):
    return {row["name"]: row for row in native["image_sample_cases"]}


def _cell_reference_map(rows):
    return {(row["row"], row["col"]): row for row in rows}


def _expected_sample_regions(fixture, pixel_rows):
    result = []
    for index, feature in enumerate(fixture["sample_regions"]["features"]):
        x, y = feature["geometry"]["coordinates"][:2]
        row = int(1.5 - y)
        col = int(x - 0.5)
        sampled = pixel_rows.get((row, col))
        if sampled is None:
            continue
        result.append({
            "feature": index,
            "row": row,
            "col": col,
            "x": x,
            "y": y,
            "values": sampled["values"],
        })
    return result


def test_actual_mask_apply_then_existing_sampling_kernels(native_probe):
    fixture = load_fixture()
    native = native_probe["native_result"]
    projected = independent_projected_tiles(fixture)
    all_positive = independent_positive_tiles(fixture)

    assert native_probe["manifest_format"] == "local-ee-standalone-audit-v1"
    assert native_probe["deployment_eligible"] is False
    assert native_probe["source_count"] == 70
    assert native_probe["runtime_jar_count"] == 245
    from scripts.probe_weighted_sampling_native import EXPECTED_MANIFEST
    assert native_probe["manifest_path"] == str(EXPECTED_MANIFEST.resolve())
    assert set(("local_ee_mask_weights", "local_ee_image_sample", "local_ee_sample_regions")) <= set(
        native["loaded_spi_ids"]
    )
    assert native["projected_fractional_tiles"] == projected
    assert native["projected_all_positive_tiles"] == all_positive

    # The smallest subnormal, ordinary fractions, exact zero, source NoData,
    # near-one and a deliberate Float32->Float64 stage all survive this route.
    assert projected["0,0"]["red"][0] == 16777219.0  # weight = 5e-324
    assert projected["0,0"]["wide_float"][0] == 16777220.0
    assert projected["0,0"]["red"][1] is None  # zero weight
    assert projected["0,0"]["wide_float"][1] == 1.25  # weight = 0.75
    assert projected["0,0"]["wide_float"][2] == 100.0  # weight = 5e-324
    assert projected["1,0"]["red"][3] == 8.0  # weight = 0.9999999999999999
    assert projected["1,0"]["wide_float"][3] is None  # mask NoData -> zero weight
    assert projected["1,0"]["red"][1] is None  # source NoData stays invalid

    cases = _case_map(native)
    assert len(cases["fractional-nullable"]["rows"]) == 8
    assert len(cases["fractional-drop-nulls"]["rows"]) == 4
    assert len(cases["all-positive-nullable"]["rows"]) == 8
    assert len(cases["fractional-factor-control"]["rows"]) == 4
    assert len(cases["all-positive-factor-control"]["rows"]) == 4
    assert cases["all-masked-empty"]["rows"] == []
    assert_rows_match(cases["fractional-nullable"]["rows"], expected_rows(projected))
    assert_rows_match(
        cases["fractional-drop-nulls"]["rows"],
        expected_rows(projected, drop_nulls=True),
    )
    assert_rows_match(cases["all-positive-nullable"]["rows"], expected_rows(all_positive))

    # A mask changes only nullability. It neither scales valid science values
    # nor changes deterministic sampling keys at the same factor/seed.
    fractional_rows = cases["fractional-factor-control"]["rows"]
    positive_rows = cases["all-positive-factor-control"]["rows"]
    assert [(row["feature"], row["row"], row["col"]) for row in fractional_rows] == [
        (row["feature"], row["row"], row["col"]) for row in positive_rows
    ]
    for weighted, control in zip(fractional_rows, positive_rows):
        for band_index, (value, raw_value) in enumerate(zip(weighted["values"], control["values"])):
            tile_key = f"{weighted['col'] // 2},{weighted['row'] // 2}"
            cell_index = (weighted["row"] % 2) * 2 + weighted["col"] % 2
            weight = fixture["tiles"][weighted["row"] // 2 * 2 + weighted["col"] // 2][
                "mask_bands"
            ][band_index]["values"][cell_index]
            assert value == (raw_value if weight is not None and weight > 0 else None)
    assert native_probe["sample_regions_row_count"] == 4
    expected_regions = _expected_sample_regions(
        fixture, _cell_reference_map(expected_rows(projected, drop_nulls=True)),
    )
    assert_rows_match(native["sample_regions_rows"], expected_regions)
    assert [row["feature"] for row in native["sample_regions_rows"]] == [0, 4, 5, 6]


def _ancestor_nodes(process_graph, reference):
    seen = set()

    def walk_graph(graph, node_id):
        key = id(graph), node_id
        if key in seen:
            return
        seen.add(key)
        node = graph[node_id]
        yield node_id, node
        yield from walk_value(node.get("arguments", {}), graph)

    def walk_value(value, graph):
        if type(value) is dict:
            child_graph = value.get("process_graph")
            if type(child_graph) is dict:
                for child_id, child in child_graph.items():
                    if child.get("result") is True:
                        yield from walk_graph(child_graph, child_id)
            reference_id = value.get("from_node")
            if type(reference_id) is str and reference_id in graph:
                yield from walk_graph(graph, reference_id)
            for name, child in value.items():
                if name not in {"process_graph", "from_node"}:
                    yield from walk_value(child, graph)
        elif type(value) is list:
            for child in value:
                yield from walk_value(child, graph)

    yield from walk_graph(process_graph, reference["from_node"])


def _node_ids(descriptor):
    return [node["process_id"] for node in descriptor["process_graph"].values()]


def test_official_python_javascript_wires_and_compiler_graphs_match():
    fixture = load_fixture()
    example = load_python_example()
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        python_wires, descriptors = python_wires_and_descriptors(ee, example, fixture)
    assert guard.evidence()["attempt_count"] == 0

    javascript = javascript_wires()
    assert set(python_wires) == set(javascript)
    assert all(_semantic_wire(python_wires[name]) == _semantic_wire(javascript[name])
               for name in python_wires)

    for name in ("samples_nullable", "samples_drop_nulls", "fractional_factor_control",
                 "all_positive_factor_control", "sample_regions_fractional",
                 "sample_regions_all_positive", "md_training", "rf_training"):
        assert descriptors[name]["kind"] == "sample_table"
        sampler = next(node for node in descriptors[name]["process_graph"].values()
                       if node["process_id"] == "local_ee_sample_regions")
        spec = decode_sampling_spec(sampler["arguments"]["spec"])
        assert spec["bands"] == fixture["bands"]
        ancestors = list(_ancestor_nodes(
            descriptors[name]["process_graph"], sampler["arguments"]["data"],
        ))
        mask_projections = [node for _node_id, node in ancestors
                            if node["process_id"] == "local_ee_mask_weights"]
        if "all_positive" in name:
            assert mask_projections == []
        else:
            operations = {
                json.loads(node["arguments"]["spec"])["op"]
                for node in mask_projections
            }
            assert {"apply", "update", "validity"} <= operations
            assert operations <= {"apply", "update", "validity"}

    sample_spec = decode_sampling_spec(descriptors["samples_nullable"]["sample_spec"])
    assert is_image_sample(sample_spec)
    assert sample_spec["image_sample"]["drop_nulls"] is False
    assert descriptors["samples_nullable"]["bands"] == sampling_columns(sample_spec)
    assert descriptors["samples_nullable"]["source_item_ids"] == [fixture["source_id"]]

    training_nodes = {
        name: _node_ids(descriptors[name])
        for name in ("md_classification", "rf_classification")
    }
    assert "local_ee_train_minimum_distance" in training_nodes["md_classification"]
    assert "local_ee_minimum_distance" in training_nodes["md_classification"]
    assert "local_ee_train_smile_rf_samples" in training_nodes["rf_classification"]
    assert "local_ee_smile_rf" in training_nodes["rf_classification"]
    for name in training_nodes:
        graph = descriptors[name]["process_graph"]
        train = next(node for node in graph.values()
                     if node["process_id"] in {
                         "local_ee_train_minimum_distance", "local_ee_train_smile_rf_samples",
                     })
        training_spec = json.loads(train["arguments"]["spec"])
        assert training_spec["class_property"] == "class_id"
        assert training_spec["schema"] == ["red", "nir"]
        sample_ops = [node for node in graph.values()
                      if node["process_id"] == "local_ee_sample_table_op"]
        assert len(sample_ops) == 4


def test_official_python_getinfo_reaches_real_sample_csv_and_sdk_readback(
    native_probe, tmp_path, monkeypatch,
):
    from engine.ee_sampling_result import SampledFeatureTable
    from gee.services import ee as ee_service

    fixture = load_fixture()
    example = load_python_example()
    catalog, items = example.synthetic_metadata()
    native = native_probe["native_result"]
    native_cases = _case_map(native)

    with OfflineGuard() as guard:
        runtime = install(monkeypatch, tmp_path)
        monkeypatch.setattr(ee_service, "DATA", tmp_path)
        monkeypatch.setattr(ee_service, "catalog_snapshot", lambda: (catalog, items))
        outputs = example.build_workflow(
            runtime.ee,
            runtime.ee.Image(fixture["source_id"]),
            runtime.ee.FeatureCollection(fixture["sample_regions"]),
            fixture,
        )
        completed = []

        def native_rows_from_spec(text):
            spec = decode_sampling_spec(text)
            return (native_cases["fractional-nullable"]["rows"]
                    if is_image_sample(spec) else native["sample_regions_rows"])

        def evaluate_from_verified_tile_rows(value):
            response = runtime.dispatch({
                "action": "evaluate",
                "expression": runtime.ee.serializer.encode(value, for_cloud_api=False),
            })
            assert response.get("pending") is True
            row = runtime.store.job(response["job_id"], runtime.account["user_id"])
            assert row["context"]["result_kind"] == "samples"
            spec_text = row["context"]["sample_spec"]
            spec = decode_sampling_spec(spec_text)
            rows = native_rows_from_spec(spec_text)
            data = assemble_sample_features(spec, rows)
            table = SampledFeatureTable(data, sampling_columns(spec))
            table.sample_spec = spec_text
            table.sample_spec_verified = True
            table.sample_operations = ()
            table.sample_operation_work = 0
            output_folder = tmp_path / "jobs" / row["id"] / "out"
            output_folder.mkdir(parents=True)
            table.write_assets(output_folder / "out")
            row["status"] = "running"
            runtime.worker.finish(row, FinishedTask())
            assert row["status"] == "finished"
            csv_path = output_folder / "openEO.csv"
            with csv_path.open(encoding="utf-8", newline="") as stream:
                header = next(csv.reader(stream))
                csv_rows = list(csv.reader(stream))
            assert header == sampling_columns(spec)
            assert len(csv_rows) == len(rows)
            result = runtime.dispatch({"action": "result", "job_id": row["id"]})["value"]
            completed.append({"row": row, "spec": spec, "csv": csv_path, "result": result})
            return result

        monkeypatch.setattr(runtime.ee.data, "computeValue", evaluate_from_verified_tile_rows)
        image_info = outputs["samples_nullable"].getInfo()
        regions_info = outputs["sample_regions_fractional"].getInfo()

    assert guard.evidence()["attempt_count"] == 0
    assert len(completed) == 2
    assert [entry["row"]["status"] for entry in completed] == ["finished", "finished"]
    assert all(entry["csv"].is_file() for entry in completed)

    projected = independent_projected_tiles(fixture)
    expected_image = expected_rows(projected)
    assert image_info["type"] == "FeatureCollection"
    assert image_info["properties"]["band_order"] == fixture["bands"]
    assert len(image_info["features"]) == 8
    for feature, reference in zip(image_info["features"], expected_image):
        expected_id = f"f0_r{reference['row']}_c{reference['col']}"
        assert feature["id"] == expected_id
        assert feature["geometry"] == {
            "type": "Point", "coordinates": [reference["x"], reference["y"]],
        }
        assert [feature["properties"][band] for band in fixture["bands"]] == reference["values"]

    expected_regions = _expected_sample_regions(
        fixture, _cell_reference_map(expected_rows(projected, drop_nulls=True)),
    )
    assert [row["properties"]["source_id"] for row in regions_info["features"]] == [
        "plot-p0", "plot-p4", "plot-p5", "plot-p6",
    ]
    assert [row["properties"]["record_number"] for row in regions_info["features"]] == [40, 44, 45, 46]
    for feature, reference in zip(regions_info["features"], expected_regions):
        properties = feature["properties"]
        assert [properties[band] for band in fixture["bands"]] == reference["values"]
        assert feature["geometry"] == {
            "type": "Point", "coordinates": [reference["x"], reference["y"]],
        }
    sample_regions_spec = completed[1]["spec"]
    assert [feature["properties"] for feature in sample_regions_spec["regions"]["features"]] == [
        {name: feature["properties"][name] for name in fixture["sample_properties"]}
        for feature in fixture["sample_regions"]["features"]
    ]
