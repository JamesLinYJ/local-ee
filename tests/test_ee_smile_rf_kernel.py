"""Opt-in real Smile 1.5.3 and GeoTrellis tile-kernel probe; no SparkContext."""
from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

from gee.sampling_spec import encode_spec
from gee.smile_rf_spec import decode_rf_spec, prepare_rf_parameters, prepare_rf_rows, prepare_rf_spec
from gee.rf_validation_spec import prepare_query_rows
from scripts.build_integer_adapter import _engine_paths, build as build_base_adapter, sha256
from scripts.build_smile_rf_adapter import ROOT, WORK_ROOT, build as build_rf_adapter


pytestmark = pytest.mark.skipif(
    os.environ.get("LOCAL_EE_RUN_SMILE_RF_KERNEL_TEST") != "1",
    reason="opt-in trusted Smile/GeoTrellis JVM kernel; excludes Spark batch and service acceptance",
)


def _parameters(**changes):
    values = {
        "number_of_trees": 17,
        "variables_per_split": 1,
        "min_leaf_population": 2,
        "bag_fraction": 0.65,
        "max_nodes": 4,
        "seed": 41,
    }
    values.update(changes)
    return prepare_rf_parameters(**values)


def _spec(parameters, schema, class_property):
    return prepare_rf_spec(parameters, schema, class_property)


def _case():
    primary_schema = ["x_猫😀", "y"]
    primary_spec = _spec(_parameters(), primary_schema, "类别")
    xor = [(0, 0, 0), (0, 1, 1), (1, 0, 1), (1, 1, 0)]
    primary_rows = [[label, [x, y]] for _ in range(16) for x, y, label in xor]
    second_seed_spec = _spec(_parameters(seed=97), primary_schema, "类别")
    queries = [[x, y] for x in (-0.25, 0.0, 0.25, 0.75, 1.0, 1.25)
               for y in (-0.25, 0.0, 0.25, 0.75, 1.0, 1.25)]

    default_spec = _spec(_parameters(variables_per_split=None, max_nodes=None),
                         primary_schema, "类别")
    precision_spec = _spec(_parameters(number_of_trees=9, variables_per_split=1,
                                       min_leaf_population=1, bag_fraction=1.0,
                                       max_nodes=2, seed=7), ["precision"], "class")
    precision_rows = ([[0, [16777216]] for _ in range(16)]
                      + [[1, [16777217]] for _ in range(16)])

    unicode_cases = []
    for code_points in (129, 256):
        schema_name = "😀" * code_points
        class_property = "🧪" * code_points
        unicode_spec = _spec(
            _parameters(number_of_trees=9, variables_per_split=1,
                        min_leaf_population=1, bag_fraction=1.0,
                        max_nodes=2, seed=code_points),
            [schema_name], class_property,
        )
        unicode_rows = prepare_rf_rows(
            [[0, [0.0]] for _ in range(16)] + [[1, [1.0]] for _ in range(16)],
            decode_rf_spec(unicode_spec),
        )
        unicode_cases.append({
            "code_points": code_points,
            "schema_name": schema_name,
            "class_property": class_property,
            "spec": unicode_spec,
            "rows": unicode_rows,
        })

    float_values = [
        -0.0, 0.0, math.ulp(0.0), -math.ulp(0.0), 1e-300, 1e-7, 1e-6,
        1e16, 1e17, 1e23, 1.2345678901234567, -1e300, sys_float_max_half(),
        -sys_float_max_half(),
    ]
    randomizer = random.Random(23026)
    while len(float_values) < 270:
        bits = randomizer.getrandbits(64)
        value = struct.unpack(">d", struct.pack(">Q", bits))[0]
        if math.isfinite(value) and abs(value) <= sys_float_max_half():
            float_values.append(value)
    canonical_numeric_rows = prepare_rf_rows(
        [[index % 2, [value]] for index, value in enumerate(float_values)],
        decode_rf_spec(precision_spec),
    )

    invalid_specs = []
    valid_value = json.loads(precision_spec)
    invalid_specs.append(precision_spec[:-1] + ',"version":1}')
    invalid_specs.append(precision_spec + " ")
    invalid_specs.append(encode_spec({**valid_value, "version": True}))
    invalid_specs.append(encode_spec({**valid_value, "not_a_parameter": 3}))
    invalid_specs.append(encode_spec({**valid_value, "implementation": "smile-1.5.2"}))
    invalid_specs.append(encode_spec({**valid_value, "schema": ["system:index"]}))
    invalid_specs.append(precision_spec.replace('"bag_fraction":1.0', '"bag_fraction":NaN'))
    invalid_specs.append(encode_spec({**valid_value, "schema": ["😀" * 257]}))
    invalid_specs.append(encode_spec({**valid_value, "class_property": "🧪" * 257}))

    valid_rows = prepare_rf_rows(precision_rows, decode_rf_spec(precision_spec))
    invalid_rows = []

    def reject_rows(raw, spec=precision_spec):
        invalid_rows.append({"spec": spec, "rows": raw})

    reject_rows(valid_rows[:-1] + ',"version":1}')
    reject_rows(valid_rows + " ")
    reject_rows(encode_spec({"version": 1, "rows": [[0, [1]], [0, [2]]]}))
    reject_rows(encode_spec({"version": 1, "rows": [[0, [1]], [2, [2]]]}))
    reject_rows(encode_spec({"version": 1, "rows": [[0, [1]], [True, [2]]]}))
    reject_rows(encode_spec({"version": 1, "rows": [[0, [1, 2]], [1, [2, 3]]]}))
    reject_rows(valid_rows.replace('16777216', 'NaN', 1))
    reject_rows(encode_spec({"version": 1, "rows": [[0, [2**53 + 1]], [1, [2]]]}))
    reject_rows(encode_spec({"version": 1, "rows": [[0, [sys_float_max_half() * 2]], [1, [2]]]}))
    wide_schema = [f"f{index}" for index in range(8)]
    expensive_spec = _spec(_parameters(number_of_trees=256, variables_per_split=None,
                                       max_nodes=None), wide_schema, "class")
    expensive_rows = encode_spec({"version": 1, "rows": [None] * 1000})
    reject_rows(expensive_rows, expensive_spec)

    scale_spec = _spec(prepare_rf_parameters(
        number_of_trees=100, variables_per_split=None, min_leaf_population=1,
        bag_fraction=0.5, max_nodes=None, seed=42,
    ), [f"reflectance_{index}" for index in range(8)], "class")
    scale_rows = []
    for index in range(500):
        scale_rows.append([0, [0.01 + index * 0.00001 + band * 0.0001 for band in range(8)]])
    for index in range(500):
        scale_rows.append([1, [0.30 + index * 0.00001 + band * 0.0001 for band in range(8)]])

    half_max_rows = prepare_rf_rows(
        [[0, [sys_float_max_half()]], [1, [-sys_float_max_half()]],
         [0, [1.0]], [1, [-1.0]]],
        decode_rf_spec(precision_spec),
    )

    def hex_bits(value):
        return f"{struct.unpack('>Q', struct.pack('>d', value))[0]:016x}"

    return {
        "primary_spec": primary_spec,
        "primary_rows": prepare_rf_rows(primary_rows, decode_rf_spec(primary_spec)),
        "primary_row_count": len(primary_rows),
        "second_seed_spec": second_seed_spec,
        "default_spec": default_spec,
        "repeat_queries": queries,
        "precision_spec": precision_spec,
        "precision_rows": prepare_rf_rows(precision_rows, decode_rf_spec(precision_spec)),
        "unicode_cases": unicode_cases,
        "canonical_numeric_rows": canonical_numeric_rows,
        "canonical_numeric_bits": [hex_bits(value) for value in float_values],
        "half_max_rows": half_max_rows,
        "half_max_bits": [hex_bits(value) for value in (sys_float_max_half(), -sys_float_max_half(), 1.0, -1.0)],
        "invalid_specs": invalid_specs,
        "invalid_rows": invalid_rows,
        "scale_spec": scale_spec,
        "scale_rows": prepare_rf_rows(scale_rows, decode_rf_spec(scale_spec)),
        "scale_row_count": len(scale_rows),
        "scale_training_work": len(scale_rows) * 100 * 8 * len(scale_rows),
        "validation_spec": precision_spec,
        "validation_training_rows": prepare_rf_rows(precision_rows, decode_rf_spec(precision_spec)),
        "validation_query_rows": prepare_query_rows([[16777216], [16777217]], 1),
        "validation_empty_query_rows": prepare_query_rows([], 1),
        "validation_invalid_queries": [
            prepare_query_rows([[16777216]], 1) + " ",
            encode_spec({"rows": [[1, 2]], "version": 1}),
            encode_spec({"rows": [[True]], "version": 1}),
            encode_spec({"rows": [[2**53 + 1]], "version": 1}),
            encode_spec({"rows": [[None]], "version": 1}),
            '{"rows":[[1e309]],"version":1}',
            encode_spec({"rows": [[float(index)] for index in range(1001)], "version": 1}),
        ],
    }


def sys_float_max_half():
    import sys
    return sys.float_info.max / 2


def test_actual_smile_training_and_geotrellis_tile_kernel():
    scratch = WORK_ROOT
    scratch.mkdir(parents=True, exist_ok=True)
    base_dir = scratch / "base"
    adapter_dir = scratch / "adapter"
    probe_dir = scratch / "probe"
    for directory in (base_dir, adapter_dir, probe_dir):
        directory.mkdir(parents=True, exist_ok=True)
    base_jar = base_dir / "local-ee-integer-adapter.jar"
    base_manifest_path = base_jar.with_suffix(base_jar.suffix + ".manifest.json")
    adapter_jar = adapter_dir / "local-ee-smile-rf-adapter.jar"
    dependencies = ROOT.parents[1] / "work" / "gee-python-wave26-native" / "dependencies"

    # The adapter build is intentionally serialized and may be reused by the
    # probe after it has completed. Verify the retained manifests against the
    # current sources before reuse; otherwise build into this wave's scratch.
    from scripts.build_integer_adapter import SOURCES

    base_sources = SOURCES
    rf_sources = [ROOT / path for path in (
        "engine/ee_smile_rf_wire.scala", "engine/ee_smile_rf_factory.scala",
        "engine/ee_smile_rf_numeric.scala", "engine/ee_smile_rf_adapter.scala",
    )]

    def matches_sources(manifest_path, sources):
        try:
            manifest = json.loads(manifest_path.read_text())
            expected = {str(path.relative_to(ROOT)): sha256(path) for path in sources}
            return manifest.get("sources") == expected
        except (OSError, json.JSONDecodeError):
            return False

    can_reuse = (
        base_jar.is_file() and base_manifest_path.is_file()
        and adapter_jar.is_file()
        and matches_sources(base_manifest_path, base_sources)
        and matches_sources(adapter_jar.with_suffix(adapter_jar.suffix + ".manifest.json"), rf_sources)
    )
    if can_reuse:
        base_manifest = json.loads(base_manifest_path.read_text())
        adapter_manifest_path = adapter_jar.with_suffix(adapter_jar.suffix + ".manifest.json")
        adapter_manifest = json.loads(adapter_manifest_path.read_text())
        can_reuse = (
            base_manifest.get("jar_sha256") == sha256(base_jar)
            and adapter_manifest.get("jar_sha256") == sha256(adapter_jar)
            and adapter_manifest.get("base_adapter", {}).get("jar_sha256") == sha256(base_jar)
            and adapter_manifest.get("base_adapter", {}).get("manifest_sha256") == sha256(base_manifest_path)
            and adapter_manifest.get("build_script_sha256") == sha256(ROOT / "scripts/build_smile_rf_adapter.py")
        )
    if not can_reuse:
        base_manifest = build_base_adapter(base_jar)
        adapter_manifest = build_rf_adapter(adapter_jar, dependencies, base_jar, base_manifest_path)

    java, _, scala_tools, runtime_jars, _ = _engine_paths()
    lock = json.loads((ROOT / "deploy/smile-rf-lock.json").read_text())
    dependencies = [dependencies / name for name in sorted(lock["smile_jars"])]
    classpath_paths = [adapter_jar, base_jar, *dependencies, *runtime_jars]
    classpath = os.pathsep.join(str(path) for path in classpath_paths)
    compiler_classpath = os.pathsep.join(str(path) for path in scala_tools)

    classes = probe_dir / "classes"
    if classes.exists():
        shutil.rmtree(classes)
    classes.mkdir(parents=True)
    source = ROOT / "tests/fixtures/ee-smile-rf-kernel-probe.scala"
    validation_source = ROOT / "tests/fixtures/ee-smile-rf-validation-kernel-probe.scala"
    compile_result = subprocess.run(
        [str(java), "-cp", compiler_classpath, "scala.tools.nsc.Main", "-classpath", classpath,
         "-d", str(classes), str(source), str(validation_source)],
        capture_output=True, text=True, timeout=120,
    )
    assert compile_result.returncode == 0, compile_result.stderr

    fixture = _case()
    assert fixture["scale_training_work"] == 800_000_000
    case_path = probe_dir / "smile-rf-kernel-cases.json"
    case_path.write_text(json.dumps(fixture, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    run = subprocess.run(
        [str(java), "-cp", str(classes) + os.pathsep + classpath,
         "local.ee.smile.EeSmileRfKernelProbe", str(case_path)],
        capture_output=True, text=True, timeout=300,
    )
    assert run.returncode == 0, run.stderr
    assert "SMILE_RF_KERNEL_OK" in run.stdout
    assert "SMILE_RF_UNICODE_OK cases=2 codepoints=129,256 schema+class_property=train-predict" in run.stdout
    assert "SMILE_RF_SCALE_OK rows=1000 features=8 trees=100 mtry=2 bag=0.5 maxNodes=1000 seed=42" in run.stdout
    assert "low=0 high=1" in run.stdout

    validation_fixture = {
        "spec": fixture["validation_spec"],
        "training_rows": fixture["validation_training_rows"],
        "query_rows": fixture["validation_query_rows"],
        "empty_query_rows": fixture["validation_empty_query_rows"],
        "invalid_queries": fixture["validation_invalid_queries"],
    }
    validation_case_path = probe_dir / "smile-rf-validation-kernel-cases.json"
    validation_case_path.write_text(
        json.dumps(validation_fixture, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    )
    validation_run = subprocess.run(
        [str(java), "-cp", str(classes) + os.pathsep + classpath,
         "local.ee.smile.EeSmileRfValidationKernelProbe", str(validation_case_path)],
        capture_output=True, text=True, timeout=120,
    )
    assert validation_run.returncode == 0, validation_run.stderr
    assert "SMILE_RF_VALIDATION_OK trusted-feature-predictions=2 Float64=preserved" in validation_run.stdout
    assert "resubstitution-rows=32 matrix=independent-frequency-reference" in validation_run.stdout

    guard = subprocess.run(
        [str(java), "-cp", str(classes) + os.pathsep + classpath,
         "local.ee.smile.EeSmileRfKernelProbe", "--parallel-preinitialized",
         fixture["precision_spec"], fixture["precision_rows"]],
        capture_output=True, text=True, timeout=120,
    )
    assert guard.returncode == 0, guard.stderr
    assert "SMILE_RF_PARALLEL_GUARD_OK" in guard.stdout

    result = {
        "scope": "Trusted standalone Smile 1.5.3 training and real GeoTrellis tile kernels; no SparkContext or service",
        "stdout": run.stdout,
        "stderr": run.stderr,
        "compile_stdout": compile_result.stdout,
        "compile_stderr": compile_result.stderr,
        "parallel_guard_stdout": guard.stdout,
        "parallel_guard_stderr": guard.stderr,
        "validation_stdout": validation_run.stdout,
        "validation_stderr": validation_run.stderr,
        "case_counts": {
            "primary_rows": fixture["primary_row_count"],
            "invalid_specs": len(fixture["invalid_specs"]),
            "invalid_rows": len(fixture["invalid_rows"]),
            "binary64_values": len(fixture["canonical_numeric_bits"]),
            "scale_rows": fixture["scale_row_count"],
            "scale_features": 8,
            "scale_training_work_bound": fixture["scale_training_work"],
        },
        "adapter_manifest": adapter_manifest,
        "base_manifest_sha256": sha256(base_manifest_path),
        "probe_source_sha256": sha256(source),
        "validation_probe_source_sha256": sha256(validation_source),
        "case_sha256": sha256(case_path),
        "validation_case_sha256": sha256(validation_case_path),
        "limitations": [
            "No SparkContext, distributed Spark job, engine service, sandbox, data account, or deployment acceptance",
            "No Google Earth Engine same-data result or RandomForest implementation parity claim",
        ],
    }
    result_path = probe_dir / "smile-rf-kernel-result.json"
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    audit_dir = os.environ.get("GEE_AUDIT_DIR")
    if audit_dir:
        audit = Path(audit_dir)
        audit.mkdir(parents=True, exist_ok=True)
        for filename, content in (
            ("smile-rf-kernel-cases.json", case_path.read_text()),
            ("smile-rf-kernel-result.json", result_path.read_text()),
            ("smile-rf-adapter.manifest.json", json.dumps(adapter_manifest, indent=2) + "\n"),
        ):
            (audit / filename).write_text(content)
        audit_jar = audit / "local-ee-smile-rf-adapter.jar"
        shutil.copy2(adapter_jar, audit_jar)
        (audit / "local-ee-smile-rf-adapter.jar.sha256").write_text(sha256(audit_jar) + "\n")
