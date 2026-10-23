"""Verify and install the optional, locally built Smile RF classpath."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


RF_JAR = "local-ee-smile-rf-adapter.jar"
RF_MANIFEST = RF_JAR + ".manifest.json"
BASE_JAR = "local-ee-integer-adapter.jar"
BASE_MANIFEST = BASE_JAR + ".manifest.json"
SMILE_JARS = (
    "smile-core-1.5.3.jar",
    "smile-data-1.5.3.jar",
    "smile-math-1.5.3.jar",
    "smile-graph-1.5.3.jar",
)
SERVICE_NAME = "org.openeo.geotrelliscommon.CubeProcessProvider"
SERVICE_PROVIDER = "local.ee.smile.LocalEeSmileRfCubeProcessProvider"
SERVICE_ENTRY = SERVICE_PROVIDER + "\n"
BASE_BRIDGE_CLASS = "local/ee/reduce/LocalEeClassifyReduceBridge.class"
RF_PROVIDER_CLASS = "local/ee/smile/LocalEeSmileRfCubeProcessProvider.class"
SLF4J_API_CLASSES = {
    "org/slf4j/Logger.class",
    "org/slf4j/LoggerFactory.class",
    "org/slf4j/ILoggerFactory.class",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> tuple[dict, bytes]:
    try:
        content = path.read_bytes()
        value = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot read {label}: {path}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return value, content


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} must be a regular, non-symlink file: {path}")
    try:
        return path.resolve(strict=True)
    except OSError as error:
        raise RuntimeError(f"{label} is unavailable: {path}") from error


def _digest_matches(path: Path, expected: object, label: str) -> str:
    if not isinstance(expected, str) or len(expected) != 64:
        raise RuntimeError(f"{label} has no valid SHA-256 digest")
    actual = _sha256(path)
    if actual != expected:
        raise RuntimeError(f"{label} SHA-256 mismatch")
    return actual


def _archive_names(path: Path, label: str) -> set[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            return set(archive.namelist())
    except (OSError, zipfile.BadZipFile) as error:
        raise RuntimeError(f"Invalid JAR on the local classpath: {label}") from error


def _legacy_classpath(paths: list[str], jars_dir: Path) -> list[str]:
    """Retain the pre-RF runner behavior when no RF install is present."""
    adapter = jars_dir / BASE_JAR
    if adapter.exists():
        manifest_path = adapter.with_suffix(".jar.manifest.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Cannot read Local EE adapter manifest: {manifest_path}") from error
        if _sha256(adapter) != manifest.get("jar_sha256"):
            raise RuntimeError("Local EE adapter checksum mismatch; rebuild the native adapter")
        if str(adapter) not in paths:
            paths.append(str(adapter))
    paths.sort(
        key=lambda value: "geotrellis-extensions" not in value
        and "geotrellis-dependencies" not in value
    )
    return paths


def _has_rf_install_signal(jars_dir: Path) -> bool:
    if not jars_dir.is_dir():
        return False
    for path in jars_dir.iterdir():
        name = path.name
        if name.startswith("local-ee-smile-rf"):
            return True
        if name.startswith("smile-") and (name.endswith(".jar") or name.endswith(".jar.manifest.json")):
            return True
    return False


def _verify_source(root: Path, relative: object, expected: object, label: str) -> None:
    if not isinstance(relative, str) or not isinstance(expected, str) or len(expected) != 64:
        raise RuntimeError(f"{label} contains an invalid source digest record")
    source_rel = PurePosixPath(relative)
    if source_rel.is_absolute() or ".." in source_rel.parts or "\\" in relative:
        raise RuntimeError(f"{label} contains an unsafe source path: {relative}")
    candidate = root.joinpath(*source_rel.parts)
    source = _regular_file(candidate, f"{label} source")
    try:
        source.relative_to(root.resolve(strict=True))
    except ValueError as error:
        raise RuntimeError(f"{label} source escapes the repository: {relative}") from error
    _digest_matches(source, expected, f"{label} source {relative}")


def _verify_optional_install(
    discovered_paths: list[str],
    jars_dir: Path,
    project_root: Path,
    spark_home: Path | None,
) -> list[str]:
    if jars_dir.is_symlink() or not jars_dir.is_dir():
        raise RuntimeError("The configured GeoPySpark JAR directory must be a real directory")
    root = project_root.resolve(strict=True)
    jars_root = jars_dir.resolve(strict=True)

    dependency_lock, _ = _read_json(root / "deploy/smile-rf-lock.json", "Smile RF dependency lock")
    if (
        dependency_lock.get("format") != "local-ee-smile-rf-dependency-lock-v1"
        or dependency_lock.get("implementation") != "smile-1.5.3"
    ):
        raise RuntimeError("Unsupported Smile RF dependency lock")
    locked_smile = dependency_lock.get("smile_jars")
    if not isinstance(locked_smile, dict) or set(locked_smile) != set(SMILE_JARS):
        raise RuntimeError("Smile RF dependency lock must name exactly the four pinned Smile 1.5.3 JARs")
    for filename, record in locked_smile.items():
        if not isinstance(record, dict) or not all(
            isinstance(record.get(field), str) for field in ("coordinate", "url", "sha256")
        ):
            raise RuntimeError(f"Smile RF lock record is incomplete: {filename}")

    engine_lock, _ = _read_json(root / ".native/engine-lock.json", "native engine lock")
    upstream = engine_lock.get("jars")
    if not isinstance(upstream, dict) or not upstream:
        raise RuntimeError("Native engine lock has no JAR digest map")
    if any(
        not isinstance(name, str) or not isinstance(digest, str) or len(digest) != 64
        for name, digest in upstream.items()
    ):
        raise RuntimeError("Native engine lock contains an invalid JAR record")

    expected_names = set(upstream) | {BASE_JAR, RF_JAR, *SMILE_JARS}
    actual_names = {path.name for path in jars_root.iterdir() if path.name.endswith(".jar")}
    if actual_names != expected_names:
        unexpected = sorted(actual_names - expected_names)
        missing = sorted(expected_names - actual_names)
        raise RuntimeError(
            f"Configured JAR directory differs from its locked contents "
            f"(unexpected={unexpected}, missing={missing})"
        )

    jar_paths = {name: _regular_file(jars_root / name, f"Locked JAR {name}") for name in expected_names}
    for name, expected in upstream.items():
        _digest_matches(jar_paths[name], expected, f"Native engine JAR {name}")

    base_path = jar_paths[BASE_JAR]
    base_manifest_path = _regular_file(jars_root / BASE_MANIFEST, "Base adapter manifest")
    base_manifest, base_bytes = _read_json(base_manifest_path, "base adapter manifest")
    base_digest = _digest_matches(base_path, base_manifest.get("jar_sha256"), "Base adapter")
    if (
        base_manifest.get("format") != "local-ee-native-adapter-v1"
        or base_manifest.get("adapter") != "local-ee-integer-adapter"
    ):
        raise RuntimeError("The installed base adapter is not the reviewed Local EE integer adapter")
    recorded_base_path = Path(str(base_manifest.get("jar", "")))
    if not recorded_base_path.is_absolute() or recorded_base_path.name != BASE_JAR:
        raise RuntimeError("Base adapter manifest identifies a different JAR filename")
    if base_manifest.get("upstream_jars") != upstream:
        raise RuntimeError("Base adapter manifest does not match the active native engine lock")
    if (
        base_manifest.get("java_home") != engine_lock.get("java_home")
        or base_manifest.get("spark_version") != engine_lock.get("spark")
    ):
        raise RuntimeError("Base adapter manifest does not match the active native Java/Spark runtime")
    base_sources = base_manifest.get("sources")
    if not isinstance(base_sources, dict) or not base_sources:
        raise RuntimeError("Base adapter manifest has no source digest map")
    for relative, expected in base_sources.items():
        _verify_source(root, relative, expected, "Base adapter manifest")
    base_names = _archive_names(base_path, BASE_JAR)
    if BASE_BRIDGE_CLASS not in base_names:
        raise RuntimeError("Base adapter lacks the reviewed classification/reducer bridge")

    rf_path = jar_paths[RF_JAR]
    rf_manifest_path = _regular_file(jars_root / RF_MANIFEST, "Smile RF adapter manifest")
    rf_manifest, _ = _read_json(rf_manifest_path, "Smile RF adapter manifest")
    _digest_matches(rf_path, rf_manifest.get("jar_sha256"), "Smile RF adapter")
    if (
        rf_manifest.get("format") != "local-ee-smile-rf-adapter-v1"
        or rf_manifest.get("adapter") != "local-ee-smile-rf-adapter"
    ):
        raise RuntimeError("Unsupported Smile RF adapter manifest")
    recorded_rf_path = Path(str(rf_manifest.get("jar", "")))
    if not recorded_rf_path.is_absolute() or recorded_rf_path.name != RF_JAR:
        raise RuntimeError("Smile RF adapter manifest identifies a different JAR filename")

    source_map = rf_manifest.get("sources")
    if not isinstance(source_map, dict) or not source_map:
        raise RuntimeError("Smile RF adapter manifest has no source digest map")
    for relative, expected in source_map.items():
        _verify_source(root, relative, expected, "Smile RF adapter manifest")
    if rf_manifest.get("build_script") != "scripts/build_smile_rf_adapter.py":
        raise RuntimeError("Smile RF adapter manifest identifies a different build script")
    _verify_source(
        root,
        rf_manifest.get("build_script"),
        rf_manifest.get("build_script_sha256"),
        "Smile RF adapter manifest",
    )

    recorded_base = rf_manifest.get("base_adapter")
    if not isinstance(recorded_base, dict):
        raise RuntimeError("Smile RF manifest has no base adapter identity")
    if (
        recorded_base.get("format") != base_manifest.get("format")
        or recorded_base.get("adapter") != base_manifest.get("adapter")
    ):
        raise RuntimeError("Smile RF manifest names a different base adapter")
    recorded_base_jar = Path(str(recorded_base.get("jar", "")))
    recorded_base_manifest = Path(str(recorded_base.get("manifest", "")))
    if (
        not recorded_base_jar.is_absolute()
        or recorded_base_jar.name != BASE_JAR
        or not recorded_base_manifest.is_absolute()
        or recorded_base_manifest.name != BASE_MANIFEST
    ):
        raise RuntimeError("Smile RF manifest identifies different base adapter files")
    if (
        recorded_base.get("jar_sha256") != base_digest
        or recorded_base.get("manifest_sha256") != hashlib.sha256(base_bytes).hexdigest()
    ):
        raise RuntimeError("Smile RF manifest does not match the installed base adapter and manifest")

    rf_native = rf_manifest.get("native")
    if not isinstance(rf_native, dict):
        raise RuntimeError("Smile RF manifest has no pinned native runtime identity")
    if (
        rf_native.get("java_home") != engine_lock.get("java_home")
        or rf_native.get("spark_version") != engine_lock.get("spark")
        or rf_native.get("scala_version") != base_manifest.get("scala_version")
        or rf_native.get("upstream_jars") != upstream
    ):
        raise RuntimeError("Smile RF manifest does not match the installed native runtime and base adapter")

    smile_records = rf_manifest.get("smile_jars")
    if not isinstance(smile_records, dict) or set(smile_records) != set(SMILE_JARS):
        raise RuntimeError("Smile RF manifest must name exactly the four pinned Smile JARs")
    for filename in SMILE_JARS:
        record = smile_records[filename]
        locked = locked_smile[filename]
        if not isinstance(record, dict) or any(
            record.get(field) != locked[field] for field in ("coordinate", "url", "sha256")
        ):
            raise RuntimeError(f"Smile RF manifest disagrees with the committed dependency lock: {filename}")
        recorded_dependency_path = Path(str(record.get("path", "")))
        if not recorded_dependency_path.is_absolute() or recorded_dependency_path.name != filename:
            raise RuntimeError(f"Smile RF manifest identifies a different dependency JAR: {filename}")
        _digest_matches(jar_paths[filename], locked["sha256"], f"Smile dependency {filename}")

    if spark_home is None:
        raise RuntimeError("SPARK_HOME is required to verify the reused SLF4J API")
    spark_jars_dir = spark_home / "jars"
    if spark_home.is_symlink() or spark_jars_dir.is_symlink() or not spark_jars_dir.is_dir():
        raise RuntimeError("SPARK_HOME does not identify the locked Spark JAR directory")
    reused_slf4j = dependency_lock.get("reused_slf4j_api")
    if (
        not isinstance(reused_slf4j, dict)
        or reused_slf4j.get("coordinate") != "org.slf4j:slf4j-api:2.0.17"
        or reused_slf4j.get("spark_version") != engine_lock.get("spark")
    ):
        raise RuntimeError("Smile RF lock does not match the active Spark SLF4J provenance")
    slf_name = reused_slf4j.get("filename")
    if not isinstance(slf_name, str) or slf_name != "slf4j-api-2.0.17.jar":
        raise RuntimeError("Smile RF lock names an unsupported shared SLF4J API")
    slf_candidates = list(spark_jars_dir.glob("slf4j-api-*.jar"))
    if len(slf_candidates) != 1 or slf_candidates[0].name != slf_name:
        raise RuntimeError("Spark must provide exactly the one separately locked SLF4J API")
    slf_path = _regular_file(slf_candidates[0], "Spark SLF4J API")
    slf_digest = _digest_matches(slf_path, reused_slf4j.get("sha256"), "Spark SLF4J API")
    slf_record = rf_manifest.get("slf4j_api")
    recorded_slf_path = Path(str(slf_record.get("path", ""))) if isinstance(slf_record, dict) else Path()
    if not isinstance(slf_record, dict) or (
        slf_record.get("filename") != slf_name
        or slf_record.get("sha256") != slf_digest
        or not recorded_slf_path.is_absolute()
        or recorded_slf_path.resolve() != slf_path
        or slf_record.get("version") != reused_slf4j.get("coordinate", "").rsplit(":", 1)[-1]
        or slf_record.get("source") != f"spark {engine_lock.get('spark')}"
    ):
        raise RuntimeError("Smile RF manifest does not match the locked Spark SLF4J API")

    services = rf_manifest.get("services")
    if services != {SERVICE_NAME: SERVICE_ENTRY}:
        raise RuntimeError("Smile RF manifest declares an unexpected GeoTrellis SPI provider")
    rf_names = _archive_names(rf_path, RF_JAR)
    if RF_PROVIDER_CLASS not in rf_names:
        raise RuntimeError("Smile RF adapter lacks its expected SPI provider class")
    try:
        with zipfile.ZipFile(rf_path) as archive:
            service_bytes = archive.read(f"META-INF/services/{SERVICE_NAME}")
    except (OSError, KeyError, zipfile.BadZipFile) as error:
        raise RuntimeError("Smile RF adapter is missing its GeoTrellis SPI service file") from error
    if service_bytes != SERVICE_ENTRY.encode("utf-8"):
        raise RuntimeError("Smile RF adapter SPI service bytes do not match the manifest")

    classpath_jars = [*jar_paths.values()]
    spark_jars = [
        _regular_file(path, "Spark runtime JAR")
        for path in spark_jars_dir.glob("*.jar")
    ]
    if slf_path not in spark_jars:
        raise RuntimeError("Locked Spark SLF4J API is missing from the Spark classpath")
    api_owners: dict[str, list[Path]] = {name: [] for name in SLF4J_API_CLASSES}
    for path in [*spark_jars, *classpath_jars]:
        names = _archive_names(path, path.name)
        for api_class in SLF4J_API_CLASSES.intersection(names):
            api_owners[api_class].append(path)
    for api_class, owners in api_owners.items():
        if owners != [slf_path]:
            raise RuntimeError(f"SLF4J API class has duplicate or missing owners: {api_class}")

    allowed_by_path = {str(path): name for name, path in jar_paths.items()}
    found_names = []
    for value in discovered_paths:
        candidate = Path(value)
        if candidate.is_symlink():
            raise RuntimeError(f"Spark discovered a symlinked JAR: {value}")
        try:
            resolved = str(candidate.resolve(strict=True))
            candidate_parent = candidate.parent.resolve(strict=True)
        except OSError as error:
            raise RuntimeError(f"Spark discovered an unavailable JAR: {value}") from error
        if candidate_parent != jars_root:
            raise RuntimeError(f"Spark discovered a JAR outside the configured flat directory: {value}")
        name = allowed_by_path.get(resolved)
        if name is None:
            raise RuntimeError(f"Spark discovered an unlocked JAR outside the verified classpath: {value}")
        found_names.append(name)
    if len(found_names) != len(set(found_names)) or set(found_names) != expected_names:
        raise RuntimeError("GeoPySpark-discovered JARs do not exactly match the locked local JAR set")

    existing_spark_jars = [jar_paths[name] for name in upstream]
    existing_spark_jars.sort(
        key=lambda path: "geotrellis-extensions" not in path.name
        and "geotrellis-dependencies" not in path.name
    )
    ordered = [
        jar_paths[RF_JAR],
        jar_paths[BASE_JAR],
        *(jar_paths[name] for name in SMILE_JARS),
        *existing_spark_jars,
    ]
    return [str(path) for path in ordered]


def prepare_local_classpath(
    discovered_paths: Iterable[str],
    jars_dir: Path,
    project_root: Path,
    spark_home: Path | None,
) -> list[str]:
    """Return validated local extraClassPath entries without touching Spark."""
    paths = [str(path) for path in discovered_paths if str(path)]
    if not _has_rf_install_signal(jars_dir):
        return _legacy_classpath(paths, jars_dir)
    return _verify_optional_install(paths, jars_dir, project_root, spark_home)
