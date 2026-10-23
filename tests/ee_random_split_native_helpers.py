"""Independent references and locked-runtime helpers for sample/RF integration."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import types
from uuid import uuid4

import pytest

from scripts.build_integer_adapter import ROOT, _engine_paths, build as build_base_adapter, sha256


SCRATCH = ROOT.parents[1] / "work/gee-python-wave30-native"
AUDIT = (Path(os.environ["GEE_AUDIT_DIR"]) / "random-split-native"
         if os.environ.get("GEE_AUDIT_DIR")
         else ROOT / "audit/gee-python-wave30" / f"standalone-{uuid4().hex}")
FIXTURE = ROOT / "tests/fixtures/ee-random-split-native-v1.json"
SCALA_PROBE = ROOT / "tests/fixtures/ee-random-split-native-kernel.scala"
RF_BUILD_ROOT = ROOT.parents[1] / "work/gee-python-wave27-native"
RF_DEPENDENCIES = ROOT.parents[1] / "work/gee-python-wave26-native/dependencies"


def random_column_reference(identifier: str, seed: int) -> float:
    """Independent SHA-256 wire oracle for the declared system:index row key."""
    encoded = identifier.encode("utf-8")
    wire = (b"local-ee/randomColumn/sha256-rowkeys-v1\0"
            + seed.to_bytes(8, "big", signed=True)
            + (1).to_bytes(4, "big")
            + b"s" + len(encoded).to_bytes(4, "big") + encoded)
    digest = hashlib.sha256(wire).digest()
    return (int.from_bytes(digest[:8], "big") >> 11) * (2.0 ** -53)


def raw_sample_reference(fixture: dict) -> list[dict]:
    """Read the fixed raw pixels independently of the GeoTrellis helper."""
    grid = fixture["grid"]
    names = fixture["band_order"]
    bands = [row["values"] for row in fixture["bands"]]
    assert [row["name"] for row in fixture["bands"]] == names
    return [
        {
            "feature": 0,
            "row": row,
            "col": col,
            "x": grid["xmin"] + (col + 0.5) * (grid["xmax"] - grid["xmin"]) / grid["columns"],
            "y": grid["ymax"] - (row + 0.5) * (grid["ymax"] - grid["ymin"]) / grid["rows"],
            "values": [float(band[row * grid["columns"] + col]) for band in bands],
        }
        for row in range(grid["rows"])
        for col in range(grid["columns"])
    ]


def matrix_counts(features: list[dict], actual: str, predicted: str) -> list[list[int]]:
    counts = [[0, 0], [0, 0]]
    for feature in features:
        properties = feature["properties"]
        counts[int(properties[actual])][int(properties[predicted])] += 1
    return counts


def matrix_array(matrix, local_ee_confusion_value, prepare_metric_spec) -> list[list[int]]:
    result = local_ee_confusion_value(
        {"data": matrix, "spec": prepare_metric_spec("array")}, env=None,
    )
    return [[int(value) for value in row] for row in json.loads(result._payload.decode("utf-8"))]


def compiled_training_spec(fixture, parameters):
    """Compile omitted inputs from real declared sample metadata, before IPC."""
    from gee.compat.earthengine.decoder import Translator
    from gee.compat.earthengine.ir import TrainedSmileRandomForest
    from gee.ee_python_client import configure_local_ee
    from scripts.ee_python_api.offline import OfflineGuard

    collection, scene = "sentinel-2-l2a", "wave30-native-schema"
    grid = fixture["grid"]
    catalog = [{"id": collection,
                "cube:dimensions": {"bands": {"values": fixture["band_order"]}}}]
    items = {collection: [{
        "id": scene, "bbox": [grid[key] for key in ("xmin", "ymin", "xmax", "ymax")],
        "geometry": fixture["region"],
        "properties": {"system:index": scene, "system:time_start": 1735689600000},
    }]}
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        sampled = ee.Image(scene).select(fixture["band_order"]).sample(
            region=ee.Geometry(fixture["region"], proj="EPSG:4326", geodesic=False),
            seed=fixture["options"]["seed"], dropNulls=True,
        )
        training = sampled.randomColumn("split", 29).filter(ee.Filter.lt("split", 0.5))
        classifier = ee.Classifier.smileRandomForest(*[
            parameters[key] for key in (
                "number_of_trees", "variables_per_split", "min_leaf_population",
                "bag_fraction", "max_nodes", "seed",
            )
        ])
        implicit = classifier.train(training, "landcover")
        explicit = classifier.train(training, "landcover", fixture["band_order"])

        def decode(value):
            return Translator(catalog, items, {}).evaluate(
                ee.serializer.encode(value, for_cloud_api=False),
            )

        automatic_model, explicit_model = decode(implicit), decode(explicit)
    assert guard.evidence()["attempt_count"] == 0
    assert isinstance(automatic_model, TrainedSmileRandomForest)
    assert automatic_model.schema == tuple(fixture["band_order"])
    assert automatic_model.training_spec == explicit_model.training_spec
    assert automatic_model.samples.spec == explicit_model.samples.spec
    assert automatic_model.samples.operations == explicit_model.samples.operations
    return automatic_model.training_spec


def native_artifacts():
    try:
        java, _, scala_tools, runtime_jars, _ = _engine_paths()
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        pytest.skip(f"locked native Java/GeoTrellis runtime is unavailable: {exc}")
    py4j_site = ROOT / ".native/engine/lib/python3.11/site-packages"
    py4j_package = py4j_site / "py4j/java_gateway.py"
    py4j_jar = next((path for path in runtime_jars if path.name.startswith("py4j-")), None)
    if not py4j_package.is_file() or py4j_jar is None:
        pytest.skip("locked Py4J Python package or JAR is unavailable")
    if not RF_DEPENDENCIES.is_dir():
        pytest.skip("locked Smile 1.5.3 dependency directory is unavailable")
    return java, scala_tools, runtime_jars, py4j_site, py4j_jar


def build_adapters():
    base_jar = SCRATCH / "base/local-ee-integer-adapter.jar"
    base_manifest = build_base_adapter(base_jar)
    base_manifest_path = base_jar.with_suffix(base_jar.suffix + ".manifest.json")

    # The pinned RF builder accepts only its existing wave27 scratch root. Its
    # manifest is checked against the newly built current-wave base artifact.
    rf_jar = RF_BUILD_ROOT / "adapter/local-ee-smile-rf-adapter.jar"
    from scripts.build_smile_rf_adapter import build as build_rf_adapter

    rf_manifest = build_rf_adapter(rf_jar, RF_DEPENDENCIES, base_jar, base_manifest_path)
    assert base_manifest["jar_sha256"] == sha256(base_jar)
    assert rf_manifest["jar_sha256"] == sha256(rf_jar)
    assert rf_manifest["base_adapter"]["jar_sha256"] == base_manifest["jar_sha256"]
    return base_jar, base_manifest_path, base_manifest, rf_jar, rf_manifest


def compile_probe(java, scala_tools, runtime_jars, base_jar, rf_jar):
    classes = SCRATCH / "probe/classes"
    classes.mkdir(parents=True, exist_ok=True)
    # The RF adapter is intentionally thin and does not shade Smile. Keep the
    # same separately locked dependency JARs on the standalone JVM classpath.
    classpath_paths = [rf_jar, base_jar, *runtime_jars, *sorted(RF_DEPENDENCIES.glob("*.jar"))]
    assert {path.name for path in classpath_paths if path.parent == RF_DEPENDENCIES} == {
        "smile-core-1.5.3.jar", "smile-data-1.5.3.jar",
        "smile-graph-1.5.3.jar", "smile-math-1.5.3.jar",
    }
    classpath = os.pathsep.join(map(str, classpath_paths))
    compiler_classpath = os.pathsep.join(map(str, scala_tools))
    compiled = subprocess.run(
        [str(java), "-cp", compiler_classpath, "scala.tools.nsc.Main",
         "-classpath", classpath, "-d", str(classes), str(SCALA_PROBE)],
        capture_output=True, text=True, timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    return classes, classpath_paths, compiled.stderr


def loopback_gateway(monkeypatch, java, py4j_site, py4j_jar, classpath_paths):
    monkeypatch.syspath_prepend(str(py4j_site))
    try:
        from py4j.java_gateway import GatewayParameters, JavaGateway, launch_gateway
    except ImportError as exc:
        pytest.skip(f"locked Py4J Python package cannot be imported: {exc}")

    classpath = os.pathsep.join(map(str, classpath_paths))
    # launch_gateway reads the chosen port from stdout without a timeout. Track
    # its Popen handle in a worker so a blocked startup is bounded and cleaned
    # up instead of leaving a JVM behind when loopback binding is unavailable.
    import py4j.java_gateway as java_gateway_module

    original_popen = java_gateway_module.Popen
    started = {}
    result = {}

    def tracked_popen(*args, **kwargs):
        # Py4J implements create_new_process_group with preexec_fn=os.setpgrp.
        # Python callbacks between fork and exec are unsafe after native
        # libraries/threads initialize (the complete suite exposed a crash).
        # Let subprocess create the session without a Python child callback.
        assert kwargs.get("preexec_fn") is None
        kwargs["start_new_session"] = True
        process = original_popen(*args, **kwargs)
        started["process"] = process
        return process

    def launch():
        try:
            result["value"] = launch_gateway(
                port=0, jarpath=str(py4j_jar), classpath=classpath,
                java_path=str(java), enable_auth=True, return_proc=True,
                cwd=str(SCRATCH), create_new_process_group=False,
                die_on_exit=True,
                redirect_stderr=sys.stderr,
            )
        except BaseException as exc:
            result["error"] = exc

    monkeypatch.setattr(java_gateway_module, "Popen", tracked_popen)
    launcher = threading.Thread(target=launch, name="ee-component-py4j-startup", daemon=True)
    launcher.start()
    launcher.join(timeout=30)
    if launcher.is_alive():
        close_gateway(None, started.get("process"))
        launcher.join(timeout=5)
        raise RuntimeError("authenticated loopback Py4J gateway startup exceeded 30 seconds")
    if "error" in result:
        close_gateway(None, started.get("process"))
        raise result["error"]
    port, token, process = result["value"]
    gateway = None
    try:
        gateway = JavaGateway(gateway_parameters=GatewayParameters(
            address="127.0.0.1", port=port, auth_token=token,
            auto_convert=True, auto_close=False, read_timeout=30,
        ))

        # The Python bridge only needs get_jvm; this stub exposes the genuine JVM.
        try:
            import openeogeotrellis.utils as utils
        except ImportError:
            package = types.ModuleType("openeogeotrellis")
            package.__path__ = []
            utils = types.ModuleType("openeogeotrellis.utils")
            package.utils = utils
            monkeypatch.setitem(sys.modules, "openeogeotrellis", package)
            monkeypatch.setitem(sys.modules, "openeogeotrellis.utils", utils)
        monkeypatch.setattr(utils, "get_jvm", lambda: gateway.jvm, raising=False)
        return gateway, process
    except BaseException:
        close_gateway(gateway, process)
        raise


def close_gateway(gateway, process):
    if gateway is not None:
        try:
            gateway.shutdown()
        except Exception:
            pass
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
