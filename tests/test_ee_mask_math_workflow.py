"""Wave66 offline mask-aware arithmetic from SDK wires to audited tile sampling."""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from ee_mask_math_reference import (
    PIXEL_MATH_UNARY,
    comparison_policy,
    expected_outputs,
    load_fixture,
    source_bands,
)
from ee_weighted_sampling_helpers import _semantic_wire
from gee.ee_python_client import configure_local_ee
from gee.sampling_spec import decode_sampling_spec, sampling_columns
from scripts.ee_python_api.offline import OfflineGuard
from scripts.probe_mask_math_native import EXPECTED_MANIFEST, run_probe


ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLE = ROOT / "examples/70_GEE_python_masked_math.py"
JAVASCRIPT_EXAMPLE = "examples/javascript/24_带权影像运算.js"
WORKFLOW_RECEIPTS = ROOT / "audit/gee-python-wave66/workflow"


def _python_example():
    spec = importlib.util.spec_from_file_location("wave66_mask_math_python", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _javascript_wires() -> dict:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node is required for the official JavaScript SDK comparison")
    script = r"""
const fs = require('node:fs');
let attempts = 0;
function deny() { attempts++; throw Error('Wave66 SDK wire generation attempted networking'); }
for (const module of ['node:http', 'node:https']) {
  const api = require(module); api.request = deny; api.get = deny;
}
const net = require('node:net');
net.connect = deny; net.createConnection = deny; net.Socket.prototype.connect = deny;
const dns = require('node:dns'); dns.lookup = deny; dns.resolve = deny;
global.fetch = deny;
global.window = globalThis;
const ee = require('./vendor/earthengine-js/earthengine.cjs');
global.ee = ee;
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ee-mask-math-wave66-v1.json', 'utf8'));
const algorithms = JSON.parse(fs.readFileSync('vendor/earthengine-js/algorithms.json', 'utf8')).algorithms;
const signatures = Object.fromEntries(algorithms.map(row => [row.name.replace(/^algorithms\//, ''), {
  description: row.description, returns: row.returnType,
  args: (row.arguments || []).map(arg => ({name: arg.argumentName, type: arg.type,
    optional: !!arg.optional, description: arg.description,
    ...('defaultValue' in arg ? {default: arg.defaultValue} : {})}))
}]));
ee.data.getAlgorithms = callback => callback ? callback(signatures) : signatures;
ee.initialize('http://localhost/disabled', 'http://localhost/disabled');
ee.data.computeValue = deny;
const example = require('./examples/javascript/24_带权影像运算.js');
const image = ee.Image(ee.ImageCollection(fixture.source_id).first());
const operationImages = example.buildOperationImages(ee, image, fixture);
const operations = Object.fromEntries(Object.entries(operationImages).map(([name, value]) =>
  [name, ee.Serializer.encode(value)]));
const workflow = example.buildWorkflow(ee, image, fixture);
const encoded = Object.fromEntries(Object.entries(workflow).map(([name, value]) =>
  [name, ee.Serializer.encode(value)]));
if (attempts !== 0) throw Error('JavaScript SDK swallowed a network attempt');
console.log(JSON.stringify({attempts, operations, encoded}));
"""
    result = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=45,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    payload = json.loads(result.stdout)
    assert payload["attempts"] == 0
    return {"operations": payload["operations"], "workflow": payload["encoded"]}


def _native_probe_or_skip():
    if not os.path.lexists(EXPECTED_MANIFEST):
        from datetime import datetime, timezone
        import uuid

        WORKFLOW_RECEIPTS.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        receipt = WORKFLOW_RECEIPTS / f"native-prerequisite-missing-{stamp}-{uuid.uuid4().hex[:12]}.json"
        descriptor = os.open(receipt, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        payload = {
            "format": "local-ee-mask-math-prerequisite-v1",
            "status": "skipped",
            "missing_prerequisite": str(EXPECTED_MANIFEST),
            "skipped_scope": ["actual Wave66 numeric tile and Image.sample kernels"],
            "still_runnable_scope": ["official Python/JavaScript SDK wire parity", "independent references"],
            "google_requests": 0,
            "deployment_eligible": False,
        }
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        pytest.skip(f"Wave66 native acceptance requires the designated manifest: {EXPECTED_MANIFEST}")
    return run_probe(receipt_dir=WORKFLOW_RECEIPTS)


_DOUBLE_MAX_ULPS = 4
# Keep the original callback allowance (3e-5 relative / 3e-6 absolute) only
# for the named Float32 special-function family. Probe calibration showed the
# largest ordinary absolute delta was 4.4e-8; erfcInv can underflow a tiny
# reference value to zero (~5e-30), so a relative-only test is unsuitable.
_FLOAT32_REL_TOL = 3e-5
_FLOAT32_ABS_TOL = 3e-6


def _same_value(actual, expected, output_name):
    if expected is None:
        assert actual is None
    elif actual is None:
        raise AssertionError(f"{output_name}: expected finite value {expected}, received NoData")
    else:
        policy = comparison_policy(output_name)
        if policy == "float32_callback":
            assert math.isclose(actual, expected, rel_tol=_FLOAT32_REL_TOL,
                                abs_tol=_FLOAT32_ABS_TOL), (output_name, actual, expected)
            return
        if policy == "float64_ulp" and expected != 0.0 and abs(expected) >= 1e-300:
            assert math.isfinite(actual) and math.isfinite(expected), (
                output_name, actual, expected,
            )
            ulp_delta = abs(actual - expected)
            tolerance = _DOUBLE_MAX_ULPS * max(math.ulp(actual), math.ulp(expected))
            assert ulp_delta <= tolerance, (
                output_name, actual, expected, ulp_delta, tolerance,
            )
            return
        assert struct.pack(">d", actual) == struct.pack(">d", expected)


def test_reference_covers_fractional_weights_domains_boolean_and_float32_stages():
    fixture = load_fixture()
    raw, weights = source_bands(fixture)
    expected = expected_outputs(fixture)
    assert set(weights) == set(fixture["weight_bands"])
    assert set(PIXEL_MATH_UNARY) == set(fixture["operations"]["pixel_math_unary"])
    assert len(expected) == 93

    observed_weights = [value for row in weights.values() for value in row]
    for boundary in (0.0, 0.25, 0.75, 5e-324, 0.9999999999999999, None):
        assert boundary in observed_weights
    assert raw["wide"][0] == 16777219.0
    assert expected["wide_add_right"]["values"][0] == 16777219.25
    assert comparison_policy("wide_add_right") == "float64_exact"
    assert comparison_policy("wide_sin") == "float64_ulp"
    assert comparison_policy("wide_pixel_erf") == "float32_callback"
    assert expected["wide_pixel_atan2_right"]["values"][0] == pytest.approx(
        math.atan2(0.25, float(struct.unpack("!f", struct.pack("!f", 16777219.0))[0])),
    )
    assert expected["red_sqrt"]["values"][6] is None
    assert expected["red_sqrt"]["weights"][6] == 0.0
    assert expected["red_log"]["values"][0] is None
    assert expected["red_log"]["weights"][0] == 0.0
    assert expected["red_not"]["values"][3] == 0.0  # a nonzero subnormal is truthy
    assert expected["red_or_zero"]["values"][3] == 1.0
    assert expected["red_clamp"]["values"][6] == 0.25
    assert expected["red_unit_scale"]["values"][6] == -1.0
    assert expected["wide_to_float"]["values"][1] is None  # 3.5e38 overflows Float32
    assert expected["wide_to_float"]["weights"][1] == 0.0
    assert expected["wide_float32_asin"]["weights"][0] == 0.0

    narrowed_add = struct.unpack(
        "!f", struct.pack("!f", expected["wide_add_right"]["values"][0])
    )[0]
    with pytest.raises(AssertionError):
        _same_value(narrowed_add, 16777219.25, "wide_add_right")


def test_official_python_and_javascript_sdk_wires_and_compiler_graphs_match():
    fixture = load_fixture()
    example = _python_example()
    catalog, items = example.synthetic_metadata(fixture)
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        image = ee.Image(ee.ImageCollection(fixture["source_id"]).first())
        operation_images = example.build_operation_images(ee, image, fixture)
        outputs = example.build_workflow(ee, image, fixture)
        from gee.ee_translate import compile_expression
        from gee.compat.earthengine.ir import UnsupportedEEError

        operation_wires = {
            name: ee.serializer.encode(value, for_cloud_api=False)
            for name, value in operation_images.items()
        }
        workflow_wires = {
            name: ee.serializer.encode(value, for_cloud_api=False)
            for name, value in outputs.items()
        }
        # Bare fractional carriers remain unsupported raster results. Compile
        # the audited consumers instead: each mask() getter exercises one math
        # graph, and sample() exercises the representative value readback.
        consumer_wires = {
            f"mask:{name}": ee.serializer.encode(value.mask(), for_cloud_api=False)
            for name, value in operation_images.items()
        }
        consumer_wires.update({
            f"workflow:{name}": workflow_wires[name]
            for name in ("values_sample", "weights_sample")
        })
        descriptors = {
            name: compile_expression(wire, catalog, items)
            for name, wire in consumer_wires.items()
        }
        with pytest.raises(UnsupportedEEError, match="mask-aware consumer"):
            compile_expression(operation_wires["red_abs"], catalog, items)
    assert guard.evidence()["attempt_count"] == 0

    javascript = _javascript_wires()
    assert set(operation_wires) == set(javascript["operations"])
    assert all(_semantic_wire(operation_wires[name]) ==
               _semantic_wire(javascript["operations"][name]) for name in operation_wires)
    assert set(workflow_wires) == set(javascript["workflow"])
    assert all(_semantic_wire(workflow_wires[name]) ==
               _semantic_wire(javascript["workflow"][name]) for name in workflow_wires)
    assert len(operation_wires) == 93
    assert descriptors["workflow:values_sample"]["kind"] == "sample_table"
    assert descriptors["workflow:weights_sample"]["kind"] == "sample_table"
    assert decode_sampling_spec(
        descriptors["workflow:values_sample"]["sample_spec"]
    )["bands"] == fixture["sample_outputs"]
    assert decode_sampling_spec(
        descriptors["workflow:weights_sample"]["sample_spec"]
    )["bands"] == [f"mask_{name}" for name in fixture["sample_outputs"]]

    mask_ops = set()
    pixel_math = set()
    for descriptor in descriptors.values():
        graph = descriptor.get("process_graph", {})
        for node in graph.values():
            if node.get("process_id") == "local_ee_mask_weights":
                mask_ops.add(json.loads(node["arguments"]["spec"])["op"])
            if node.get("process_id") == "local_ee_pixel_math":
                pixel_math.add(node["arguments"]["operation"])
    assert {"apply", "result_value", "validity", "update"} <= mask_ops
    assert set(PIXEL_MATH_UNARY) <= pixel_math
    assert "atan2" in pixel_math


def test_verified_native_tiles_and_sdk_getinfo_reach_csv_and_readback(
    tmp_path, monkeypatch,
):
    from engine.ee_sampling_result import SampledFeatureTable
    from gee.services import ee as ee_service
    from gee.sampling_values import assemble_sample_features
    from table_export_support import FinishedTask, install

    fixture = load_fixture()
    expected = expected_outputs(fixture)
    native_probe = _native_probe_or_skip()
    native = native_probe["native_result"]
    assert native_probe["deployment_eligible"] is False
    assert native_probe["source_count"] == 70
    assert native_probe["scala_tool_count"] == 3
    assert native_probe["runtime_jar_count"] == 245
    assert native_probe["jar_sha256"] == (
        "b1f20b0d4e9214b0da1433e4293f0bf2ae9e5b24e6b940ea3c88ab535def6564"
    )
    assert set(native["outputs"]) == set(expected)
    assert native["source_infinity_guard_rejected"] == [True, True]
    controls = native["result_value_controls"]
    assert controls["input_bits"][:5] == controls["output_bits"][:5]
    assert controls["input_bits"][:5] == [
        "3ff4000000000000", "8000000000000000", "0000000000000000",
        "0000000000000001", "8000000000000001",
    ]
    assert controls["output_bits"][5:] == [None, None, None]
    assert controls["output_values"][5:] == [None, None, None]
    atan2_zeros = native["atan2_signed_zero_controls"]
    assert atan2_zeros["x_bits"] == ["bf800000", "bf800000"]
    assert atan2_zeros["y_bits"] == ["80000000", "00000000"]
    assert atan2_zeros["output_bits"] == ["c0490fdb", "40490fdb"]
    float_pi = struct.unpack("!f", struct.pack("!f", math.pi))[0]
    assert atan2_zeros["output_values"] == [-float_pi, float_pi]
    wide_add = native["outputs"]["wide_add_right"]["values"][0]
    assert wide_add == 16777219.25
    assert struct.pack(">d", wide_add) == struct.pack(">d", 16777219.25)

    for name, reference in expected.items():
        result = native["outputs"][name]
        assert len(result["values"]) == len(reference["values"]), name
        assert result["weights"] == reference["weights"], name
        for actual, wanted in zip(result["values"], reference["values"]):
            _same_value(actual, wanted, name)
    for row in native["values_sample_rows"]:
        assert row["row"] in (0, 1)
        assert row["col"] in (0, 1, 2, 3)
        index = row["row"] * 4 + row["col"]
        for actual, name in zip(row["values"], fixture["sample_outputs"]):
            _same_value(actual, expected[name]["values"][index], name)
    for row in native["weights_sample_rows"]:
        index = row["row"] * 4 + row["col"]
        for actual, name in zip(row["values"], fixture["sample_outputs"]):
            assert actual == expected[name]["weights"][index]
    assert len(native["values_sample_rows"]) == len(native["weights_sample_rows"]) == 8

    example = _python_example()
    catalog, items = example.synthetic_metadata(fixture)
    with OfflineGuard() as guard:
        runtime = install(monkeypatch, tmp_path)
        monkeypatch.setattr(ee_service, "DATA", tmp_path)
        monkeypatch.setattr(ee_service, "catalog_snapshot", lambda: (catalog, items))
        image = runtime.ee.Image(runtime.ee.ImageCollection(fixture["source_id"]).first())
        outputs = example.build_workflow(runtime.ee, image, fixture)
        completed = []

        def native_rows(spec_text):
            spec = decode_sampling_spec(spec_text)
            bands = spec["bands"]
            return (native["weights_sample_rows"] if bands[0].startswith("mask_")
                    else native["values_sample_rows"])

        def evaluate_from_native_rows(value):
            response = runtime.dispatch({
                "action": "evaluate",
                "expression": runtime.ee.serializer.encode(value, for_cloud_api=False),
            })
            assert response.get("pending") is True
            row = runtime.store.job(response["job_id"], runtime.account["user_id"])
            assert row["context"]["result_kind"] == "samples"
            spec_text = row["context"]["sample_spec"]
            spec = decode_sampling_spec(spec_text)
            rows = native_rows(spec_text)
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
            assert len(csv_rows) == len(rows) == 8
            result = runtime.dispatch({"action": "result", "job_id": row["id"]})["value"]
            completed.append((csv_path, result, spec))
            return result

        monkeypatch.setattr(runtime.ee.data, "computeValue", evaluate_from_native_rows)
        values_info = outputs["values_sample"].getInfo()
        weights_info = outputs["weights_sample"].getInfo()
    assert guard.evidence()["attempt_count"] == 0
    assert len(completed) == 2
    assert all(path.is_file() for path, _result, _spec in completed)
    assert values_info["properties"]["band_order"] == fixture["sample_outputs"]
    assert weights_info["properties"]["band_order"] == [
        f"mask_{name}" for name in fixture["sample_outputs"]
    ]
    assert len(values_info["features"]) == len(weights_info["features"]) == 8
    for row_index, (value_row, weight_row) in enumerate(zip(
            native["values_sample_rows"], native["weights_sample_rows"])):
        value_properties = values_info["features"][row_index]["properties"]
        weight_properties = weights_info["features"][row_index]["properties"]
        pixel_index = value_row["row"] * 4 + value_row["col"]
        for band, value, weight in zip(fixture["sample_outputs"], value_row["values"], weight_row["values"]):
            assert value_properties[band] == value
            _same_value(value_properties[band], expected[band]["values"][pixel_index], band)
            assert weight_properties[f"mask_{band}"] == weight
