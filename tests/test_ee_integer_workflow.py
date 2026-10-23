"""Offline Python/JavaScript workflow coverage for integer image operations."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from ee_random_split_parity import JAVASCRIPT
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs


ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXAMPLE = ROOT / "examples/54_GEE_python_integer_images.py"
JAVASCRIPT_EXAMPLE = ROOT / "examples/javascript/08_合成QA整数影像.js"
EXPORT_REGION = {
    "type": "Polygon",
    "coordinates": [[
        [100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
        [100.2, 30.8], [100.2, 30.2],
    ]],
}
CAST_GROUPS = {
    "uint8": ("byte", "toByte", "uint8", "toUint8"),
    "int8": ("int8", "toInt8"),
    "int16": ("short", "toShort", "int16", "toInt16"),
    "int32": ("int", "toInt", "int32", "toInt32"),
    "uint16": ("uint16", "toUint16"),
    "uint32": ("uint32", "toUint32"),
    "int64": ("long", "toLong", "int64", "toInt64"),
}
BITWISE_GROUPS = {
    "bitCount": ("bitCount",),
    "bitwiseNot": ("bitwiseNot", "bitwise_not"),
    "bitwiseAnd": ("bitwiseAnd", "bitwise_and"),
    "bitwiseOr": ("bitwiseOr", "bitwise_or"),
    "bitwiseXor": ("bitwiseXor", "bitwise_xor"),
    "leftShift": ("leftShift", "left_shift"),
    "rightShift": ("rightShift", "right_shift"),
}
OUTPUT_NAMES = {
    "packed_qa", "cloud_clear", "surface_clear", "masked_ndvi",
    "dynamic_high_bit", "wide_eq", "wide_neq", "wide_lt", "wide_lte",
    "wide_gt", "wide_gte", "int64_at_upper_bound", "int64_above_previous",
    "int64_not_above_bound", "negative_bit_count", "signed_shift_63",
}
VISUALIZATION = {"min": 0, "max": 1, "palette": ["000000", "00aaff"]}


def _example():
    spec = importlib.util.spec_from_file_location("integer_images_example", PYTHON_EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _catalog():
    """Only synthetic metadata; never reads local raster data files."""
    metadata, items, _ = synthetic_inputs()
    for item in items["sentinel-2-l2a"]:
        item["properties"].update({
            "proj:code": "EPSG:32649",
            "proj:transform": [10, 0, 220000, 0, -10, 3420000],
        })
    return metadata, items


def _encode(ee, value):
    return ee.serializer.encode(value, for_cloud_api=False)


def _python_results():
    metadata, items = _catalog()
    captured_maps = []
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        assert ee.__version__ == "1.7.49"
        example = _example()
        scene = ee.ImageCollection("sentinel-2-l2a").first()
        outputs = example.build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))
        assert set(outputs) == OUTPUT_NAMES
        compiled = {
            name: compile_expression(_encode(ee, value), [metadata], items)
            for name, value in outputs.items()
        }

        # Exercise all 22 cast method names against the same admitted category band.
        cast_results = {}
        for dtype, names in CAST_GROUPS.items():
            for name in names:
                expression = getattr(scene.select("SCL"), name)()
                cast_results[name] = compile_expression(
                    _encode(ee, expression), [metadata], items,
                )

        # Exercise all seven bitwise methods and every pinned snake-case alias.
        category = scene.select("SCL")
        bitwise_results = {}
        for name in BITWISE_GROUPS["bitCount"]:
            bitwise_results[name] = compile_expression(
                _encode(ee, category.bitCount()), [metadata], items,
            )
        for canonical, argument in (
            ("bitwiseNot", None), ("bitwiseAnd", 5), ("bitwiseOr", 4),
            ("bitwiseXor", 4), ("leftShift", 2), ("rightShift", 2),
        ):
            for name in BITWISE_GROUPS[canonical]:
                method = getattr(category, name)
                expression = method() if argument is None else method(argument)
                bitwise_results[name] = compile_expression(
                    _encode(ee, expression), [metadata], items,
                )

        original_send = ee.Map._send
        ee.Map._send = lambda payload: captured_maps.append(payload) or {
            "job_id": "wave49-integer-map",
        }
        try:
            ee.Map.addLayer(
                outputs["cloud_clear"], VISUALIZATION, "Synthetic cloud-clear mask",
            )
        finally:
            ee.Map._send = original_send

        task = example.build_export_task(ee, outputs["masked_ndvi"])
        exported = {
            key: (_encode(ee, value) if key in {"expression", "region"} else value)
            for key, value in task.config.items()
        }
    assert guard.evidence()["attempt_count"] == 0
    assert len(captured_maps) == 1
    map_result = compile_expression(
        captured_maps[0]["expression"], [metadata], items,
    )
    return (compiled, cast_results, bitwise_results, map_result,
            captured_maps[0]["options"], exported, metadata, items)


def _javascript_results():
    pinned_node = ROOT / ".native/toolchains/node-v24.22.1-darwin-arm64/bin/node"
    node = str(pinned_node) if pinned_node.is_file() else shutil.which("node")
    if node is None:
        pytest.skip("Node is required for pinned JavaScript SDK serialization")
    if not Path(node).is_file():
        pytest.skip("Node is required for pinned JavaScript SDK serialization")
    prefix = JAVASCRIPT.split("const config =", 1)[0]
    script = prefix + r"""
let capturedLayer = null;
const mapStub = {addLayer: (image, visParams, name) => {
  capturedLayer = {image, visParams, name};
}};
const exportStub = ee.batch.Export;
const exampleSource = require('node:fs').readFileSync(
  'examples/javascript/08_合成QA整数影像.js', 'utf8');
const factory = new Function('Map', 'Export',
  exampleSource + '\nreturn {outputs, task};');
const {outputs:workflow, task} = factory(mapStub, exportStub);
const taskConfig = task.config_;
const encodedOutputs = Object.fromEntries(Object.entries(workflow).map(([key,value]) =>
  [key, ee.Serializer.encode(value)]));
const exportRegionValue = JSON.parse(taskConfig.region);
console.log(JSON.stringify({
  attempts,
  outputs:encodedOutputs,
  map:{expression:ee.Serializer.encode(capturedLayer.image),
    visParams:capturedLayer.visParams, name:capturedLayer.name},
  export:{expression:ee.Serializer.encode(taskConfig.element),
    region:Array.isArray(exportRegionValue)
      ? {type:'Polygon', coordinates:exportRegionValue} : exportRegionValue,
    scale:taskConfig.scale, crs:taskConfig.crs, maxPixels:taskConfig.maxPixels,
    folder:taskConfig.driveFolder,
    fileNamePrefix:taskConfig.driveFileNamePrefix}
}));
"""
    completed = subprocess.run(
        [node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["attempts"] == 0
    return result


def _specs(compiled):
    found = []
    for node in compiled["process_graph"].values():
        if node["process_id"] == "local_ee_integer_values":
            found.append(json.loads(node["arguments"]["spec"]))
    return found


def _constant(spec_operand):
    return struct.unpack(">d", bytes.fromhex(spec_operand["constant"]))[0]


def test_synthetic_qa_workflow_matches_python_and_javascript_sdk_graphs():
    (python, casts, bitwise, map_result, map_options, python_export,
     metadata, items) = _python_results()
    javascript = _javascript_results()

    assert set(javascript["outputs"]) == OUTPUT_NAMES == set(python)
    for name, expression in javascript["outputs"].items():
        assert compile_expression(expression, [metadata], items) == python[name], name

    assert map_result == python["cloud_clear"]
    assert javascript["map"]["expression"]
    assert compile_expression(
        javascript["map"]["expression"], [metadata], items,
    ) == python["cloud_clear"]
    assert map_options == {
        "vis_params": VISUALIZATION,
        "name": "Synthetic cloud-clear mask",
        "shown": True,
        "opacity": 1,
    }
    assert javascript["map"]["visParams"] == VISUALIZATION
    assert javascript["map"]["name"] == map_options["name"]

    js_export = javascript["export"]
    assert js_export["scale"] == python_export["scale"] == 10
    assert js_export["crs"] == python_export["crs"] == "EPSG:32649"
    assert js_export["maxPixels"] == python_export["maxPixels"] == 100_000
    assert js_export["folder"] == python_export["folder"] == "integer-images"
    assert js_export["fileNamePrefix"] == python_export["fileNamePrefix"] == \
        "synthetic_integer_qa_masked_ndvi"
    assert js_export["region"] == EXPORT_REGION
    assert python_export["region"] == {**EXPORT_REGION, "evenOdd": True}
    export_options = {"region": EXPORT_REGION, "scale": 10, "crs": "EPSG:32649"}
    assert compile_expression(
        js_export["expression"], [metadata], items, options=export_options,
    ) == compile_expression(
        python_export["expression"], [metadata], items, options=export_options,
    )

    cast_count = sum(len(names) for names in CAST_GROUPS.values())
    assert cast_count == 22
    for canonical, names in CAST_GROUPS.items():
        results = [casts[name] for name in names]
        assert all(result == results[0] for result in results), canonical
        assert _specs(results[0])[0]["dtype"] == canonical

    bitwise_count = sum(len(names) for names in BITWISE_GROUPS.values())
    assert bitwise_count == 13
    for canonical, names in BITWISE_GROUPS.items():
        results = [bitwise[name] for name in names]
        assert all(result == results[0] for result in results), canonical

    packed_specs = _specs(python["packed_qa"])
    assert {spec["op"] for spec in packed_specs} >= {
        "cast", "eq", "left_shift", "bit_or",
    }
    assert {spec["op"] for spec in _specs(python["cloud_clear"])} >= {
        "eq", "bit_and",
    }

    wide_operations = {
        "wide_eq": ("eq", 2**24 + 1),
        "wide_neq": ("neq", 2**24),
        "wide_lt": ("lt", 2**24 + 2),
        "wide_lte": ("lte", 2**24 + 1),
        "wide_gt": ("gt", 2**24),
        "wide_gte": ("gte", 2**24 + 1),
    }
    for name, (operation, threshold) in wide_operations.items():
        specs = _specs(python[name])
        assert any(spec["op"] == operation
                   and _constant(spec["operands"][1]) == threshold
                   and spec["operands"][0] == {"band": 0}
                   for spec in specs), name
        assert any(spec["op"] == "left_shift"
                   and _constant(spec["operands"][1]) == 24
                   and spec["operands"][0] == {"band": 0}
                   for spec in specs), name
        assert any(spec["op"] == "bit_or"
                   and _constant(spec["operands"][1]) == 1
                   for spec in specs), name
        assert not any(node["process_id"] == "local_ee_to_float"
                       for node in python[name]["process_graph"].values()), name

    upper_bound_operations = {
        "int64_at_upper_bound": ("eq", 2**53),
        "int64_above_previous": ("gt", 2**53 - 1),
        "int64_not_above_bound": ("lte", 2**53),
    }
    for name, (operation, threshold) in upper_bound_operations.items():
        specs = _specs(python[name])
        assert any(spec["op"] == operation
                   and _constant(spec["operands"][1]) == threshold
                   and spec["operands"][0] == {"band": 0}
                   for spec in specs), name
        assert any(spec["op"] == "left_shift"
                   and _constant(spec["operands"][1]) == 53
                   and spec["operands"][0] == {"band": 0}
                   for spec in specs), name
        assert any(spec["op"] == "eq"
                   and spec["operands"][0] == {"band": 0}
                   and _constant(spec["operands"][1]) == 1
                   for spec in specs), name
        assert not any(node["process_id"] == "local_ee_to_float"
                       for node in python[name]["process_graph"].values()), name

    high_bit_specs = _specs(python["dynamic_high_bit"])
    assert any(spec["op"] == "left_shift" and _constant(spec["operands"][1]) == 40
               for spec in high_bit_specs)
    assert any(spec["op"] == "bit_and" and _constant(spec["operands"][1]) == 2**40
               for spec in high_bit_specs)
    assert {spec["op"] for spec in high_bit_specs} >= {"eq", "left_shift", "bit_and"}

    negative_count_specs = _specs(python["negative_bit_count"])
    assert any(spec["op"] == "bit_count" for spec in negative_count_specs)
    shift_specs = _specs(python["signed_shift_63"])
    assert any(spec["op"] == "right_shift"
               and _constant(spec["operands"][1]) == 63 for spec in shift_specs)

    for output in python.values():
        if "process_graph" in output:
            validate(output["process_graph"])
