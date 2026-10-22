"""Synthetic install builders for focused Smile RF classpath tests."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from engine.smile_rf_runtime import (
    BASE_BRIDGE_CLASS,
    BASE_JAR,
    BASE_MANIFEST,
    RF_JAR,
    RF_MANIFEST,
    RF_PROVIDER_CLASS,
    SERVICE_ENTRY,
    SERVICE_NAME,
    SLF4J_API_CLASSES,
    SMILE_JARS,
    prepare_local_classpath,
)


UPSTREAM = (
    "openeo-logging-2.6.4_2.13-SNAPSHOT.jar",
    "geotrellis-extensions-2.6.4_2.13-SNAPSHOT.jar",
    "geotrellis-dependencies-2.6.4_2.13-SNAPSHOT.jar",
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    path.write_bytes(content)
    return content


def _write_jar(path: Path, classes: tuple[str, ...] = (), service: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for class_name in classes:
            archive.writestr(class_name, b"fixture")
        if service is not None:
            archive.writestr(f"META-INF/services/{SERVICE_NAME}", service.encode("utf-8"))


@pytest.fixture
def install(tmp_path):
    """Create a complete, synthetic, hash-consistent optional RF install."""
    root = tmp_path / "repo"
    jars_dir = root / ".native/jars"
    spark_jars_dir = root / ".native/engine/lib/python3.11/site-packages/pyspark/jars"
    sources = {
        "engine/ee_integer_adapter.scala": "base integer adapter source",
        "engine/ee_rf_adapter.scala": "rf adapter source",
        "engine/ee_rf_factory.scala": "rf factory source",
        "engine/ee_rf_numeric.scala": "rf numeric source",
        "engine/ee_rf_wire.scala": "rf wire source",
    }
    for relative, content in sources.items():
        source_path = root / relative
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(content, encoding="utf-8")
    build_script = root / "scripts/build_smile_rf_adapter.py"
    build_script.parent.mkdir(parents=True, exist_ok=True)
    build_script.write_text("# fixture builder\n", encoding="utf-8")

    upstream_hashes = {}
    for filename in UPSTREAM:
        path = jars_dir / filename
        _write_jar(path)
        upstream_hashes[filename] = _digest(path)
    engine_lock = {
        "java_home": "/locked/java/home",
        "spark": "4.0.4",
        "jars": upstream_hashes,
    }
    _write_json(root / ".native/engine-lock.json", engine_lock)

    base_path = jars_dir / BASE_JAR
    _write_jar(base_path, classes=(BASE_BRIDGE_CLASS,))
    base_sources = {
        "engine/ee_integer_adapter.scala": _digest(root / "engine/ee_integer_adapter.scala")
    }
    base_manifest = {
        "format": "local-ee-native-adapter-v1",
        "adapter": "local-ee-integer-adapter",
        "jar": str(base_path),
        "jar_sha256": _digest(base_path),
        "sources": base_sources,
        "java_home": engine_lock["java_home"],
        "scala_version": "2.13.16",
        "spark_version": engine_lock["spark"],
        "upstream_jars": upstream_hashes,
    }
    base_manifest_path = jars_dir / BASE_MANIFEST
    base_bytes = _write_json(base_manifest_path, base_manifest)

    smile_lock = {}
    smile_records = {}
    for filename in SMILE_JARS:
        path = jars_dir / filename
        _write_jar(path)
        digest = _digest(path)
        record = {
            "coordinate": f"com.github.haifengl:{filename.removesuffix('-1.5.3.jar')}:1.5.3",
            "url": f"https://repo.maven.apache.org/maven2/com/github/haifengl/{filename}",
            "sha256": digest,
        }
        smile_lock[filename] = record
        smile_records[filename] = {**record, "path": str(tmp_path / "builder-deps" / filename)}

    slf4j_path = spark_jars_dir / "slf4j-api-2.0.16.jar"
    _write_jar(slf4j_path, classes=tuple(SLF4J_API_CLASSES))
    dependency_lock = {
        "format": "local-ee-smile-rf-dependency-lock-v1",
        "implementation": "smile-1.5.3",
        "source": {"repository": "https://github.com/haifengl/smile", "tag": "v1.5.3"},
        "smile_jars": smile_lock,
        "reused_slf4j_api": {
            "coordinate": "org.slf4j:slf4j-api:2.0.16",
            "spark_version": "4.0.4",
            "filename": slf4j_path.name,
            "sha256": _digest(slf4j_path),
        },
    }
    _write_json(root / "deploy/smile-rf-lock.json", dependency_lock)

    rf_path = jars_dir / RF_JAR
    _write_jar(rf_path, classes=(RF_PROVIDER_CLASS,), service=SERVICE_ENTRY)
    rf_manifest = {
        "format": "local-ee-smile-rf-adapter-v1",
        "adapter": "local-ee-smile-rf-adapter",
        "jar": str(tmp_path / "builder-output" / RF_JAR),
        "jar_sha256": _digest(rf_path),
        "sources": {
            relative: _digest(root / relative)
            for relative in sources
            if relative != "engine/ee_integer_adapter.scala"
        },
        "build_script": "scripts/build_smile_rf_adapter.py",
        "build_script_sha256": _digest(build_script),
        "native": {
            "java_home": engine_lock["java_home"],
            "scala_version": base_manifest["scala_version"],
            "spark_version": engine_lock["spark"],
            "upstream_jars": upstream_hashes,
        },
        "base_adapter": {
            "format": base_manifest["format"],
            "adapter": base_manifest["adapter"],
            "jar": str(base_path),
            "jar_sha256": _digest(base_path),
            "manifest": str(base_manifest_path),
            "manifest_sha256": hashlib.sha256(base_bytes).hexdigest(),
        },
        "smile_jars": smile_records,
        "slf4j_api": {
            "filename": slf4j_path.name,
            "sha256": _digest(slf4j_path),
            "path": str(slf4j_path),
            "version": "2.0.16",
            "source": "spark 4.0.4",
        },
        "services": {SERVICE_NAME: SERVICE_ENTRY},
    }
    _write_json(jars_dir / RF_MANIFEST, rf_manifest)

    discovered = [str(path) for path in sorted(jars_dir.glob("*.jar"))]
    return {
        "root": root,
        "jars": jars_dir,
        "spark_home": spark_jars_dir.parent,
        "discovered": discovered,
        "rf_manifest": rf_manifest,
        "slf4j_path": slf4j_path,
    }


def _prepare(install, discovered=None):
    return prepare_local_classpath(
        install["discovered"] if discovered is None else discovered,
        install["jars"],
        install["root"],
        install["spark_home"],
    )
