"""Offline checks for the optional, trusted local Smile RF classpath."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from gee.native import sandbox as sandbox_module
from engine.smile_rf_runtime import (
    BASE_JAR,
    BASE_MANIFEST,
    RF_JAR,
    RF_MANIFEST,
    RF_PROVIDER_CLASS,
    SERVICE_ENTRY,
    SMILE_JARS,
    prepare_local_classpath,
)
from ee_smile_rf_runtime_helpers import _digest, _prepare, _write_jar, _write_json, install


def test_absent_optional_rf_preserves_legacy_path_handling(tmp_path):
    jars_dir = tmp_path / "jars"
    root = tmp_path / "repo-without-lock-files"
    paths = ["/runtime/openeo-logging.jar", "/runtime/geotrellis-extensions.jar", "/runtime/other.jar"]

    result = prepare_local_classpath(paths, jars_dir, root, None)

    assert result == [
        "/runtime/geotrellis-extensions.jar",
        "/runtime/openeo-logging.jar",
        "/runtime/other.jar",
    ]


def test_absent_optional_rf_still_verifies_and_adds_the_existing_base_adapter(tmp_path):
    jars_dir = tmp_path / "jars"
    jars_dir.mkdir()
    adapter = jars_dir / BASE_JAR
    _write_jar(adapter)
    manifest = {"jar_sha256": _digest(adapter)}
    _write_json(jars_dir / BASE_MANIFEST, manifest)

    result = prepare_local_classpath([], jars_dir, tmp_path / "repo", None)

    assert result == [str(adapter)]
    adapter.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="Local EE adapter checksum mismatch"):
        prepare_local_classpath([], jars_dir, tmp_path / "repo", None)


def test_optional_install_verifies_and_orders_only_locked_local_jars(install):
    result = _prepare(install)

    assert [Path(path).name for path in result] == [
        RF_JAR,
        BASE_JAR,
        *SMILE_JARS,
        "geotrellis-extensions-2.6.4_2.13-SNAPSHOT.jar",
        "geotrellis-dependencies-2.6.4_2.13-SNAPSHOT.jar",
        "openeo-logging-2.6.4_2.13-SNAPSHOT.jar",
    ]
    assert all(Path(path).parent == install["jars"] for path in result)


def test_partial_install_is_rejected_before_classpath_creation(install):
    (install["jars"] / SMILE_JARS[2]).unlink()
    discovered = [value for value in install["discovered"] if Path(value).name != SMILE_JARS[2]]

    with pytest.raises(RuntimeError, match="locked contents"):
        _prepare(install, discovered)


def test_unlocked_jar_in_flat_directory_is_rejected(install):
    extra = install["jars"] / "unlocked-helper.jar"
    _write_jar(extra)

    with pytest.raises(RuntimeError, match="locked contents"):
        _prepare(install, [*install["discovered"], str(extra)])


def test_changed_rf_source_manifest_is_rejected(install):
    source = install["root"] / "engine/ee_rf_adapter.scala"
    source.write_text("changed after build\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="source engine/ee_rf_adapter.scala SHA-256 mismatch"):
        _prepare(install)


def test_changed_base_manifest_bytes_are_rejected(install):
    manifest_path = install["jars"] / BASE_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="does not match the installed base adapter"):
        _prepare(install)


def test_smile_manifest_and_committed_lock_must_agree(install):
    manifest_path = install["jars"] / RF_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["smile_jars"][SMILE_JARS[0]]["sha256"] = "0" * 64
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="disagrees with the committed dependency lock"):
        _prepare(install)


def test_second_slf4j_api_owner_is_rejected(install):
    rf_path = install["jars"] / RF_JAR
    _write_jar(
        rf_path,
        classes=(RF_PROVIDER_CLASS, "org/slf4j/LoggerFactory.class"),
        service=SERVICE_ENTRY,
    )
    manifest_path = install["jars"] / RF_MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["jar_sha256"] = _digest(rf_path)
    _write_json(manifest_path, manifest)

    with pytest.raises(RuntimeError, match="SLF4J API class has duplicate or missing owners"):
        _prepare(install)


def test_engine_profile_allows_only_exact_rf_verification_files(monkeypatch, tmp_path):
    root = tmp_path / "project"
    for directory in (".venv", ".native/engine", ".native/jars", "engine", "deploy", "scripts", "jdk"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for relative in (
        ".native/engine-lock.json",
        "deploy/smile-rf-lock.json",
        "scripts/build_smile_rf_adapter.py",
    ):
        (root / relative).write_text("synthetic non-secret metadata\n", encoding="utf-8")
    monkeypatch.setenv("JAVA_HOME", str(root / "jdk"))
    monkeypatch.setattr(sandbox_module.sys, "platform", "darwin")
    original_is_file = Path.is_file
    monkeypatch.setattr(
        Path,
        "is_file",
        lambda path: str(path) == "/usr/bin/sandbox-exec" or original_is_file(path),
    )

    reads = sandbox_module.runtime_reads(root, sys.executable, engine=True)
    policy = sandbox_module.profile(reads=reads, writes=[tmp_path], spark=True)
    rules = policy.splitlines()
    expected_files = (
        root / ".native/engine-lock.json",
        root / "deploy/smile-rf-lock.json",
        root / "scripts/build_smile_rf_adapter.py",
    )

    for path in expected_files:
        assert path in reads
        assert f'(allow file-read* (literal {json.dumps(str(path.resolve()))}))' in rules

    forbidden = (
        root / "deploy",
        root / "scripts",
        root / "vendor",
        root / "deploy/native-lock.json",
        root / "scripts/build_integer_adapter.py",
        root / ".native/config.json",
    )
    for path in forbidden:
        assert f'(allow file-read* (subpath {json.dumps(str(path.resolve()))}))' not in rules
        assert f'(allow file-read* (literal {json.dumps(str(path.resolve()))}))' not in rules


def test_native_entrypoint_uses_package_imports_with_script_sys_path(tmp_path):
    root = Path(__file__).resolve().parents[1]
    engine_dir = root / "engine"
    temp_jars = tmp_path / "empty-jars"
    temp_jars.mkdir()
    probe = r'''import os, pathlib, sys, types
root = pathlib.Path(sys.argv[1])
scratch = pathlib.Path(sys.argv[2])
engine_dir = root / "engine"
sys.path[:] = [str(engine_dir), str(root)] + [
    item for item in sys.path
    if pathlib.Path(item or ".").resolve() not in {engine_dir.resolve(), root.resolve()}
]
import engine.ee_process_adapters as adapters
import engine.smile_rf_runtime as runtime
assert adapters.__package__ == "engine"
assert "ee_process_adapters" not in sys.modules
marker = object()
sampling = types.ModuleType("engine.ee_sampling")
sampling.local_ee_train_minimum_distance = lambda args, env: marker
sys.modules["engine.ee_sampling"] = sampling
assert adapters.local_ee_train_minimum_distance({}, {}) is marker
registered = []
validated = []
expected_classpath = ["/verified/local-ee-smile-rf-adapter.jar", "/verified/local-ee-integer-adapter.jar"]
def prepare(paths, jars, project_root, spark_home):
    assert paths == ["/discovered/upstream.jar"]
    validated.append(True)
    return expected_classpath
runtime.prepare_local_classpath = prepare
def register():
    assert sys.modules["engine.ee_process_adapters"] is adapters
    assert "ee_process_adapters" not in sys.modules
    registered.append(True)
adapters.register_local_ee_processes = register

class Conf:
    def __init__(self): self.values = {"spark.jars": "/discovered/upstream.jar"}
    def get(self, key): return self.values.get(key)
    def set(self, key, value): self.values[key] = value
conf = Conf()
gps = types.ModuleType("geopyspark")
gps.geopyspark_conf = lambda **kwargs: conf
sys.modules["geopyspark"] = gps

class SparkContext:
    @staticmethod
    def getOrCreate(candidate):
        assert candidate is conf
        assert conf.get("spark.jars") == ""
        assert validated == [True]
        assert conf.get("spark.driver.extraClassPath") == ":".join(expected_classpath)
        assert conf.get("spark.executor.extraClassPath") == ":".join(expected_classpath)
        return types.SimpleNamespace(setLogLevel=lambda value: None)
pyspark = types.ModuleType("pyspark")
pyspark.SparkContext = SparkContext
sys.modules["pyspark"] = pyspark
deploy = types.SimpleNamespace(load_custom_processes=lambda: None)
openeo = types.ModuleType("openeogeotrellis")
openeo.deploy = deploy
sys.modules["openeogeotrellis"] = openeo
os.environ["GEOPYSPARK_JARS_PATH"] = str(scratch)
namespace = {"__name__": "native_run_script_probe", "__file__": str(engine_dir / "native_run.py")}
exec(
    compile((engine_dir / "native_run.py").read_text(), str(engine_dir / "native_run.py"), "exec"),
    namespace,
)
namespace["setup"](scratch)
assert registered == [True]
print("native-import-probe-ok")
'''
    completed = subprocess.run(
        [sys.executable, "-c", probe, str(root), str(temp_jars)],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root), "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "native-import-probe-ok" in completed.stdout
