"""Exact scalar integer semantics and the native GeoTrellis Float64 SPI slice."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from gee.ee_integer import (
    INT64_MAX,
    INT64_MIN,
    SUPPORTED_INTEGER_FUNCTIONS,
    bit_count64,
    bitwise_binary_nonnegative64,
    bitwise_not_smallest_signed,
    invoke_integer,
    shift64,
)
from gee.ee_translate import Translator, UnsupportedEEError


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-integer-1.7.49.json"


def _invoke(name, **arguments):
    return invoke_integer(Translator([], {}, None), name, arguments)


@pytest.mark.parametrize(("value", "expected"), [
    (0, 0), (1, 1), (2, 1), (3, 2), (0xFFFF, 16),
    (-1, 64), (-2, 63), (INT64_MIN, 1), (INT64_MAX, 63),
])
def test_bit_count_uses_signed_64_bit_twos_complement(value, expected):
    assert bit_count64(value) == expected


@pytest.mark.parametrize(("value", "expected"), [
    (0, -1), (1, -2), (25, -26), (127, -128),
    (128, -129), (-128, 127), (-129, 128),
    (32767, -32768), (32768, -32769),
    (INT64_MIN, INT64_MAX), (INT64_MAX, INT64_MIN),
])
def test_bitwise_not_uses_smallest_signed_type_that_contains_input(value, expected):
    assert bitwise_not_smallest_signed(value) == expected


@pytest.mark.parametrize(("op", "left", "right", "expected"), [
    ("bitwiseAnd", 25, 21, 17),
    ("bitwiseOr", 25, 21, 29),
    ("bitwiseXor", 25, 21, 12),
])
def test_binary_bitwise_nonnegative_integer_examples(op, left, right, expected):
    assert bitwise_binary_nonnegative64(op, left, right) == expected


def test_binary_bitwise_rejects_negative_inputs_without_width_evidence():
    with pytest.raises(UnsupportedEEError, match="negative operands is not verified"):
        bitwise_binary_nonnegative64("bitwiseAnd", -1, 0xFF)


@pytest.mark.parametrize(("op", "left", "right", "expected"), [
    ("leftShift", 20, 2, 80),
    ("rightShift", 20, 2, 5),
    ("rightShift", -8, 2, -2),
    ("rightShift", INT64_MIN, 63, -1),
])
def test_shift_operations_on_bounded_integer_domain(op, left, right, expected):
    assert shift64(op, left, right) == expected


@pytest.mark.parametrize("value", [1.5, float("nan"), float("inf"), True, INT64_MAX + 1, INT64_MIN - 1])
def test_integer_operations_refuse_implicit_truncation_and_out_of_range(value):
    with pytest.raises(UnsupportedEEError):
        bit_count64(value)


def test_shift_refuses_unverified_overflow_and_invalid_counts():
    with pytest.raises(UnsupportedEEError):
        shift64("leftShift", INT64_MAX, 1)
    for count in (-1, 64):
        with pytest.raises(UnsupportedEEError):
            shift64("rightShift", 1, count)
    with pytest.raises(UnsupportedEEError, match="negative inputs is not verified"):
        shift64("leftShift", -1, 1)


@pytest.mark.parametrize(("name", "arguments", "expected"), [
    ("Number.bitCount", {"input": -2}, 63),
    ("Number.bitwiseNot", {"input": 25}, -26),
    ("Number.bitwiseAnd", {"left": 25, "right": 21}, 17),
    ("Number.bitwiseOr", {"left": 25, "right": 21}, 29),
    ("Number.bitwiseXor", {"left": 25, "right": 21}, 12),
    ("Number.leftShift", {"left": 20, "right": 2}, 80),
    ("Number.rightShift", {"left": -8, "right": 2}, -2),
])
def test_static_number_integer_dispatch(name, arguments, expected):
    assert invoke_integer(Translator([], {}, None), name, arguments) == expected


def test_dispatch_is_limited_to_number_bitwise_methods_and_checks_arguments():
    assert SUPPORTED_INTEGER_FUNCTIONS == frozenset({
        "Number.bitCount", "Number.bitwiseNot", "Number.bitwiseAnd",
        "Number.bitwiseOr", "Number.bitwiseXor", "Number.leftShift",
        "Number.rightShift",
    })
    with pytest.raises(UnsupportedEEError, match="Unsupported Earth Engine integer"):
        _invoke("Image.toInt16", input=1)
    with pytest.raises(UnsupportedEEError, match="requires left"):
        _invoke("Number.bitwiseAnd", right=1)
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        _invoke("Number.bitCount", input=1, width=8)


def _final_invocation(serialized):
    if serialized["type"] == "Invocation":
        return serialized
    assert serialized["type"] == "CompoundValue"
    reference = serialized["value"]["value"]
    return dict(serialized["scope"])[reference]


def test_fixture_uses_the_pinned_official_sdk_and_covers_integer_signatures():
    fixture = json.loads(FIXTURE.read_text())
    assert fixture["sdk"] == "1.7.49"
    assert fixture["source_commit"] == "e189e4b89e785019ea5642ea8e80cb644749cd4a"
    expected = {
        "numberAnd": "Number.bitwiseAnd",
        "numberOr": "Number.bitwiseOr",
        "numberXor": "Number.bitwiseXor",
        "numberLeftShift": "Number.leftShift",
        "numberRightShift": "Number.rightShift",
        "numberSignedRightShift": "Number.rightShift",
        "numberNotSmallestSigned": "Number.bitwiseNot",
        "numberBitCountNegative": "Number.bitCount",
        "imageAnd": "Image.bitwiseAnd",
        "imageOr": "Image.bitwiseOr",
        "imageXor": "Image.bitwiseXor",
        "imageLeftShift": "Image.leftShift",
        "imageRightShift": "Image.rightShift",
        "imageNot": "Image.bitwiseNot",
        "imageToDouble": "Image.toDouble",
        "imageToFloat": "Image.toFloat",
        "imageToInt16": "Image.toInt16",
        "imageToUint16": "Image.toUint16",
        "imageToInt32": "Image.toInt32",
    }
    assert set(fixture["expressions"]) == set(expected)
    for key, function in expected.items():
        assert _final_invocation(fixture["expressions"][key])["functionName"] == function


def test_every_fixture_uses_only_offline_sdk_serialization():
    fixture = json.loads(FIXTURE.read_text())
    source = (ROOT / "scripts/ee_integer_fixtures.cjs").read_text()
    assert "ee.data.computeValue = () => { throw Error" in source
    assert "http://localhost/disabled" in source
    assert "vendor/earthengine-js" in source


def _native_paths():
    native = ROOT / ".native"
    lock_path = native / "engine-lock.json"
    if not lock_path.is_file():
        pytest.skip("native engine is not installed")
    lock = json.loads(lock_path.read_text())
    java_home = Path(lock["java_home"])
    java = java_home / "bin/java"
    scalac_jars = native / "engine/lib/python3.11/site-packages/pyspark/jars"
    if not java.is_file() or not list(scalac_jars.glob("scala-compiler-*.jar")):
        pytest.skip("locked Java/Scala native toolchain is unavailable")
    return native, lock, java_home, scalac_jars


def test_native_adapter_builds_and_executes_real_spi_tile_conversion(tmp_path):
    """Compile a tiny adapter JAR and execute it via the real upstream SPI.

    This test deliberately uses one local Spark partition and a 2x2 tile. It
    does not submit a user job or start/stop any application service.
    """
    if os.environ.get("LOCAL_EE_RUN_NATIVE_INTEGER_TEST") != "1":
        pytest.skip("set LOCAL_EE_RUN_NATIVE_INTEGER_TEST=1 for the lightweight JVM/Spark probe")
    native, lock, java_home, spark_jars_dir = _native_paths()
    adapter_jar = tmp_path / "local-ee-integer-adapter.jar"
    builder = ROOT / "scripts/build_integer_adapter.py"
    subprocess.run([
        str(ROOT / ".venv/bin/python"), str(builder), "--output", str(adapter_jar),
    ], check=True, cwd=ROOT, capture_output=True, text=True)

    scala_tools = [*spark_jars_dir.glob("scala-compiler-*.jar"),
                   *spark_jars_dir.glob("scala-library-*.jar"),
                   *spark_jars_dir.glob("scala-reflect-*.jar")]
    runtime_jars = [*spark_jars_dir.glob("*.jar"), *(native / "jars").glob("*.jar")]
    compile_cp = os.pathsep.join(str(p) for p in runtime_jars)
    compiler_cp = os.pathsep.join(str(p) for p in scala_tools)
    source = tmp_path / "IntegerAdapterProbe.scala"
    source.write_text(r'''import geotrellis.layer.{Bounds, LayoutDefinition, SpatialKey, TileLayerMetadata}
import geotrellis.proj4.CRS
    import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, IntArrayTile, IntConstantNoDataCellType, Tile, TileLayout}
    import geotrellis.vector.Extent
import org.apache.spark.{SparkConf, SparkContext}
import org.openeo.geotrelliscommon.{CubeProcessRegistry, OpenEORasterCube, OpenEORasterCubeMetadata}
import scala.jdk.CollectionConverters._

object IntegerAdapterProbe {
  def main(args: Array[String]): Unit = {
    val conf = new SparkConf().setMaster("local[1]").setAppName("local-ee-integer-probe")
      .set("spark.ui.enabled", "false")
      .set("spark.driver.host", "127.0.0.1")
      .set("spark.driver.bindAddress", "127.0.0.1")
      .set("spark.driver.memory", "1g")
      .set("spark.executor.memory", "1g")
    val sc = new SparkContext(conf)
    sc.setLogLevel("ERROR")
    try {
      val keys = CubeProcessRegistry.processIds().asScala.toSet
          assert(keys.contains("local_ee_to_double"), s"SPI process missing: $keys")
          assert(keys.contains("local_ee_to_float"), s"SPI process missing: $keys")
      val key = SpatialKey(0, 0)
      val tile = IntArrayTile(Array(17, Int.MinValue, -2, 42), 2, 2, IntConstantNoDataCellType)
      val multi = ArrayMultibandTile(Array(tile): Array[geotrellis.raster.Tile])
      val extent = Extent(0, 0, 2, 2)
      val layout = LayoutDefinition(extent, TileLayout(1, 1, 2, 2))
      val metadata = TileLayerMetadata(IntConstantNoDataCellType, layout, extent, CRS.fromEpsgCode(4326), Bounds(key, key))
      val bands = new OpenEORasterCubeMetadata(scala.collection.immutable.Seq("qa"))
      val cube = new OpenEORasterCube[SpatialKey](sc.parallelize(Seq(key -> multi), 1), metadata, bands)
      val result = CubeProcessRegistry.invoke(cube, "local_ee_to_double", java.util.Collections.emptyMap[String, Object]())
        .asInstanceOf[OpenEORasterCube[SpatialKey]]
      assert(result.metadata.cellType == DoubleConstantNoDataCellType, result.metadata.cellType.toString)
      assert(result.openEOMetadata.bands.toSeq == Seq("qa"), result.openEOMetadata.bands.toString)
      val converted = result.first()._2.band(0)
      assert(converted.cellType == DoubleConstantNoDataCellType, converted.cellType.toString)
      assert(converted.getDouble(0, 0) == 17.0, converted.getDouble(0, 0).toString)
          assert(converted.getDouble(0, 1) == -2.0, converted.getDouble(0, 1).toString)
          assert(converted.getDouble(1, 1) == 42.0, converted.getDouble(1, 1).toString)
      assert(converted.getDouble(1, 0).isNaN, converted.getDouble(1, 0).toString)
          val floatCube = CubeProcessRegistry.invoke(result, "local_ee_to_float", java.util.Collections.emptyMap[String, Object]())
            .asInstanceOf[OpenEORasterCube[SpatialKey]]
          assert(floatCube.metadata.cellType == geotrellis.raster.FloatConstantNoDataCellType, floatCube.metadata.cellType.toString)
          assert(floatCube.openEOMetadata.bands.toSeq == Seq("qa"), floatCube.openEOMetadata.bands.toString)
          val floatTile = floatCube.first()._2.band(0)
          assert(floatTile.cellType == geotrellis.raster.FloatConstantNoDataCellType, floatTile.cellType.toString)
          assert(floatTile.getDouble(0, 0) == 17.0, floatTile.getDouble(0, 0).toString)
          assert(floatTile.getDouble(1, 0).isNaN, floatTile.getDouble(1, 0).toString)
          println("SPI_OK local_ee_to_double/to_float cellType=float64/float32 nodata=NaN band=qa")
    } finally {
      sc.stop()
    }
  }
}
''', encoding="utf-8")
    classes = tmp_path / "probe-classes"
    classes.mkdir()
    compile_result = subprocess.run([
        str(java_home / "bin/java"), "-cp", compiler_cp, "scala.tools.nsc.Main",
        "-classpath", compile_cp + os.pathsep + str(adapter_jar), "-d", str(classes), str(source),
    ], check=False, cwd=ROOT, capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    run_cp = os.pathsep.join([str(classes), str(adapter_jar), *map(str, runtime_jars)])
    environment = {**os.environ,
                   "JAVA_HOME": str(java_home),
                   "SPARK_LOCAL_IP": "127.0.0.1",
                   "SPARK_LOCAL_HOSTNAME": "localhost"}
    probe = subprocess.run([
        str(java_home / "bin/java"), "-Xmx1g", "-cp", run_cp, "IntegerAdapterProbe",
    ], check=True, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=90)
    assert "SPI_OK local_ee_to_double/to_float cellType=float64/float32 nodata=NaN band=qa" in probe.stdout
