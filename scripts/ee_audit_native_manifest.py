"""Validate explicit-classpath native audit artifacts without deployment config."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.build_integer_adapter import SERVICE_NAME, SOURCE, SOURCES


ROOT = Path(__file__).resolve().parents[1]
AUDIT_ROOT = (ROOT / "audit").resolve()
NATIVE_JARS = (ROOT / ".native/jars").resolve()
SPARK_JARS = (
    ROOT / ".native/engine/lib/python3.11/site-packages/pyspark/jars"
).resolve()
HELPER = ROOT / "scripts/ee_adapter_build_inputs.py"
BUILDER = ROOT / "scripts/build_integer_adapter.py"
EXPECTED_ADAPTERS = {
    "local-ee-mask-weights-audit-adapter":
        "local.ee.reduce.LocalEeMaskWeightsCubeProcessProvider",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_child(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _manifest_at(path: Path, expected_adapter: str) -> tuple[Path, dict]:
    manifest_path = Path(path).expanduser().resolve(strict=True)
    if not _is_child(manifest_path, AUDIT_ROOT) or not manifest_path.is_file():
        raise ValueError("native audit manifest must be a file under ROOT/audit")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("native audit manifest is not readable JSON") from error
    if (type(manifest) is not dict
            or manifest.get("format") != "local-ee-standalone-audit-v1"
            or manifest.get("build_mode") != "standalone-explicit-classpath"
            or manifest.get("deployment_eligible") is not False
            or manifest.get("provenance_claim_verified") is not False):
        raise ValueError("manifest is not a non-deployment standalone audit artifact")
    if expected_adapter not in EXPECTED_ADAPTERS or manifest.get("adapter") != expected_adapter:
        raise ValueError("manifest adapter does not match the expected audit adapter")
    return manifest_path, manifest


def _runtime_and_tools(manifest: dict) -> dict:
    java = Path(manifest.get("java", "")).expanduser().resolve(strict=True)
    jar_tool = Path(manifest.get("jar_tool", "")).expanduser().resolve(strict=True)
    if manifest.get("java_sha256") != sha256(java):
        raise ValueError("audit manifest Java runtime hash mismatch")
    if manifest.get("jar_tool_sha256") != sha256(jar_tool):
        raise ValueError("audit manifest jar tool hash mismatch")

    def checked_jars(rows, label):
        if type(rows) is not list or not rows:
            raise ValueError(f"audit manifest has no {label} JAR records")
        paths = []
        for row in rows:
            if type(row) is not dict or type(row.get("path")) is not str:
                raise ValueError(f"audit manifest has an invalid {label} JAR record")
            path = Path(row["path"]).expanduser().resolve(strict=True)
            if (path.suffix != ".jar" or row.get("sha256") != sha256(path)
                    or not any(_is_child(path, directory)
                               for directory in (NATIVE_JARS, SPARK_JARS))):
                raise ValueError(f"audit manifest {label} JAR path or hash is invalid: {path}")
            paths.append(path)
        if len(paths) != len(set(paths)):
            raise ValueError(f"audit manifest repeats a {label} JAR path")
        return paths

    scala_tools = checked_jars(manifest.get("scala_tools"), "Scala tool")
    if (len(scala_tools) != 3
            or {path.name.split("-")[1] for path in scala_tools} !=
            {"compiler", "library", "reflect"}):
        raise ValueError("audit manifest must contain compiler, library and reflect JARs")
    runtime_jars = checked_jars(manifest.get("runtime_jars"), "runtime")
    allowed_current = set(SPARK_JARS.glob("*.jar"))
    allowed_current.update(
        path for path in NATIVE_JARS.glob("*.jar")
        if not path.name.startswith("local-ee-")
    )
    allowed_current = {path.resolve(strict=True) for path in allowed_current}
    if set(runtime_jars) != allowed_current:
        raise ValueError("audit manifest runtime JAR set differs from the current allowed directories")
    if not set(scala_tools).issubset(runtime_jars):
        raise ValueError("audit manifest Scala tools are absent from its runtime classpath")
    return {
        "java": java,
        "jar_tool": jar_tool,
        "scala_tools": scala_tools,
        "runtime_jars": runtime_jars,
    }


def verify_native_manifest_tools_and_runtime(
    manifest_path: Path, *, expected_adapter: str,
) -> dict:
    """Verify tool and allowed runtime JAR hashes, including for prior audit manifests."""
    path, manifest = _manifest_at(manifest_path, expected_adapter)
    return {"manifest_path": path, "manifest": manifest, **_runtime_and_tools(manifest)}


def validate_native_manifest(manifest_path: Path, *, expected_adapter: str) -> dict:
    """Verify a current adapter source/build/provider receipt and its explicit classpath."""
    checked = verify_native_manifest_tools_and_runtime(
        manifest_path, expected_adapter=expected_adapter,
    )
    path, manifest = checked["manifest_path"], checked["manifest"]
    expected_sources = {str(source.relative_to(ROOT)): source for source in SOURCES}
    source_hashes = manifest.get("sources")
    if (type(source_hashes) is not dict or len(expected_sources) != len(SOURCES)
            or set(source_hashes) != set(expected_sources)):
        raise ValueError("audit manifest source set differs from the current adapter builder")
    for relative, source in expected_sources.items():
        if not source.is_file() or source_hashes.get(relative) != sha256(source):
            raise ValueError(f"audit manifest source hash mismatch: {relative}")
    if (manifest.get("source") != str(SOURCE.relative_to(ROOT))
            or manifest.get("source_sha256") != sha256(SOURCE)):
        raise ValueError("audit manifest primary source hash mismatch")
    if (manifest.get("build_script") != str(BUILDER.relative_to(ROOT))
            or manifest.get("build_script_sha256") != sha256(BUILDER)):
        raise ValueError("audit manifest builder hash mismatch")
    if manifest.get("build_helpers") != {
            str(HELPER.relative_to(ROOT)): sha256(HELPER)}:
        raise ValueError("audit manifest standalone build helper hash mismatch")

    jar = Path(manifest.get("jar", "")).expanduser().resolve(strict=True)
    if (not _is_child(jar, AUDIT_ROOT) or manifest.get("jar_sha256") != sha256(jar)
            or path != Path(str(jar) + ".manifest.json")):
        raise ValueError("audit JAR path or hash does not match its adjacent manifest")
    provider = EXPECTED_ADAPTERS[expected_adapter]
    service_entry = manifest.get("services", {}).get(SERVICE_NAME, "")
    if type(service_entry) is not str or provider not in service_entry.splitlines():
        raise ValueError("audit manifest does not register the expected service provider")
    return {**checked, "jar": jar, "provider": provider}
