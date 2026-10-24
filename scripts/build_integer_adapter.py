"""Build the independent Local EE GeoTrellis SPI adapter.

The adapter is deliberately excluded from the upstream engine JAR lock. Build
to an explicit path, normally `.native/jars/local-ee-integer-adapter.jar`, and
retain the adjacent JSON manifest as the local source/artifact digest record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "engine/ee_integer_adapter.scala"
SOURCES = [SOURCE, ROOT / "engine/ee_cell_conversion.scala", ROOT / "engine/ee_grid_adapter.scala", ROOT / "engine/ee_mask_adapter.scala",
           ROOT / "engine/ee_reduce_support.scala", ROOT / "engine/ee_reduce_numeric.scala",
           ROOT / "engine/ee_reduce_statistics.scala",
           ROOT / "engine/ee_reduce_adapter.scala", ROOT / "engine/ee_classify_numeric.scala",
           ROOT / "engine/ee_classify_model.scala", ROOT / "engine/ee_classify_adapter.scala",
           ROOT / "engine/ee_sample_kernel.scala", ROOT / "engine/ee_sample_adapter.scala"]
SOURCES += [ROOT / "engine/ee_remap_numeric.scala", ROOT / "engine/ee_remap_adapter.scala"]
SOURCES += [ROOT / "engine/ee_image_sample_options.scala",
            ROOT / "engine/ee_image_sample_kernel.scala", ROOT / "engine/ee_image_sample_adapter.scala"]
SOURCES += [ROOT / "engine/ee_pixel_math_numeric.scala", ROOT / "engine/ee_pixel_math_adapter.scala"]
SOURCES += [ROOT / "engine/ee_integer_values_spec.scala", ROOT / "engine/ee_integer_values_numeric.scala",
            ROOT / "engine/ee_integer_values_adapter.scala", ROOT / "engine/ee_float64_values.scala"]
SOURCES += [ROOT / "engine/ee_matrix_values_spec.scala", ROOT / "engine/ee_matrix_values_numeric.scala",
            ROOT / "engine/ee_matrix_orthogonal.scala", ROOT / "engine/ee_matrix_svd_native.scala",
            ROOT / "engine/ee_matrix_svd_jacobi.scala", ROOT / "engine/ee_matrix_orthogonal_rank.scala",
            ROOT / "engine/ee_matrix_orthogonal_budget.scala",
            ROOT / "engine/ee_matrix_factorization.scala", ROOT / "engine/ee_matrix_factorization_budget.scala",
            ROOT / "engine/ee_matrix_values_adapter.scala"]
SOURCES += [ROOT / "engine/ee_unmix_spec.scala", ROOT / "engine/ee_unmix_rank.scala",
            ROOT / "engine/ee_unmix_solver.scala",
            ROOT / "engine/ee_unmix_numeric.scala", ROOT / "engine/ee_unmix_budget.scala",
            ROOT / "engine/ee_unmix_adapter.scala"]
SOURCES += [ROOT / "engine/ee_focal_spec.scala", ROOT / "engine/ee_focal_numeric.scala",
            ROOT / "engine/ee_focal_adapter.scala"]
SOURCES += [ROOT / "engine/ee_convolve_spec.scala", ROOT / "engine/ee_convolve_numeric.scala",
            ROOT / "engine/ee_convolve_adapter.scala"]
SOURCES += [ROOT / "engine/ee_terrain_spec.scala", ROOT / "engine/ee_terrain_budget.scala",
            ROOT / "engine/ee_terrain_metric.scala", ROOT / "engine/ee_terrain_numeric.scala",
            ROOT / "engine/ee_terrain_adapter.scala"]
SOURCES += [ROOT / "engine/ee_neighborhood_spec.scala", ROOT / "engine/ee_neighborhood_budget.scala",
            ROOT / "engine/ee_neighborhood_exact.scala", ROOT / "engine/ee_neighborhood_statistics.scala",
            ROOT / "engine/ee_neighborhood_numeric.scala", ROOT / "engine/ee_neighborhood_adapter.scala"]
SOURCES += [ROOT / "engine/ee_distance_spec.scala", ROOT / "engine/ee_distance_budget.scala",
            ROOT / "engine/ee_distance_numeric.scala", ROOT / "engine/ee_distance_adapter.scala"]
SOURCES += [ROOT / "engine/ee_fast_distance_spec.scala", ROOT / "engine/ee_fast_distance_budget.scala",
            ROOT / "engine/ee_fast_distance_halo.scala", ROOT / "engine/ee_fast_distance_adapter.scala",
            ROOT / "engine/ee_fast_distance_transform.scala",
            ROOT / "engine/ee_fast_distance_transform_envelope.scala"]
SERVICE_NAME = "org.openeo.geotrelliscommon.CubeProcessProvider"
SERVICE_ENTRY = ("local.ee.integer.LocalEeIntegerCubeProcessProvider\n"
                 "local.ee.grid.LocalEeGridCubeProcessProvider\n"
                 "local.ee.mask.LocalEeMaskCubeProcessProvider\n"
                 "local.ee.reduce.LocalEeReduceCubeProcessProvider\n"
                 "local.ee.classify.LocalEeClassifyCubeProcessProvider\n"
                 "local.ee.sample.LocalEeSampleCubeProcessProvider\n")
SERVICE_ENTRY += "local.ee.remap.LocalEeRemapCubeProcessProvider\n"
SERVICE_ENTRY += "local.ee.image.sample.LocalEeImageSampleCubeProcessProvider\n"
SERVICE_ENTRY += "local.ee.math.LocalEePixelMathCubeProcessProvider\n"
SERVICE_ENTRY += "local.ee.reduce.LocalEeIntegerValuesCubeProcessProvider\n"
SERVICE_ENTRY += "local.ee.reduce.LocalEeMatrixValuesCubeProcessProvider\n"
SERVICE_ENTRY += "local.ee.reduce.LocalEeSpectralUnmixCubeProcessProvider\n"

SERVICE_ENTRY += "local.ee.reduce.LocalEeFocalCubeProcessProvider\n"
SERVICE_ENTRY += "local.ee.reduce.LocalEeConvolveCubeProcessProvider\n"
SERVICE_ENTRY += "local.ee.reduce.LocalEeTerrainCubeProcessProvider\n"
SERVICE_ENTRY += "local.ee.reduce.LocalEeDistanceCubeProcessProvider\n"
SERVICE_ENTRY += "local.ee.reduce.LocalEeFastDistanceCubeProcessProvider\n"
SERVICE_ENTRY += "local.ee.reduce.LocalEeNeighborhoodCubeProcessProvider\n"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _engine_paths() -> tuple[Path, Path, list[Path], list[Path], dict[str, str]]:
    native = ROOT / ".native"
    lock = json.loads((native / "engine-lock.json").read_text())
    java_home = Path(lock["java_home"])
    java = java_home / "bin/java"
    jar_tool = java_home / "bin/jar"
    if not java.is_file() or not jar_tool.is_file():
        raise RuntimeError(f"Locked Java runtime is unavailable: {java_home}")
    spark_jars = native / "engine/lib/python3.11/site-packages/pyspark/jars"
    scala_compiler = sorted(spark_jars.glob("scala-compiler-*.jar"))
    scala_library = sorted(spark_jars.glob("scala-library-*.jar"))
    scala_reflect = sorted(spark_jars.glob("scala-reflect-*.jar"))
    if not (len(scala_compiler) == len(scala_library) == len(scala_reflect) == 1):
        raise RuntimeError("Expected exactly one pinned Scala compiler/library/reflect JAR")
    locked_jars = lock.get("jars")
    if not isinstance(locked_jars, dict):
        raise RuntimeError("Native engine lock does not contain the expected JAR digest map")
    native_jars = []
    for name, expected_digest in sorted(locked_jars.items()):
        if name.startswith('local-ee-'):
            raise RuntimeError('Local adapters must have separate manifests, not appear in the upstream engine lock')
        path = native / "jars" / name
        if not path.is_file():
            raise RuntimeError(f"Locked engine JAR is missing: {name}")
        actual_digest = sha256(path)
        if actual_digest != expected_digest:
            raise RuntimeError(f"Locked engine JAR SHA-256 mismatch: {name}")
        native_jars.append(path)
    if not any("geotrellis-extensions" in p.name for p in native_jars):
        raise RuntimeError("Locked engine JAR set has no GeoTrellis extensions JAR")
    if not any("geotrellis-dependencies" in p.name for p in native_jars):
        raise RuntimeError("Locked engine JAR set has no GeoTrellis dependencies JAR")
    runtime_jars = sorted(spark_jars.glob("*.jar")) + native_jars
    return java, jar_tool, [scala_compiler[0], scala_library[0], scala_reflect[0]], runtime_jars, locked_jars


def _run(args: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT, env=env)


def build(output: Path) -> dict:
    for source in SOURCES:
        if not source.is_file():
            raise RuntimeError(f"Adapter source is missing: {source}")
    java, jar_tool, scala_tools, runtime_jars, locked_jars = _engine_paths()
    math_dependencies = [path for path in runtime_jars if path.name.startswith("commons-math3-")]
    if len(math_dependencies) != 1:
        raise RuntimeError("Expected exactly one existing Apache Commons Math 3 JAR")
    math_dependency = math_dependencies[0]
    if (math_dependency.name != "commons-math3-3.6.1.jar"
            or sha256(math_dependency) != "1e56d7b058d28b65abd256b8458e3885b674c1d588fa43cd7d1cbb9c7ef2b308"):
        raise RuntimeError("Apache Commons Math dependency does not match the audited 3.6.1 digest")
    engine_lock = json.loads((ROOT / ".native/engine-lock.json").read_text())
    scala_version = scala_tools[1].stem.rsplit("-", 1)[-1]
    java_home = java.parent.parent
    compile_cp = os.pathsep.join(str(path) for path in runtime_jars)
    compiler_cp = os.pathsep.join(str(path) for path in scala_tools)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    with tempfile.TemporaryDirectory(prefix=".local-ee-integer-adapter-", dir=output.parent) as temporary:
        temporary_path = Path(temporary)
        classes = temporary_path / "classes"
        staged_jar = temporary_path / output.name
        staged_manifest = temporary_path / manifest_path.name
        services = classes / "META-INF/services"
        classes.mkdir()
        services.mkdir(parents=True)
        (services / SERVICE_NAME).write_text(SERVICE_ENTRY, encoding="utf-8")
        compiler = [
            java, "-cp", compiler_cp, "scala.tools.nsc.Main",
            "-classpath", compile_cp, "-d", classes, *SOURCES,
        ]
        _run(compiler, env={**os.environ, "JAVA_HOME": str(java_home)})
        _run([jar_tool, "--create", "--file", staged_jar, "-C", classes, "."],
             env={**os.environ, "JAVA_HOME": str(java_home)})
        manifest = {
            "format": "local-ee-native-adapter-v1",
            "adapter": "local-ee-integer-adapter",
            "source": str(SOURCE.relative_to(ROOT)),
            "source_sha256": sha256(SOURCE),
            "sources": {str(path.relative_to(ROOT)): sha256(path) for path in SOURCES},
            "build_script": str(Path(__file__).resolve().relative_to(ROOT)),
            "build_script_sha256": sha256(Path(__file__).resolve()),
            "jar": str(output),
            "jar_sha256": sha256(staged_jar),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "java_home": str(java_home),
            "scala_version": scala_version,
            "spark_version": engine_lock["spark"],
            "upstream_jars": locked_jars,
            "math_dependencies": {math_dependency.name: sha256(math_dependency)},
            "services": {SERVICE_NAME: SERVICE_ENTRY.strip()},
        }
        staged_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        staged_manifest.chmod(0o600)
        os.replace(staged_jar, output)
        os.replace(staged_manifest, manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="destination for the independently locked adapter JAR")
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))


if __name__ == "__main__":
    main()
