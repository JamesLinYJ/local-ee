"""Opt-in trusted GeoTrellis remap probe; never starts SparkContext or a service."""
from __future__ import annotations

import json
import hashlib
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import uuid
import zipfile

import pytest

from scripts.build_integer_adapter import ROOT, _engine_paths, build
from gee.remap_spec import decode_remap_spec, prepare_remap_spec


pytestmark = pytest.mark.skipif(
    os.environ.get("LOCAL_EE_RUN_REMAP_KERNEL_TEST") != "1",
    reason="opt-in trusted JVM GeoTrellis remap kernel; no SparkContext or service acceptance",
)


def _spec(from_values, to_values, default):
    return json.dumps({"version": 1, "from": from_values, "to": to_values, "default": default},
                      sort_keys=True, separators=(",", ":"), allow_nan=False)


def _f32(value):
    return struct.unpack("!f", struct.pack("!f", value))[0]


def _hex(value):
    if math.isnan(value):
        return "NaN"
    if value == math.inf:
        return "Infinity"
    if value == -math.inf:
        return "-Infinity"
    return value.hex()


def _case(name, from_values, to_values, default, values, input_type="float64"):
    spec = prepare_remap_spec(from_values, to_values, default)
    assert decode_remap_spec(spec)["version"] == 1
    converted = [_f32(value) if input_type == "float32" and math.isfinite(value) else value
                 for value in values]
    outputs = []
    for value in converted:
        if math.isnan(value):
            outputs.append(math.nan)
            continue
        match = next((index for index, source in enumerate(from_values) if value == source), None)
        outputs.append(to_values[match] if match is not None else
                       math.nan if default is None else default)
    return {"name": name, "spec": spec,
            "input_type": input_type, "input": [_hex(value) for value in values],
            "expected": [_hex(value) for value in outputs]}


def _fixture():
    cases = [
        _case("binary64-exact-null-default-mask-and-signed-zero",
              [0.0, -1.5, 1.25], [-0.0, 0.0, 1e100], None,
              [0.0, -1.5, 1.25, 3.0, math.nan]),
        _case("finite-default-does-not-fill-input-nodata", [0.1], [7.25], -2.5,
              [0.1, 0.10000000000000002, 9.0, math.nan]),
        _case("native-float32-values-are-compared-without-narrowing-the-spec",
              [16777216.0, 1.0], [3.0, 8.0], None,
              [16777216.0, 16777217.0, 1.0, math.nan], "float32"),
        _case("binary64-extremes-subnormal-max-and-signed-zero",
              [sys.float_info.max, math.ulp(0.0), -math.ulp(0.0)], [6.0, 7.0, 8.0], None,
              [sys.float_info.max, math.ulp(0.0), -math.ulp(0.0), -0.0]),
        _case("empty-map-default", [], [], 0.0, [-0.0, 12.0, math.nan]),
        _case("full-256-entry-map", list(map(float, range(256))),
              [float(3000 + value) for value in range(256)], None, [0.0, 127.0, 255.0, 256.0]),
    ]
    invalid_specs = [
        "", "{", "null", "[]", "{\"version\":1,\"from\":[],\"to\":[],\"default\":null,\"extra\":0}",
        "{\"version\":1,\"from\":[],\"to\":[],\"default\":null,\"version\":1}",
        "{\"version\":true,\"from\":[],\"to\":[],\"default\":null}",
        "{\"version\":1.0,\"from\":[],\"to\":[],\"default\":null}",
        "{\"version\":2,\"from\":[],\"to\":[],\"default\":null}",
        "{\"version\":1,\"from\":0,\"to\":[],\"default\":null}",
        "{\"version\":1,\"from\":[1],\"to\":[],\"default\":null}",
        "{\"version\":1,\"from\":[true],\"to\":[1],\"default\":null}",
        "{\"version\":1,\"from\":[{}],\"to\":[1],\"default\":null}",
        "{\"version\":1,\"from\":[0.0,-0.0],\"to\":[1,2],\"default\":null}",
        "{\"version\":1,\"from\":[1,1.0],\"to\":[2,3],\"default\":null}",
        "{\"version\":1,\"from\":[9007199254740993],\"to\":[1],\"default\":null}",
        "{\"version\":1,\"from\":[1e999],\"to\":[1],\"default\":null}",
        "{\"version\":1,\"from\":[NaN],\"to\":[1],\"default\":null}",
        "{\"version\":1,\"from\":[Infinity],\"to\":[1],\"default\":null}",
        "{\"version\":1,\"from\":[],\"to\":[],\"default\":false}",
        "{\"version\":1,\"from\":[],\"to\":[],\"default\":null} []",
        _spec(list(map(float, range(257))), list(map(float, range(257))), None),
        " " * 1000001,
    ]
    return {"cases": cases, "invalid_specs": invalid_specs}


def test_actual_geotrellis_remap_kernel_matches_independent_binary64_oracle():
    scratch = ROOT.parent.parent / "work/gee-python-wave25-native"
    run = scratch / f"probe-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    run.mkdir(parents=True)
    jar = run / "local-ee-integer-adapter.jar"
    manifest = build(jar)
    with zipfile.ZipFile(jar) as archive:
        providers = archive.read(
            "META-INF/services/org.openeo.geotrelliscommon.CubeProcessProvider"
        ).decode("utf-8").splitlines()
    assert "local.ee.remap.LocalEeRemapCubeProcessProvider" in providers
    assert "local.ee.classify.LocalEeClassifyCubeProcessProvider" in providers
    assert "local.ee.sample.LocalEeSampleCubeProcessProvider" in providers
    java, _, compiler_tools, runtime_jars, _ = _engine_paths()
    classes = run / "probe-classes"
    classes.mkdir()
    probe_source = ROOT / "tests/fixtures/ee-remap-kernel-probe.scala"
    classpath = os.pathsep.join(map(str, [jar, *runtime_jars]))
    compiled = subprocess.run(
        [str(java), "-cp", os.pathsep.join(map(str, compiler_tools)), "scala.tools.nsc.Main",
         "-classpath", classpath, "-d", str(classes), str(probe_source)],
        capture_output=True, text=True, timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    fixture = _fixture()
    cases_path = run / "remap-cases.json"
    cases_path.write_text(json.dumps(fixture, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    result = subprocess.run(
        [str(java), "-cp", str(classes) + os.pathsep + classpath,
         "EeRemapKernelProbe", str(cases_path)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    expected = f"REMAP_KERNEL_OK cases={len(fixture['cases'])} invalid_specs={len(fixture['invalid_specs'])} invalid_pixels=3"
    assert expected in result.stdout

    result_path = run / "remap-result.json"
    result_path.write_text(json.dumps({
        "scope": "Trusted standalone GeoTrellis tile kernel; no SparkContext, service, sandbox task or real data",
        "stdout": result.stdout,
        "stderr": result.stderr,
        "case_count": len(fixture["cases"]),
        "invalid_spec_count": len(fixture["invalid_specs"]),
        "invalid_pixel_count": 3,
        "probe_source_sha256": hashlib.sha256(probe_source.read_bytes()).hexdigest(),
        "manifest": manifest,
    }, indent=2) + "\n", encoding="utf-8")
    audit_dir = os.environ.get("GEE_AUDIT_DIR")
    if audit_dir:
        target = Path(audit_dir)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cases_path, target / "remap-cases.json")
        shutil.copy2(result_path, target / "remap-result.json")
        shutil.copy2(jar.with_suffix(jar.suffix + ".manifest.json"),
                     target / "remap-adapter.manifest.json")
