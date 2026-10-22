"""Build the separately locked native Smile 1.5.3 random-forest SPI adapter.

All inputs are explicit local files. This builder never downloads dependencies
and writes only below the dedicated Wave26 work scratch directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORK_ROOT = ROOT.parents[1] / "work" / "gee-python-wave26-native"
LOCK_PATH = ROOT / "deploy/smile-rf-lock.json"
SOURCES = [
    ROOT / "engine/ee_smile_rf_wire.scala",
    ROOT / "engine/ee_smile_rf_factory.scala",
    ROOT / "engine/ee_smile_rf_numeric.scala",
    ROOT / "engine/ee_smile_rf_adapter.scala",
]
SERVICE_NAME = "org.openeo.geotrelliscommon.CubeProcessProvider"
SERVICE_ENTRY = "local.ee.smile.LocalEeSmileRfCubeProcessProvider\n"
BASE_FORMAT = "local-ee-native-adapter-v1"
BASE_ADAPTER = "local-ee-integer-adapter"
ADAPTER_ID = "local-ee-smile-rf-adapter"
SLF4J_API_CLASSES = {
    "org/slf4j/Logger.class",
    "org/slf4j/LoggerFactory.class",
    "org/slf4j/ILoggerFactory.class",
}
SMILE_ARTIFACTS = {
    "smile-core-1.5.3.jar": "com.github.haifengl:smile-core:1.5.3",
    "smile-data-1.5.3.jar": "com.github.haifengl:smile-data:1.5.3",
    "smile-math-1.5.3.jar": "com.github.haifengl:smile-math:1.5.3",
    "smile-graph-1.5.3.jar": "com.github.haifengl:smile-graph:1.5.3",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot read {label}: {path}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _engine_paths() -> tuple[Path, Path, list[Path], list[Path], dict[str, str], dict]:
    native = ROOT / ".native"
    engine_lock = _read_json(native / "engine-lock.json", "native engine lock")
    java_home = Path(engine_lock.get("java_home", "")).expanduser().resolve()
    java = java_home / "bin/java"
    jar_tool = java_home / "bin/jar"
    if not java.is_file() or not jar_tool.is_file():
        raise RuntimeError(f"Locked Java runtime is unavailable: {java_home}")
    spark_jars = native / "engine/lib/python3.11/site-packages/pyspark/jars"
    scala_tools = []
    for prefix in ("scala-compiler-", "scala-library-", "scala-reflect-"):
        matches = sorted(spark_jars.glob(prefix + "*.jar"))
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one locked {prefix[:-1]} JAR")
        scala_tools.append(matches[0])
    locked_jars = engine_lock.get("jars")
    if not isinstance(locked_jars, dict) or not locked_jars:
        raise RuntimeError("Native engine lock does not contain the expected JAR digest map")
    native_jars = []
    for name, expected_digest in sorted(locked_jars.items()):
        if name.startswith("local-ee-"):
            raise RuntimeError("Local adapters must remain outside the native engine lock")
        path = native / "jars" / name
        if not path.is_file() or sha256(path) != expected_digest:
            raise RuntimeError(f"Locked engine JAR is missing or has a digest mismatch: {name}")
        native_jars.append(path)
    runtime_jars = sorted(spark_jars.glob("*.jar")) + native_jars
    if not any("geotrellis-extensions" in path.name for path in native_jars):
        raise RuntimeError("Locked engine JAR set has no GeoTrellis extensions JAR")
    if not any("geotrellis-dependencies" in path.name for path in native_jars):
        raise RuntimeError("Locked engine JAR set has no GeoTrellis dependencies JAR")
    return java, jar_tool, scala_tools, runtime_jars, locked_jars, engine_lock


def _verify_smile_deps(directory: Path, lock: dict) -> dict[str, Path]:
    deps = directory.expanduser().resolve()
    if not deps.is_dir():
        raise RuntimeError(f"Explicit Smile dependency directory does not exist: {deps}")
    expected = lock.get("smile_jars")
    if not isinstance(expected, dict) or set(expected) != set(SMILE_ARTIFACTS):
        raise RuntimeError("Smile dependency lock must name exactly four JARs")
    actual_jars = {path.name for path in deps.glob("*.jar")}
    if actual_jars != set(expected):
        raise RuntimeError("Dependency directory JAR names must exactly match the four locked Smile artifacts")
    paths = {}
    for filename, record in expected.items():
        coordinate = SMILE_ARTIFACTS[filename]
        artifact = coordinate.split(":")[1]
        url = f"https://repo.maven.apache.org/maven2/com/github/haifengl/{artifact}/1.5.3/{filename}"
        digest = record.get("sha256") if isinstance(record, dict) else None
        if (not isinstance(record, dict) or record.get("coordinate") != coordinate
                or record.get("url") != url or not isinstance(digest, str)
                or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)):
            raise RuntimeError(f"Smile dependency provenance record is invalid: {filename}")
        path = deps / filename
        if not path.is_file() or sha256(path) != digest:
            raise RuntimeError(f"Smile dependency SHA-256 mismatch: {filename}")
        paths[filename] = path
    return paths


def _verify_base(path: Path, manifest_path: Path, runtime: dict, locked_jars: dict) -> dict:
    jar = path.expanduser().resolve()
    manifest_file = manifest_path.expanduser().resolve()
    manifest = _read_json(manifest_file, "base adapter manifest")
    if not jar.is_file() or sha256(jar) != manifest.get("jar_sha256"):
        raise RuntimeError("Base adapter JAR SHA-256 does not match its adjacent manifest")
    if Path(manifest.get("jar", "")).expanduser().resolve() != jar:
        raise RuntimeError("Base adapter manifest identifies a different JAR path")
    if manifest.get("format") != BASE_FORMAT or manifest.get("adapter") != BASE_ADAPTER:
        raise RuntimeError("Base adapter must be the reviewed Local EE integer adapter")
    expected_native = {
        "java_home": runtime["java_home"],
        "scala_version": runtime["scala_version"],
        "spark_version": runtime["spark_version"],
        "upstream_jars": locked_jars,
    }
    for field, expected in expected_native.items():
        if manifest.get(field) != expected:
            raise RuntimeError(f"Base adapter manifest {field} does not match the active pinned runtime")
    base_sources = manifest.get("sources")
    if not isinstance(base_sources, dict) or not base_sources:
        raise RuntimeError("Base adapter manifest has no source digest map")
    for relative, expected_digest in base_sources.items():
        source = (ROOT / relative).resolve()
        if not _under(source, ROOT) or not source.is_file() or sha256(source) != expected_digest:
            raise RuntimeError(f"Base adapter source is missing or changed: {relative}")
    bridge_class = "local/ee/reduce/LocalEeClassifyReduceBridge.class"
    with zipfile.ZipFile(jar) as archive:
        if bridge_class not in archive.namelist():
            raise RuntimeError("Base adapter lacks the reviewed classification/reducer bridge")
    return {"path": jar, "manifest_path": manifest_file, "manifest": manifest}


def _runtime_classpath_check(jars: list[Path], smile: dict[str, Path], slf4j_record: dict) -> Path:
    slf4j_candidates = [path for path in jars if path.name == slf4j_record.get("filename")]
    if len(slf4j_candidates) != 1 or sha256(slf4j_candidates[0]) != slf4j_record.get("sha256"):
        raise RuntimeError("The reused Spark SLF4J API does not match the separately recorded SHA-256")
    owners = {class_name: [] for class_name in SLF4J_API_CLASSES}
    for path in [*jars, *smile.values()]:
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                for class_name in SLF4J_API_CLASSES.intersection(names):
                    owners[class_name].append(path)
        except zipfile.BadZipFile as error:
            raise RuntimeError(f"Invalid JAR on compiler classpath: {path.name}") from error
    for class_name, class_owners in owners.items():
        if class_owners != slf4j_candidates:
            raise RuntimeError(f"The resolved compiler classpath must contain exactly one owner for {class_name}")
    return slf4j_candidates[0]


def _run(args: list[Path | str], env: dict[str, str]) -> None:
    try:
        subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT, env=env)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"Locked tool failed with exit code {error.returncode}: {Path(str(args[0])).name}") from None


def build(output: Path, dependencies: Path, base_adapter: Path, base_manifest: Path) -> dict:
    output = output.expanduser().resolve()
    scratch = WORK_ROOT.resolve()
    if not _under(output, scratch) or output == scratch:
        raise RuntimeError(f"RF adapter output must be below the dedicated work scratch: {scratch}")
    if output.suffix.lower() != ".jar":
        raise RuntimeError("RF adapter output must use a .jar extension")
    if output.name != "local-ee-smile-rf-adapter.jar":
        raise RuntimeError("The RF adapter filename is fixed as local-ee-smile-rf-adapter.jar")
    for source in SOURCES:
        if not source.is_file():
            raise RuntimeError(f"RF adapter source is missing: {source}")
    lock = _read_json(LOCK_PATH, "Smile dependency lock")
    source_provenance = lock.get("source")
    if (lock.get("format") != "local-ee-smile-rf-dependency-lock-v1"
            or lock.get("implementation") != "smile-1.5.3"
            or not isinstance(source_provenance, dict)
            or source_provenance.get("repository") != "https://github.com/haifengl/smile"
            or source_provenance.get("tag") != "v1.5.3"
            or source_provenance.get("license") != "Apache-2.0"):
        raise RuntimeError("Unsupported or changed Smile RF dependency lock")
    smile_paths = _verify_smile_deps(dependencies, lock)
    java, jar_tool, scala_tools, runtime_jars, locked_jars, engine_lock = _engine_paths()
    scala_version = scala_tools[1].stem.rsplit("-", 1)[-1]
    java_home = java.parent.parent
    runtime = {
        "java_home": str(java_home),
        "scala_version": scala_version,
        "spark_version": engine_lock.get("spark"),
    }
    if runtime["spark_version"] != lock["reused_slf4j_api"].get("spark_version"):
        raise RuntimeError("Pinned Spark version differs from Smile's reused SLF4J provenance")
    slf4j_api = _runtime_classpath_check(runtime_jars, smile_paths, lock["reused_slf4j_api"])
    base = _verify_base(base_adapter, base_manifest, runtime, locked_jars)
    all_classpath = [*runtime_jars, base["path"], *smile_paths.values()]
    compiler_cp = os.pathsep.join(str(path) for path in scala_tools)
    compile_cp = os.pathsep.join(str(path) for path in all_classpath)
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    with tempfile.TemporaryDirectory(prefix=".local-ee-smile-rf-", dir=output.parent) as temporary:
        temp = Path(temporary)
        classes = temp / "classes"
        staged_jar = temp / output.name
        staged_manifest = temp / manifest_path.name
        service_file = classes / "META-INF/services" / SERVICE_NAME
        service_file.parent.mkdir(parents=True)
        service_file.write_text(SERVICE_ENTRY, encoding="utf-8")
        compiler = [java, "-cp", compiler_cp, "scala.tools.nsc.Main", "-classpath", compile_cp,
                    "-d", classes, *SOURCES]
        _run(compiler, {**os.environ, "JAVA_HOME": str(java_home)})
        _run([jar_tool, "--create", "--file", staged_jar, "-C", classes, "."],
             {**os.environ, "JAVA_HOME": str(java_home)})
        with zipfile.ZipFile(staged_jar) as archive:
            provider_class = "local/ee/smile/LocalEeSmileRfCubeProcessProvider.class"
            service_bytes = archive.read(f"META-INF/services/{SERVICE_NAME}")
            if provider_class not in archive.namelist() or service_bytes != SERVICE_ENTRY.encode("utf-8"):
                raise RuntimeError("Generated RF SPI class or service-provider bytes are incomplete")
        manifest = {
            "format": "local-ee-smile-rf-adapter-v1",
            "adapter": ADAPTER_ID,
            "jar": str(output),
            "jar_sha256": sha256(staged_jar),
            "sources": {str(path.relative_to(ROOT)): sha256(path) for path in SOURCES},
            "build_script": str(Path(__file__).resolve().relative_to(ROOT)),
            "build_script_sha256": sha256(Path(__file__).resolve()),
            "native": {**runtime, "upstream_jars": locked_jars},
            "base_adapter": {
                "format": base["manifest"]["format"],
                "adapter": base["manifest"]["adapter"],
                "jar": str(base["path"]),
                "jar_sha256": sha256(base["path"]),
                "manifest": str(base["manifest_path"]),
                "manifest_sha256": sha256(base["manifest_path"]),
            },
            "smile_jars": {
                filename: {
                    **record,
                    "path": str(smile_paths[filename]),
                }
                for filename, record in sorted(lock["smile_jars"].items())
            },
            "slf4j_api": {
                "filename": slf4j_api.name,
                "sha256": sha256(slf4j_api),
                "path": str(slf4j_api),
                "version": lock["reused_slf4j_api"]["coordinate"].rsplit(":", 1)[-1],
                "source": f"spark {runtime['spark_version']}",
            },
            "services": {SERVICE_NAME: SERVICE_ENTRY},
        }
        staged_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        staged_manifest.chmod(0o600)
        os.replace(staged_jar, output)
        os.replace(staged_manifest, manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dependencies", required=True, type=Path,
                        help="directory containing exactly the four SHA-locked Smile 1.5.3 JARs")
    parser.add_argument("--base-adapter", required=True, type=Path,
                        help="already built and reviewed base adapter JAR")
    parser.add_argument("--base-manifest", required=True, type=Path,
                        help="adjacent base adapter manifest")
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.dependencies, args.base_adapter, args.base_manifest), indent=2))


if __name__ == "__main__":
    main()
