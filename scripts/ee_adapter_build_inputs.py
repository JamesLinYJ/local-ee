"""Standalone, audit-only classpath builder for the local EE adapter."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
from pathlib import Path


_PUBLIC_LOCKS = (
    "engine/jars-lock.json",
    "engine/security-jar-lock.json",
    "engine/security-build-downloads.json",
    "engine/security-downloads.json",
    "engine/security-runtime-profile.json",
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _collect_public_hashes(value, source: str, result: dict[str, list[tuple[str, str]]]) -> None:
    if isinstance(value, list):
        for item in value:
            _collect_public_hashes(item, source, result)
    elif isinstance(value, dict):
        filename, digest = value.get("file"), value.get("sha256")
        if isinstance(filename, str) and filename.endswith(".jar") and isinstance(digest, str):
            if _SHA256.fullmatch(digest):
                result.setdefault(filename, []).append((source, digest))
        for name, nested in value.items():
            if (isinstance(name, str) and name.endswith(".jar") and isinstance(nested, str)
                    and _SHA256.fullmatch(nested)):
                result.setdefault(name, []).append((source, nested))
            elif isinstance(nested, (dict, list)):
                _collect_public_hashes(nested, source, result)


def public_runtime_attestation(project_root: Path, runtime_jars: list[Path]) -> dict:
    root = Path(project_root)
    public_hashes: dict[str, list[tuple[str, str]]] = {}
    lock_files = []
    for relative in _PUBLIC_LOCKS:
        path = root / relative
        if not path.is_file():
            continue
        lock_files.append(relative)
        _collect_public_hashes(json.loads(path.read_text(encoding="utf-8")), relative, public_hashes)

    matched, mismatched, unlisted = [], [], []
    for path in runtime_jars:
        digest = sha256(path)
        expected = public_hashes.get(path.name, [])
        record = {"path": str(path), "sha256": digest}
        if not expected:
            unlisted.append(record)
        elif any(expected_digest == digest for _, expected_digest in expected):
            record["matches"] = [source for source, expected_digest in expected if expected_digest == digest]
            matched.append(record)
        else:
            record["expected"] = [
                {"source": source, "sha256": expected_digest}
                for source, expected_digest in expected
            ]
            mismatched.append(record)
    return {
        "lock_files": lock_files,
        "matched": matched,
        "mismatched": mismatched,
        "unlisted": unlisted,
        "deployment_eligible": False,
    }


def build_with_classpath(
    output: Path, *, project_root: Path, sources: list[Path], primary_source: Path,
    build_script: Path, service_name: str, service_entry: str, java: Path,
    jar_tool: Path, scala_tools: list[Path], runtime_jars: list[Path], provenance: str,
) -> dict:
    """Compile from explicit tools and JARs; this format is audit-only."""
    root = Path(project_root).resolve()
    sources = [Path(path).resolve() for path in sources]
    primary_source = Path(primary_source).resolve()
    build_script = Path(build_script).resolve()
    build_helper = Path(__file__).resolve()
    java = Path(java).expanduser().resolve()
    jar_tool = Path(jar_tool).expanduser().resolve()
    scala_tools = [Path(path).expanduser().resolve() for path in scala_tools]
    runtime_jars = [Path(path).expanduser().resolve() for path in runtime_jars]
    if any(not source.is_file() for source in sources):
        raise RuntimeError("Standalone build is missing one or more Scala sources")
    if not java.is_file() or not jar_tool.is_file():
        raise RuntimeError("Standalone Java and jar tools must be existing files")
    if len(scala_tools) != 3 or any(not path.is_file() for path in scala_tools):
        raise RuntimeError("Standalone build requires compiler, library, and reflect JARs")
    if not runtime_jars or any(not path.is_file() for path in runtime_jars):
        raise RuntimeError("Standalone build requires existing runtime JARs")
    if not isinstance(provenance, str) or not provenance.strip():
        raise RuntimeError("Standalone build requires a public provenance label")

    java_home = java.parent.parent
    scala_version = next((path.stem.rsplit("-", 1)[-1] for path in scala_tools
                          if path.name.startswith("scala-library-")), "unknown")
    compile_cp = os.pathsep.join(str(path) for path in runtime_jars)
    compiler_cp = os.pathsep.join(str(path) for path in scala_tools)
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    java_version = subprocess.run(
        [str(java), "-version"], check=True, cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    ).stdout.strip()

    with tempfile.TemporaryDirectory(prefix=".local-ee-mask-weights-", dir=output.parent) as temporary:
        temporary_path = Path(temporary)
        classes = temporary_path / "classes"
        staged_jar = temporary_path / output.name
        staged_manifest = temporary_path / manifest_path.name
        services = classes / "META-INF/services"
        classes.mkdir()
        services.mkdir(parents=True)
        (services / service_name).write_text(service_entry, encoding="utf-8")
        compiler = [
            str(java), "-cp", compiler_cp, "scala.tools.nsc.Main",
            "-classpath", compile_cp, "-d", str(classes), *map(str, sources),
        ]
        subprocess.run(compiler, check=True, cwd=root, env={**os.environ, "JAVA_HOME": str(java_home)})
        subprocess.run(
            [str(jar_tool), "--create", "--file", str(staged_jar), "-C", str(classes), "."],
            check=True, cwd=root, env={**os.environ, "JAVA_HOME": str(java_home)},
        )
        manifest = {
            "format": "local-ee-standalone-audit-v1",
            "adapter": "local-ee-mask-weights-audit-adapter",
            "build_mode": "standalone-explicit-classpath",
            "deployment_eligible": False,
            "provenance_claim": provenance.strip(),
            "provenance_claim_verified": False,
            "source": str(primary_source.relative_to(root)),
            "source_sha256": sha256(primary_source),
            "sources": {str(path.relative_to(root)): sha256(path) for path in sources},
            "build_script": str(build_script.relative_to(root)),
            "build_script_sha256": sha256(build_script),
            "build_helpers": {str(build_helper.relative_to(root)): sha256(build_helper)},
            "jar": str(output),
            "jar_sha256": sha256(staged_jar),
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "java": str(java),
            "java_sha256": sha256(java),
            "java_version": java_version,
            "jar_tool": str(jar_tool),
            "jar_tool_sha256": sha256(jar_tool),
            "scala_version": scala_version,
            "scala_tools": [{"path": str(path), "sha256": sha256(path)} for path in scala_tools],
            "runtime_jars": [{"path": str(path), "sha256": sha256(path)} for path in runtime_jars],
            "runtime_public_attestation": public_runtime_attestation(root, runtime_jars),
            "services": {service_name: service_entry.strip()},
        }
        staged_manifest.write_text(json.dumps(manifest, indent=2) + os.linesep, encoding="utf-8")
        staged_manifest.chmod(0o600)
        os.replace(staged_jar, output)
        os.replace(staged_manifest, manifest_path)
    return manifest


def build_standalone(
    output: Path, *, project_root: Path, sources: list[Path], primary_source: Path,
    build_script: Path, service_name: str, service_entry: str, java_home: Path,
    spark_jars_dir: Path, engine_jars_dir: Path, provenance: str,
) -> dict:
    """Enumerate only supplied JAR directories; never read native config or locks."""
    java_home = Path(java_home).expanduser().resolve()
    spark_jars_dir = Path(spark_jars_dir).expanduser().resolve()
    engine_jars_dir = Path(engine_jars_dir).expanduser().resolve()
    java, jar_tool = java_home / "bin/java", java_home / "bin/jar"
    if not spark_jars_dir.is_dir() or not engine_jars_dir.is_dir():
        raise RuntimeError("Standalone Spark and engine JAR directories must exist")
    scala_tools = []
    for stem in ("scala-compiler", "scala-library", "scala-reflect"):
        matches = sorted(spark_jars_dir.glob(f"{stem}-*.jar"))
        if len(matches) != 1:
            raise RuntimeError(f"Expected exactly one standalone {stem} JAR")
        scala_tools.append(matches[0])
    runtime_jars = sorted(spark_jars_dir.glob("*.jar"))
    runtime_jars += [path for path in sorted(engine_jars_dir.glob("*.jar"))
                     if not path.name.startswith("local-ee-")]
    if not any("geotrellis-extensions" in path.name for path in runtime_jars):
        raise RuntimeError("Standalone engine JAR set has no GeoTrellis extensions JAR")
    if not any("geotrellis-dependencies" in path.name for path in runtime_jars):
        raise RuntimeError("Standalone engine JAR set has no GeoTrellis dependencies JAR")
    return build_with_classpath(
        output, project_root=project_root, sources=sources, primary_source=primary_source,
        build_script=build_script, service_name=service_name, service_entry=service_entry,
        java=java, jar_tool=jar_tool, scala_tools=scala_tools, runtime_jars=runtime_jars,
        provenance=provenance,
    )
