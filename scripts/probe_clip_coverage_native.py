"""Run the source-attested native clip-coverage tile and sampling-kernel probe."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from scripts import ee_audit_native_manifest as native_manifest
from scripts.ee_audit_native_manifest import validate_native_manifest
from scripts.build_integer_adapter import sha256 as builder_sha256
from ee_kernel_subprocess import run_bounded


PROBE_SOURCE = ROOT / "tests/fixtures/ee-clip-coverage-kernel-probe.scala"
DEFAULT_FIXTURE = ROOT / "tests/fixtures/ee-geodesic-clip-wave70-v1.json"
DEFAULT_MANIFEST = getattr(
    native_manifest,
    "CURRENT_ADAPTER_MANIFEST",
    ROOT / "audit/gee-python-wave70/native/final-1/local-ee-clip-coverage-adapter.jar.manifest.json",
)
DEFAULT_OUTPUT = ROOT / "audit/gee-python-wave70/native/tile-receipt-v4.json"
EXPECTED_ADAPTER = "local-ee-mask-weights-audit-adapter"
MAX_FIXTURE_BYTES = 1_000_000
MAX_RESULT_BYTES = 2_000_000
PREFIX = "EE_CLIP_COVERAGE_TILE_RESULT "


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_tile_result(result: object, fixture_hash: str) -> dict:
    if type(result) is not dict or result.get("schema") != "local-ee-clip-coverage-native-tile-result/v1":
        raise ValueError("native probe returned an unexpected tile result schema")
    if result.get("producer") != "local.ee.reduce.EeClipCoverageKernelProbe":
        raise ValueError("native probe producer identity is not attested")
    if result.get("fixture_schema") != "local-ee-geodesic-clip-wave70/v1":
        raise ValueError("native probe did not use the approved geodesic clip fixture")
    if result.get("fixture_sha256") != fixture_hash:
        raise ValueError("native probe fixture hash differs from the supplied fixture")

    grid = result.get("grid")
    if (type(grid) is not dict or grid.get("kind") != "synthetic-kernel-grid"
            or grid.get("crs") != "EPSG:32647"
            or (grid.get("columns"), grid.get("rows"), grid.get("tile_cols"), grid.get("tile_rows"))
            != (8, 8, 8, 8)):
        raise ValueError("native probe source grid identity or shape is invalid")

    for name in ("raw_source_values_row_major", "coverage_values_row_major",
                 "clipped_science_values_row_major", "unary_absolute_science_values_row_major",
                 "scalar_multiply_2_science_values_row_major"):
        values = result.get(name)
        if type(values) is not list or len(values) != 64:
            raise ValueError(f"native probe {name} is not an actual 8x8 tile array")
    coverage = result["coverage_values_row_major"]
    if any(type(value) not in (float, int) or not 0.0 <= value <= 1.0 for value in coverage):
        raise ValueError("native coverage tile contains a missing or out-of-range weight")
    invariants = result.get("tile_invariants")
    if (type(invariants) is not dict or invariants.get("source_nodata_cell_coverage_zero") is not True
            or invariants.get("fractional_coverage_keeps_raw_science_bits") is not True
            or invariants.get("zero_coverage_masks_science") is not True
            or invariants.get("nonpolar_intermediate_rejected") is not True
            or invariants.get("partial_coverage_cells", 0) <= 0):
        raise ValueError("native clip coverage tile invariants were not demonstrated")

    samples = result.get("sample_rows")
    required_rows = (
        "explicit_roi_clip_sample_drop_nulls_false",
        "explicit_roi_clip_sample_drop_nulls_true",
        "explicit_roi_mask_getter_sample_drop_nulls_false",
        "source_footprint_default_sample_drop_nulls_true",
        "source_footprint_unary_absolute_sample_drop_nulls_true",
        "source_footprint_scalar_multiply_2_sample_drop_nulls_true",
    )
    if type(samples) is not dict or set(samples) != set(required_rows):
        raise ValueError("native sample outputs do not match the declared explicit/default routes")
    route_tiles = {
        "explicit_roi_clip_sample_drop_nulls_false": result["clipped_science_values_row_major"],
        "explicit_roi_clip_sample_drop_nulls_true": result["clipped_science_values_row_major"],
        "explicit_roi_mask_getter_sample_drop_nulls_false": coverage,
        "source_footprint_default_sample_drop_nulls_true": result["clipped_science_values_row_major"],
        "source_footprint_unary_absolute_sample_drop_nulls_true": result["unary_absolute_science_values_row_major"],
        "source_footprint_scalar_multiply_2_sample_drop_nulls_true": result["scalar_multiply_2_science_values_row_major"],
    }
    route_keysets: dict[str, set[tuple[int, int, int]]] = {}
    for route in required_rows:
        rows = samples[route]
        if type(rows) is not list:
            raise ValueError(f"native sample output {route} is not an actual row array")
        keys: set[tuple[int, int, int]] = set()
        for row in rows:
            if type(row) is not dict or set(row) != {"feature", "row", "col", "x", "y", "values"}:
                raise ValueError(f"native sample output {route} contains a malformed sample row")
            if (type(row["feature"]) is not int or type(row["row"]) is not int
                    or type(row["col"]) is not int or type(row["values"]) is not list
                    or len(row["values"]) != 1):
                raise ValueError(f"native sample output {route} has invalid key/value types")
            if any(type(row[key]) not in (int, float) for key in ("x", "y")):
                raise ValueError(f"native sample output {route} has invalid WGS84 centers")
            value = row["values"][0]
            if value is not None and type(value) not in (int, float):
                raise ValueError(f"native sample output {route} has a non-numeric science value")
            if (row["feature"] != 0 or not 0 <= row["row"] < 8 or not 0 <= row["col"] < 8):
                raise ValueError(f"native sample output {route} has a key outside the actual 8x8 tile")
            key = (row["feature"], row["row"], row["col"])
            if key in keys:
                raise ValueError(f"native sample output {route} repeats a source cell")
            keys.add(key)
            expected = route_tiles[route][row["row"] * 8 + row["col"]]
            if value != expected:
                raise ValueError(f"native sample output {route} differs from its producer tile cell")
        route_keysets[route] = keys

    explicit_false = route_keysets["explicit_roi_clip_sample_drop_nulls_false"]
    explicit_true = route_keysets["explicit_roi_clip_sample_drop_nulls_true"]
    if not explicit_false or route_keysets["explicit_roi_mask_getter_sample_drop_nulls_false"] != explicit_false:
        raise ValueError("explicit ROI science and mask samples do not cover the same center-selected cells")
    clipped = result["clipped_science_values_row_major"]
    expected_explicit_true = {
        key for key in explicit_false if clipped[key[1] * 8 + key[2]] is not None
    }
    if explicit_true != expected_explicit_true:
        raise ValueError("explicit ROI dropNulls=true rows do not match valid science cells from dropNulls=false")
    for route in (
        "source_footprint_default_sample_drop_nulls_true",
        "source_footprint_unary_absolute_sample_drop_nulls_true",
        "source_footprint_scalar_multiply_2_sample_drop_nulls_true",
    ):
        tile_values = route_tiles[route]
        expected_cells = {
            (0, row, col)
            for row in range(8)
            for col in range(8)
            if tile_values[row * 8 + col] is not None
        }
        if route_keysets[route] != expected_cells:
            raise ValueError(f"default dropNulls=true route {route} omitted or invented valid source cells")

    controls = result.get("independent_numeric_reference_controls")
    if type(controls) is not list or len(controls) < 10:
        raise ValueError("native probe omitted its independent geometry/numeric controls")
    names = {row.get("id") for row in controls if type(row) is dict}
    if not {"meridian_half", "meridian_touch_zero", "meridian_near_touch_positive_2^-52",
            "hole_contains_center", "multipart_disjoint", "tiny_positive_2^-31",
            "high_latitude_outside_center", "equator_inflection_half_cell",
            "utm_32n_native_cell", "web_mercator_native_cell"}.issubset(names):
        raise ValueError("native probe omitted one or more fixed independent controls")
    for row in controls:
        actual, reference, tolerance = (row.get("actual_native_fraction"),
                                        row.get("separate_reference_fraction"), row.get("tolerance"))
        if (any(type(value) not in (float, int) for value in (actual, reference, tolerance))
                or abs(actual - reference) > tolerance):
            raise ValueError("native probe output disagrees with its separately labeled reference")

    admission = result.get("default_256_admission_probe")
    if (type(admission) is not dict
            or admission.get("label") != "synthetic-256x256-one-degree-EPSG4326-grid"
            or (admission.get("tile_cols"), admission.get("tile_rows")) != (256, 256)
            or admission.get("observed_time_count") != 1
            or admission.get("admitted") is not True
            or admission.get("max_work") != 67108864
            or type(admission.get("geometry_segments")) is not int
            or admission["geometry_segments"] <= 0
            or type(admission.get("bbox_candidate_visits")) is not int
            or not 0 <= admission["bbox_candidate_visits"] <= 1_000_000
            or type(admission.get("unique_global_boundary_cells")) is not int
            or not 0 <= admission["unique_global_boundary_cells"] <= 1_000_000
            or type(admission.get("actual_positive_coverage_cells")) is not int
            or admission["actual_positive_coverage_cells"] <= 0
            or type(admission.get("actual_partial_coverage_cells")) is not int
            or admission["actual_partial_coverage_cells"] <= 0
            or type(admission.get("charged_boundary_cells")) is not str
            or type(admission.get("total_work")) is not str):
        raise ValueError("native probe omitted an admitted 256x256 production-budget control")
    try:
        charged_boundary_cells = int(admission["charged_boundary_cells"])
        total_work = int(admission["total_work"])
        full_cover_plan_bound = int(admission["full_layout_cover_plan_boundary_bound"])
        full_cover_charged_cells = int(admission["full_layout_cover_charged_boundary_cells"])
    except (TypeError, ValueError) as error:
        raise ValueError("native 256x256 budget counts are not decimal integers") from error
    weight_sum = admission.get("actual_coverage_weight_sum")
    if (not 0 <= charged_boundary_cells <= 100_000_000
            or charged_boundary_cells < admission["actual_partial_coverage_cells"]
            or not 0 <= total_work <= admission["max_work"]
            or full_cover_plan_bound != 0 or full_cover_charged_cells != 0
            or admission.get("full_layout_cover_actual_cells") != 256 * 256
            or type(weight_sum) not in (float, int) or not math.isfinite(weight_sum)
            or weight_sum <= 0.0):
        raise ValueError("native 256x256 budget or actual tile summaries are out of bounds")
    return result


def _is_child(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def run_probe(manifest_path: Path, fixture_path: Path, output_path: Path) -> dict:
    checked = validate_native_manifest(
        manifest_path.expanduser().resolve(strict=True), expected_adapter=EXPECTED_ADAPTER,
    )
    fixture_path = fixture_path.expanduser().resolve(strict=True)
    fixture_bytes = fixture_path.read_bytes()
    if len(fixture_bytes) > MAX_FIXTURE_BYTES:
        raise ValueError(f"clip fixture exceeds {MAX_FIXTURE_BYTES} bytes")
    fixture = json.loads(fixture_bytes)
    if (type(fixture) is not dict or fixture.get("schema") != "local-ee-geodesic-clip-wave70/v1"
            or type(fixture.get("expected_clip_coverage_contract")) is not dict):
        raise ValueError("fixture does not satisfy local-ee-geodesic-clip-wave70/v1")
    if not PROBE_SOURCE.is_file():
        raise FileNotFoundError(PROBE_SOURCE)

    java = checked["java"]
    jar = checked["jar"]
    scala_tools = checked["scala_tools"]
    runtime_jars = checked["runtime_jars"]
    compiler_cp = os.pathsep.join(map(str, scala_tools))
    runtime_cp = os.pathsep.join(map(str, [jar, *runtime_jars]))
    with tempfile.TemporaryDirectory(prefix="local-ee-clip-coverage-probe-") as directory:
        scratch = Path(directory)
        source_path = scratch / "EeClipCoverageKernelProbe.scala"
        fixture_copy = scratch / "ee-geodesic-clip-wave70-v1.json"
        classes = scratch / "classes"
        classes.mkdir()
        source_path.write_bytes(PROBE_SOURCE.read_bytes())
        fixture_copy.write_bytes(fixture_bytes)
        compile_result = run_bounded(
            [str(java), "-cp", compiler_cp, "scala.tools.nsc.Main",
             "-classpath", runtime_cp, "-d", str(classes), str(source_path)],
            cwd=str(ROOT), timeout=150,
        )
        if compile_result.returncode != 0:
            raise RuntimeError(f"Scala clip coverage probe compile failed: {compile_result.stderr}")
        started = time.monotonic()
        executed = run_bounded(
            [str(java), "-cp", str(classes) + os.pathsep + runtime_cp,
             "local.ee.reduce.EeClipCoverageKernelProbe", str(fixture_copy)],
            cwd=str(ROOT), timeout=120,
        )
        elapsed = time.monotonic() - started
        if executed.returncode != 0:
            raise RuntimeError(f"native clip coverage kernel probe failed: {executed.stderr or executed.stdout}")
        line = next((value for value in executed.stdout.splitlines() if value.startswith(PREFIX)), None)
        if line is None or len(line.encode("utf-8")) > MAX_RESULT_BYTES:
            raise RuntimeError("native clip coverage probe emitted no bounded result record")
        tile_result = validate_tile_result(json.loads(line[len(PREFIX):]), sha256_bytes(fixture_bytes))

    manifest = checked["manifest"]
    receipt = {
        "schema": "local-ee-clip-coverage-native-probe-receipt/v1",
        "manifest_path": str(checked["manifest_path"]),
        "manifest_format": manifest["format"],
        "manifest_adapter_label": manifest["adapter"],
        "deployment_eligible": manifest["deployment_eligible"],
        "manifest_jar": str(jar),
        "manifest_jar_sha256": manifest["jar_sha256"],
        "builder_sha256": builder_sha256(ROOT / "scripts/build_integer_adapter.py"),
        "probe_source": str(PROBE_SOURCE.relative_to(ROOT)),
        "probe_source_sha256": builder_sha256(PROBE_SOURCE),
        "fixture_path": str(fixture_path.relative_to(ROOT)),
        "fixture_sha256": sha256_bytes(fixture_bytes),
        "elapsed_seconds": round(elapsed, 3),
        "native_tile_result": tile_result,
        "scope": "Offline actual-tile probe only; synthetic raster, trusted kernels and sample rows. "
                 "No build, service, SparkContext, Google request, private data, or deployment action is implied.",
    }
    encoded = (json.dumps(receipt, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode()
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValueError("clip coverage native receipt exceeds its 2 MB limit")
    output_path = output_path.expanduser().resolve()
    audit_root = (ROOT / "audit").resolve()
    if not _is_child(output_path, audit_root):
        raise ValueError("clip coverage probe output must remain under ROOT/audit")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".clip-coverage-", dir=output_path.parent,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
        # Link within the destination directory to publish atomically without
        # replacing an earlier receipt, including on a concurrent rerun.
        os.link(temporary, output_path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                        help="current source-attested audit manifest for the native adapter")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="receipt path under the ignored audit tree")
    args = parser.parse_args()
    receipt = run_probe(args.manifest, args.fixture, args.output)
    print(json.dumps({key: receipt[key] for key in (
        "schema", "manifest_path", "manifest_jar_sha256", "fixture_sha256",
        "probe_source_sha256", "elapsed_seconds", "scope")}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
