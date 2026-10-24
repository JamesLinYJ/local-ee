"""Wave67 official SDK wires, local compilation, and native sampled readback."""
from __future__ import annotations

import csv
import os
from pathlib import Path
import struct

import pytest

from ee_empty_expression_reference import (
    expected_expression_outputs,
    expected_fractional_hidden_recovery,
    expected_mask_transition_outputs,
    load_fixture,
)
from ee_empty_expression_sdk import (
    canonical_graph as _canonical_graph,
    official_wires as _official_wires,
    python_example as _python_example,
    wire_digest as _wire_digest,
)
from ee_weighted_sampling_helpers import _semantic_wire
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from scripts.ee_python_api.offline import OfflineGuard
from scripts.probe_empty_expression_native import EXPECTED_MANIFEST, run_probe


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_RECEIPTS = ROOT / "audit/gee-python-wave67/workflow"
SAMPLE_NAMES = (
    "map_sample", "setter_value_sample", "setter_weight_sample",
    "update_mask_value_sample", "update_mask_weight_sample",
    "fractional_hidden_recovery_value_sample",
    "fractional_hidden_recovery_weight_sample",
)


def test_frozen_original_python_and_javascript_sdk_graphs_match_before_compile():
    fixture = load_fixture()
    python, javascript = _official_wires(fixture)
    assert _semantic_wire(_canonical_graph(python["constructor"])) == _semantic_wire(
        _canonical_graph(javascript["constructor"])
    )
    constructor = _semantic_wire(_canonical_graph(python["constructor"]))["value"]
    assert constructor["functionName"] == "Image.mask"
    assert constructor["arguments"]["image"] == constructor["arguments"]["mask"]
    constant = constructor["arguments"]["image"]
    assert constant["functionName"] == "Image.constant"
    assert constant["arguments"]["value"] == ("number", "0x0.0p+0")
    assert set(python["expressions"]) == set(javascript["expressions"])
    assert set(python["workflow"]) == set(javascript["workflow"])
    assert fixture["original_sdk_wire_sha256"]["python:constructor"] == _wire_digest(
        python["constructor"]
    )
    assert fixture["original_sdk_wire_sha256"]["javascript:constructor"] == _wire_digest(
        javascript["constructor"]
    )
    for section in ("expressions", "workflow"):
        for name, python_wire in python[section].items():
            js_wire = javascript[section][name]
            python_canonical = _semantic_wire(_canonical_graph(python_wire))
            js_canonical = _semantic_wire(_canonical_graph(js_wire))
            assert python_canonical == js_canonical, (section, name)
            key = f"{section}:{name}"
            assert fixture["original_sdk_semantic_sha256"][key] == _wire_digest(
                python_canonical
            ), key
            for client, wire in (("python", python_wire), ("javascript", js_wire)):
                raw_key = f"{client}:{section}:{name}"
                assert fixture["original_sdk_wire_sha256"][raw_key] == _wire_digest(wire), raw_key
    assert "default_call" in python["expressions"]
    assert "default_index" in python["expressions"]
    assert "default_name" in python["expressions"]
    assert "dot_red" in python["expressions"]
    assert {"index_red", "index_nir", "assigned"} <= set(python["expressions"])
    assert fixture["transparent_constructor"] == {"band_names": ["constant"], "band_count": 1,
                                                    "mask_value": 0}


def _native_probe_or_skip():
    if not os.path.lexists(EXPECTED_MANIFEST):
        pytest.skip(f"Wave67 native probe requires the designated Wave66 manifest: {EXPECTED_MANIFEST}")
    return run_probe(receipt_dir=WORKFLOW_RECEIPTS)


def _same_f64(actual, expected, label):
    if expected is None:
        assert actual is None, (label, actual)
    else:
        assert actual is not None, (label, expected)
        assert struct.pack(">d", float(actual)) == struct.pack(">d", float(expected)), (
            label, actual, expected,
        )


def test_compiled_sample_workflow_reaches_actual_kernels_csv_and_sdk_getinfo(
    tmp_path, monkeypatch,
):
    from engine.ee_sampling_result import SampledFeatureTable
    from gee.services import ee as ee_service
    from gee.sampling_values import assemble_sample_features
    from table_export_support import FinishedTask, install

    fixture = load_fixture()
    expression_reference = expected_expression_outputs(fixture)
    transition_reference = expected_mask_transition_outputs(fixture)
    hidden_recovery_reference = expected_fractional_hidden_recovery(fixture)
    transition_cases = fixture["mask_transitions"]
    case_names = transition_cases["case_names"]
    assert len(case_names) == 16
    expected_names = [
        f"{old}_to_{new}"
        for old in ("valid_old", "raw_nodata_old", "old_zero",
                    "old_fractional_025", "old_subnormal")
        for new in ("zero", "positive", "fractional")
    ] + ["negative_science_old_zero_to_positive"]
    assert case_names == expected_names
    assert transition_cases["science"][:3] == [8, 8, 8]
    assert transition_cases["science"][3:6] == [None, None, None]
    assert transition_cases["old_weights"][6:9] == [0, 0, 0]
    assert transition_cases["old_weights"][9:12] == [0.25, 0.25, 0.25]
    assert transition_cases["old_weights"][12:15] == [5e-324] * 3
    assert transition_cases["new_weights"] == [0, 1, 0.25] * 5 + [1]
    native_probe = _native_probe_or_skip()
    native = native_probe["native_result"]
    boolean_control = native["geotrellis_boolean_control"]
    assert boolean_control["input_r"] == [1.0, 2.0, None]
    assert boolean_control["input_n"] == [3.0, None, 5.0]
    # These are raw values from the pinned upstream GeoTrellis local operators.
    # Keep their missing-as-false behavior distinct from the independent
    # expression semantic expectation, which propagates missing operands.
    assert boolean_control["greater_r"] == [1.0, 1.0, 0.0]
    assert boolean_control["greater_n"] == [1.0, 0.0, 1.0]
    assert boolean_control["less_r"] == [0.0, 0.0, 0.0]
    assert boolean_control["less_n"] == [0.0, 0.0, 0.0]
    assert boolean_control["and_positive"] == [1.0, 0.0, 0.0]
    assert boolean_control["and_positive"] != [1.0, None, None]
    assert boolean_control["input_missing_mask"] == [0.0, 1.0, 1.0]
    assert boolean_control["and_positive_input_nodata_preserved"] == [1.0, None, None]
    logical_control = native["geotrellis_logical_nonbinary_control"]
    assert logical_control["input_x"] == [2.0, -3.0, 0.0]
    assert logical_control["input_y"] == [-3.0, 2.0, 2.0]
    assert logical_control["and_raw"] == [0.0, 0.0, 0.0]
    assert logical_control["or_raw"] == [-1.0, -1.0, 2.0]
    assert logical_control["not_x_raw"] == [-3.0, 2.0, -1.0]
    # EE logical truth is nonzero, so normalize each numeric operand first.
    assert logical_control["x_nonzero"] == [1.0, 1.0, 0.0]
    assert logical_control["y_nonzero"] == [1.0, 1.0, 1.0]
    assert logical_control["and_x_nonzero"] == [1.0, 1.0, 0.0]
    assert logical_control["or_x_nonzero"] == [1.0, 1.0, 1.0]
    assert logical_control["not_x_equal_zero"] == [0.0, 0.0, 1.0]
    assert native_probe["deployment_eligible"] is False
    from scripts import build_integer_adapter

    assert len(build_integer_adapter.SOURCES) == 75
    assert (native_probe["source_count"], native_probe["scala_tool_count"],
            native_probe["runtime_jar_count"]) == (len(build_integer_adapter.SOURCES), 3, 245)
    assert native_probe["sample_row_counts"] == {key: 16 for key in (
        "map_sample_rows", "default_value_sample_rows", "default_weight_sample_rows",
        "setter_value_sample_rows", "setter_weight_sample_rows",
        "update_mask_value_sample_rows", "update_mask_weight_sample_rows",
        "fractional_hidden_recovery_value_sample_rows",
        "fractional_hidden_recovery_weight_sample_rows",
    )}
    for key, expected in transition_reference.items():
        actual = native[key]
        assert len(actual) == 16
        for index, (got, wanted) in enumerate(zip(actual, expected)):
            _same_f64(got, wanted, f"{key}[{index}]")
    assert native["setter_values"][15] == 0.0
    assert native["update_mask_values"][15] is None
    assert native["setter_weights"][15] == 1.0
    assert native["update_mask_weights"][15] == 0.0
    assert native["filled_science"][6] == 0.0
    assert native["filled_science"][7] == 0.0
    assert native["fractional_hidden_recovery_values"] == hidden_recovery_reference["values"]
    assert native["fractional_hidden_recovery_weights"] == hidden_recovery_reference["weights"]
    assert all(row["values"] == [None] * 4
               for row in native["default_value_sample_rows"])
    assert all(row["values"] == [0.0] * 4
               for row in native["default_weight_sample_rows"])

    example = _python_example()
    catalog, items = example.synthetic_metadata(fixture)
    with OfflineGuard() as guard:
        runtime = install(monkeypatch, tmp_path)
        monkeypatch.setattr(ee_service, "DATA", tmp_path)
        monkeypatch.setattr(ee_service, "catalog_snapshot", lambda: (catalog, items))
        source = runtime.ee.Image(runtime.ee.ImageCollection(fixture["source_id"]).first())
        outputs = example.build_workflow(runtime.ee, source, fixture)
        for name in ("default_value_sample", "default_weight_sample"):
            with pytest.raises(UnsupportedEEError, match="finite bound raster operand"):
                compile_expression(
                    runtime.ee.serializer.encode(outputs[name], for_cloud_api=False),
                    catalog, items,
                )
        encoded = {name: runtime.ee.serializer.encode(outputs[name], for_cloud_api=False)
                   for name in SAMPLE_NAMES}
        descriptors = {name: compile_expression(wire, catalog, items)
                       for name, wire in encoded.items()}
        assert all(descriptors[name]["kind"] == "sample_table" for name in SAMPLE_NAMES)
        expected_map_bands = [
            "named_sum", "dot_red", "index_red", "index_nir", "assigned",
            "unweighted_nd", "normalized_difference",
        ]
        map_spec = decode_sampling_spec(descriptors["map_sample"]["sample_spec"])
        assert map_spec["bands"] == expected_map_bands
        assert descriptors["map_sample"]["bands"] == sampling_columns(map_spec)
        boolean_callbacks = []
        for node in descriptors["map_sample"]["process_graph"].values():
            reducer = node.get("arguments", {}).get("reducer")
            callback = reducer.get("process_graph") if isinstance(reducer, dict) else None
            if isinstance(callback, dict) and "boolean_missing_1" in callback:
                boolean_callbacks.append(callback)
        assert boolean_callbacks
        for callback in boolean_callbacks:
            assert callback["boolean_missing_0"]["process_id"] == "is_nodata"
            assert callback["boolean_missing_1"]["process_id"] == "is_nodata"
            assert callback["boolean_valid_1"] == {
                "process_id": "and",
                "arguments": {"x": {"from_node": "boolean_present_0"},
                              "y": {"from_node": "boolean_present_1"}},
            }
            assert callback["result"] == {
                "process_id": "if",
                "arguments": {"value": {"from_node": "boolean_valid_1"},
                              "accept": {"from_node": "boolean_value"},
                              "reject": None},
                "result": True,
            }
        assert any(node["process_id"] == "local_ee_unmask"
                   for node in descriptors["setter_value_sample"]["process_graph"].values())
        with pytest.raises(UnsupportedEEError, match="mask-aware consumer"):
            compile_expression(
                runtime.ee.serializer.encode(outputs["setter_values"], for_cloud_api=False),
                catalog, items,
            )

        completed = []
        native_rows = [native[f"{name}_rows"] for name in SAMPLE_NAMES]
        call_index = 0

        def evaluate_from_native_rows(_value):
            nonlocal call_index
            sample_name = SAMPLE_NAMES[call_index]
            rows = native_rows[call_index]
            call_index += 1
            response = runtime.dispatch({
                "action": "evaluate",
                "expression": runtime.ee.serializer.encode(
                    outputs[sample_name], for_cloud_api=False,
                ),
            })
            assert response.get("pending") is True
            row = runtime.store.job(response["job_id"], runtime.account["user_id"])
            assert row["context"]["result_kind"] == "samples"
            spec_text = row["context"]["sample_spec"]
            spec = decode_sampling_spec(spec_text)
            data = assemble_sample_features(spec, rows)
            table = SampledFeatureTable(data, sampling_columns(spec))
            table.sample_spec = spec_text
            table.sample_spec_verified = True
            table.sample_operations = ()
            table.sample_operation_work = 0
            folder = tmp_path / "jobs" / row["id"] / "out"
            folder.mkdir(parents=True)
            table.write_assets(folder / "out")
            row["status"] = "running"
            runtime.worker.finish(row, FinishedTask())
            assert row["status"] == "finished"
            csv_path = folder / "openEO.csv"
            with csv_path.open(encoding="utf-8", newline="") as stream:
                header = next(csv.reader(stream))
                csv_rows = list(csv.reader(stream))
            assert header == sampling_columns(spec)
            assert len(csv_rows) == len(rows) == 16
            result = runtime.dispatch({"action": "result", "job_id": row["id"]})["value"]
            completed.append((sample_name, csv_path, result, spec))
            return result

        monkeypatch.setattr(runtime.ee.data, "computeValue", evaluate_from_native_rows)
        readbacks = [outputs[name].getInfo() for name in SAMPLE_NAMES]
    assert guard.evidence()["attempt_count"] == 0
    assert call_index == len(SAMPLE_NAMES)
    assert len(completed) == len(SAMPLE_NAMES)
    sample_specs = {
        name: decode_sampling_spec(descriptors[name]["sample_spec"])
        for name in SAMPLE_NAMES
    }
    band_keys = {name: list(sample_specs[name]["bands"]) for name in SAMPLE_NAMES}
    for (name, csv_path, result, spec), info in zip(completed, readbacks):
        assert csv_path.is_file()
        assert spec == sample_specs[name]
        assert descriptors[name]["bands"] == sampling_columns(spec)
        assert info["properties"]["band_order"] == band_keys[name]
        assert result["properties"]["band_order"] == band_keys[name]
        features = info["features"]
        assert len(features) == 16
        assert len(result["features"]) == 16
        rows = native_rows[SAMPLE_NAMES.index(name)]
        with csv_path.open(encoding="utf-8", newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        assert len(csv_rows) == len(rows)
        for row_index, (feature, row, result_feature) in enumerate(zip(
                features, rows, result["features"])):
            assert row["row"] == row_index // 4 and row["col"] == row_index % 4
            assert csv_rows[row_index]["system:index"] == feature["id"]
            for band, value in zip(band_keys[name], row["values"]):
                _same_f64(feature["properties"][band], value, f"{name}:{row_index}:{band}")
                _same_f64(result_feature["properties"][band], value,
                          f"csv:{name}:{row_index}:{band}")
                csv_value = csv_rows[row_index][band]
                _same_f64(None if csv_value == "" else float(csv_value), value,
                          f"physical-csv:{name}:{row_index}:{band}")
        if name == "map_sample":
            for row_index, feature in enumerate(features):
                for band in band_keys[name]:
                    _same_f64(feature["properties"][band],
                              expression_reference[band]["values"][row_index],
                              f"reference:{band}:{row_index}")
        elif name == "setter_value_sample":
            for row_index, feature in enumerate(features):
                _same_f64(feature["properties"]["mask_science"],
                          transition_reference["setter_values"][row_index],
                          f"setter-reference:{row_index}")
        elif name == "setter_weight_sample":
            for row_index, feature in enumerate(features):
                _same_f64(feature["properties"]["mask_science"],
                          transition_reference["setter_weights"][row_index],
                          f"setter-weight-reference:{row_index}")
        elif name == "fractional_hidden_recovery_value_sample":
            for row_index, feature in enumerate(features):
                _same_f64(feature["properties"]["fractional_hidden_recovery"],
                          hidden_recovery_reference["values"][row_index],
                          f"hidden-recovery-reference:{row_index}")
        elif name == "fractional_hidden_recovery_weight_sample":
            for row_index, feature in enumerate(features):
                _same_f64(feature["properties"]["fractional_hidden_recovery"],
                          hidden_recovery_reference["weights"][row_index],
                          f"hidden-recovery-weight-reference:{row_index}")
