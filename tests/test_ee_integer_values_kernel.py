"""Independent contracts and opt-in standalone GeoTrellis checks for integer values."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from ee_integer_values_kernel_helpers import OPERATIONS, binary64_hex, make_fixture, reference
from ee_kernel_subprocess import run_bounded


ROOT = Path(__file__).resolve().parents[1]
NATIVE_SOURCES = (
    "engine/ee_cell_conversion.scala",
    "engine/ee_reduce_support.scala",
    "engine/ee_integer_values_spec.scala",
    "engine/ee_integer_values_numeric.scala",
    "engine/ee_integer_values_adapter.scala",
)


def _case(fixture: dict, name: str) -> dict:
    return next(row for row in fixture["cases"] if row["name"] == name)


def _decoded_expected(case: dict) -> list[float | None]:
    return [None if value == "NaN" else float.fromhex(value) for value in case["expected"]]


def test_integer_values_fixture_is_deterministic_and_covers_each_op_and_cast_dtype():
    fixture = make_fixture()
    assert fixture == make_fixture()
    assert fixture["schema"] == "local-ee-integer-values-synthetic/v1"
    assert fixture["operation_count"] == len(OPERATIONS) == 14
    assert fixture["case_count"] == len(fixture["cases"])
    assert fixture["pixel_count"] == sum(len(row["expected"]) for row in fixture["cases"])
    assert {json.loads(row["spec"])["op"] for row in fixture["cases"]} == set(OPERATIONS)
    assert {json.loads(row["spec"])["dtype"] for row in fixture["cases"]
            if json.loads(row["spec"])["op"] == "cast"} == {
                "int8", "uint8", "int16", "uint16", "int32", "uint32", "int64",
            }
    assert {row["input_type"] for row in fixture["cases"]} == {
        "double", "byte", "short", "int", "ubyte", "ushort",
    }
    assert all(reference(row) == _decoded_expected(row) for row in fixture["cases"])


def test_integer_oracle_covers_twos_complement_limits_casts_and_binary64_comparisons():
    fixture = make_fixture()
    assert _decoded_expected(_case(fixture, "bit-count-uses-signed-64-bit-two-complement")) == [
        0.0, 1.0, 64.0, 57.0, 1.0, 11.0, None,
    ]
    assert _decoded_expected(_case(fixture, "left-shift-signed-and-count-boundaries")) == [
        -float(1 << 53), -float(1 << 41), 1.0, float(1 << 31),
        float(1 << 53), -float(1 << 53), None,
    ]
    assert _decoded_expected(_case(fixture, "right-shift-arithmetic-and-large-counts")) == [
        -1.0, -2.0, -1.0, 1.0, -1.0, 0.0, None,
    ]
    assert _decoded_expected(_case(fixture, "byte-valid-minus-128-is-not-nodata")) == [
        128.0, 127.0,
    ]
    assert _decoded_expected(_case(fixture, "int-valid-minimum-is-not-nodata")) == [
        float((1 << 31) - 1), -float(1 << 31),
    ]
    assert _decoded_expected(_case(fixture, "compare-negative-zero-constant")) == [
        1.0, 1.0, 0.0, 0.0, None,
    ]
    for operation in ("eq", "neq", "lt", "lte", "gt", "gte"):
        case = _case(fixture, f"compare-float64-signed-zero-subnormal-extremes-{operation}")
        assert _decoded_expected(case) == reference(case)
        assert len(case["expected"]) == 11

    int64 = _decoded_expected(_case(fixture, "cast-int64-exact-binary64-domain"))
    assert int64 == [-float(1 << 53), -1.0, 0.0, float(1 << 53), None]
    assert _decoded_expected(_case(fixture, "cast-clamp-truncate-uint32"))[0] == 0.0
    assert _decoded_expected(_case(fixture, "cast-clamp-truncate-uint32"))[-2] == float((1 << 32) - 1)


def test_masks_invalid_values_and_composite_qa_reference_are_explicit():
    fixture = make_fixture()
    equality = _case(fixture, "compare-float64-signed-zero-subnormal-extremes-eq")
    assert _decoded_expected(equality)[9:] == [None, None]
    assert len(fixture["invalid_specs"]) >= 30
    assert len(fixture["invalid_tile_cases"]) >= 8
    assert {row["name"] for row in fixture["masked_constant_cases"]} >= {
        "fractional-bit-constant-with-masked-band",
        "fractional-shift-constant-with-masked-band",
        "out-of-range-shift-constant-with-masked-band",
        "negative-shift-constant-with-masked-band",
        "out-of-domain-bit-constant-with-masked-band",
    }
    assert {row["name"] for row in fixture["invalid_tile_cases"]} >= {
        "fractional-bit-input", "left-shift-result-overflow", "bit-not-result-overflow",
        "negative-shift-count", "fractional-shift-count", "source-positive-infinity",
        "source-negative-infinity", "int64-cast-result-overflow",
    }

    qa = fixture["qa_composite"]
    raw = [None if value == "NaN" else float.fromhex(value) for value in qa["raw_scl"]]
    expected_from_raw_labels = [
        None if value is None else (0.0 if value in {4.0, 5.0, 6.0} else 1.0)
        for value in raw
    ]
    assert _decoded_expected({"expected": qa["expected_clear"]}) == expected_from_raw_labels
    assert qa["steps"] == [
        "eq4", "shift10", "eq5", "shift11", "or45", "eq6",
        "shift40", "or_highbit", "mask_bits", "eq_zero",
    ]
    assert json.loads(qa["specs"]["mask_bits"])["operands"][1]["constant"] == binary64_hex(
        (1 << 40) | (1 << 11) | (1 << 10)
    )
    assert {json.loads(value)["op"] for value in qa["specs"].values()} == {
        "eq", "left_shift", "bit_or", "bit_and",
    }


def test_native_sources_expose_the_bounded_numeric_api_and_manifest_registration():
    sources = {name: (ROOT / name).read_text(encoding="utf-8") for name in NATIVE_SOURCES}
    numeric = sources["engine/ee_integer_values_numeric.scala"]
    spec = sources["engine/ee_integer_values_spec.scala"]
    adapter = sources["engine/ee_integer_values_adapter.scala"]
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text(encoding="utf-8")
    probe = (ROOT / "scripts/probe_integer_values_native.py").read_text(encoding="utf-8")

    assert "def applyTile(input: MultibandTile, spec: LocalEeIntegerValuesSpec.Value): Tile" in numeric
    assert "LocalEeReduceSupport.copyAsDouble(input, spec.inputBands, cols, rows)" in numeric
    assert "MaxSafeIntegerBig" in numeric and "Math.rint(value)" in numeric
    assert "java.lang.Long.bitCount(asLong(left))" in numeric
    assert "value.isNaN || value.isFinite" in (ROOT / "engine/ee_reduce_support.scala").read_text()
    assert "STRICT_DUPLICATE_DETECTION" in spec
    assert 'text == canonicalJson(result)' in spec
    assert "validateIntegerConstants" in spec or "validateConstant" in spec
    assert 'id = "local_ee_integer_values"' in adapter
    assert "LocalEeIntegerValuesSpec.parse(wire)" in adapter
    for source in NATIVE_SOURCES:
        assert source in builder
    assert "LocalEeIntegerValuesCubeProcessProvider" in builder
    assert "LocalEeIntegerValuesNumeric.applyTile" in probe
    assert "PROBE_SOURCE_PATH = ROOT / \"tests/fixtures/ee-integer-values-kernel-probe.scala\"" in probe
    assert (ROOT / "tests/fixtures/ee-integer-values-kernel-probe.scala").is_file()
    assert "import org.apache.spark.SparkContext" not in probe
    assert "new SparkContext" not in probe and "ServiceLoader.load" not in probe


def _write_current_source_manifest(tmp_path: Path) -> Path:
    from scripts.build_integer_adapter import SERVICE_ENTRY, SERVICE_NAME, SOURCES
    from scripts.probe_integer_values_native import sha256

    jar = tmp_path / "fake-local-adapter.jar"
    jar.write_bytes(b"synthetic portable manifest-control artifact")
    sources = {
        str(path.relative_to(ROOT)): sha256(path)
        for path in SOURCES
    }
    manifest = {
        "adapter": "local-ee-integer-adapter",
        "build_script_sha256": sha256(ROOT / "scripts/build_integer_adapter.py"),
        "jar": str(jar),
        "jar_sha256": sha256(jar),
        "services": {SERVICE_NAME: SERVICE_ENTRY.strip()},
        "sources": sources,
    }
    path = tmp_path / "fake-local-adapter.manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_native_manifest_requires_exact_current_build_source_set(tmp_path):
    from scripts.build_integer_adapter import SOURCES
    from scripts.probe_integer_values_native import _checked_manifest

    manifest_path = _write_current_source_manifest(tmp_path)
    manifest, jar = _checked_manifest(manifest_path)
    expected = {str(path.relative_to(ROOT)) for path in SOURCES}
    assert set(manifest["sources"]) == expected
    assert jar.read_bytes() == b"synthetic portable manifest-control artifact"

    for omission in ("engine/ee_integer_adapter.scala", "engine/ee_reduce_support.scala"):
        damaged = json.loads(manifest_path.read_text(encoding="utf-8"))
        del damaged["sources"][omission]
        manifest_path.write_text(json.dumps(damaged), encoding="utf-8")
        with pytest.raises(ValueError, match="source set differs"):
            _checked_manifest(manifest_path)

    damaged = json.loads(_write_current_source_manifest(tmp_path).read_text(encoding="utf-8"))
    damaged["sources"]["unexpected.scala"] = "0" * 64
    manifest_path.write_text(json.dumps(damaged), encoding="utf-8")
    with pytest.raises(ValueError, match="source set differs"):
        _checked_manifest(manifest_path)


@pytest.mark.parametrize("relative", [
    "engine/ee_cell_conversion.scala",
    "engine/ee_reduce_support.scala",
])
def test_native_manifest_rejects_tampered_shared_source_digest_without_jvm(tmp_path, relative):
    from scripts.probe_integer_values_native import _checked_manifest

    manifest_path = _write_current_source_manifest(tmp_path)
    damaged = json.loads(manifest_path.read_text(encoding="utf-8"))
    digest = damaged["sources"][relative]
    damaged["sources"][relative] = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    manifest_path.write_text(json.dumps(damaged), encoding="utf-8")
    with pytest.raises(ValueError, match=relative.replace(".", r"\.")):
        _checked_manifest(manifest_path)


def test_actual_integer_values_tiles_match_independent_oracle_and_composite_scl_chain():
    if os.environ.get("LOCAL_EE_RUN_INTEGER_VALUES_KERNEL_TEST") != "1":
        pytest.skip("opt-in trusted GeoTrellis tile probe; no SparkContext, service, or user code")
    manifest = os.environ.get("LOCAL_EE_INTEGER_VALUES_ADAPTER_MANIFEST")
    if not manifest:
        pytest.skip("native integer-values probe needs LOCAL_EE_INTEGER_VALUES_ADAPTER_MANIFEST")

    result = run_bounded(
        [sys.executable, str(ROOT / "scripts/probe_integer_values_native.py"),
         "--manifest", manifest],
        cwd=str(ROOT), timeout=300,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    summary = json.loads(result.stdout)
    assert summary["fixture_schema"] == "local-ee-integer-values-synthetic/v1"
    assert summary["case_count"] == make_fixture()["case_count"]
    assert summary["pixel_count"] == make_fixture()["pixel_count"]
    assert summary["invalid_spec_count"] == len(make_fixture()["invalid_specs"])
    assert summary["invalid_tile_count"] == len(make_fixture()["invalid_tile_cases"])
    assert summary["masked_constant_case_count"] == len(make_fixture()["masked_constant_cases"])
    assert "operations=14" in summary["summary"]
    assert "qa_steps=10" in summary["summary"]
    assert "qa_pixels=13" in summary["summary"]
    assert "cell_conversion_checks=5" in summary["summary"]
