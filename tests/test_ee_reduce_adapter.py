"""Opt-in Spark probes for exact singleton-time removal and Float64 band reducers."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _native_runtime():
    native = ROOT / ".native"
    lock_path = native / "engine-lock.json"
    if not lock_path.is_file():
        pytest.skip("native engine is not installed")
    lock = json.loads(lock_path.read_text())
    java_home = Path(lock["java_home"])
    spark_jars = native / "engine/lib/python3.11/site-packages/pyspark/jars"
    if not (java_home / "bin/java").is_file() or not list(spark_jars.glob("scala-compiler-*.jar")):
        pytest.skip("locked Java/Scala native toolchain is unavailable")
    return native, java_home, spark_jars


def test_reducer_sources_are_in_the_atomic_adapter_build():
    builder = (ROOT / "scripts/build_integer_adapter.py").read_text()
    assert 'ROOT / "engine/ee_reduce_support.scala"' in builder
    assert 'ROOT / "engine/ee_reduce_numeric.scala"' in builder
    assert 'ROOT / "engine/ee_reduce_adapter.scala"' in builder
    assert "local.ee.reduce.LocalEeReduceCubeProcessProvider\\n" in builder
    for provider in ("integer.LocalEeInteger", "grid.LocalEeGrid", "mask.LocalEeMask"):
        assert provider in builder
    assert "os.replace(staged_jar, output)" in builder and '"source_sha256"' in builder


def test_native_single_time_and_band_reducer_semantics(tmp_path):
    """Compile and run independent expected arrays on a real local[1] Spark context."""
    if os.environ.get("LOCAL_EE_RUN_NATIVE_REDUCER_TEST") != "1":
        pytest.skip("set LOCAL_EE_RUN_NATIVE_REDUCER_TEST=1 for the opt-in local[1] JVM/Spark probe")
    native, java_home, spark_jars = _native_runtime()
    runtime_jars = [*spark_jars.glob("*.jar"), *(native / "jars").glob("*.jar")]
    compiler_jars = [*spark_jars.glob("scala-compiler-*.jar"),
                     *spark_jars.glob("scala-library-*.jar"),
                     *spark_jars.glob("scala-reflect-*.jar")]
    assert len(compiler_jars) == 3
    source = tmp_path / "ReduceAdapterProbe.scala"
    source.write_text(r'''import geotrellis.layer.{Bounds, EmptyBounds, LayoutDefinition, SpatialKey, SpaceTimeKey, TileLayerMetadata}
import geotrellis.proj4.CRS
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, MutableArrayTile, Tile, TileLayout}
import geotrellis.spark.ContextRDD
import geotrellis.vector.Extent
import org.apache.spark.{SparkConf, SparkContext}
import org.openeo.geotrelliscommon.{CubeProcessRegistry, OpenEORasterCube, OpenEORasterCubeMetadata}
import local.ee.reduce.LocalEeReduceCubeProcesses
import java.lang.reflect.InvocationTargetException
import scala.collection.immutable.Seq
import scala.jdk.CollectionConverters._

object ReduceAdapterProbe {
  private val extent = Extent(0, 0, 3, 2)
  private val layout = LayoutDefinition(extent, TileLayout(1, 1, 3, 2))
  private val key = SpatialKey(0, 0)
  private val instant = 1700000000123L
  private val two53 = 9007199254740992d

  private def multi(values: Seq[Array[Double]]): MultibandTile =
    ArrayMultibandTile(values.map(v => DoubleArrayTile(v, 3, 2, DoubleConstantNoDataCellType): Tile).toArray)

  private def spatialCube(sc: SparkContext, records: Seq[(Any, MultibandTile)], names: Seq[String],
                          cubeExtent: Extent = extent, cubeLayout: LayoutDefinition = layout): OpenEORasterCube[Any] = {
    val bounds: Bounds[Any] = if (records.isEmpty) EmptyBounds else Bounds[Any](records.head._1, records.last._1)
    val metadata: TileLayerMetadata[Any] = TileLayerMetadata(DoubleConstantNoDataCellType, cubeLayout, cubeExtent,
      CRS.fromEpsgCode(32649), bounds)
    val rdd = new ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]](sc.parallelize(records, 1), metadata)
    new OpenEORasterCube[Any](rdd, metadata, new OpenEORasterCubeMetadata(names))
  }

  private def temporalCube(sc: SparkContext, dates: Seq[Long], bands: Seq[Array[Double]],
                           names: Seq[String]): OpenEORasterCube[Any] = {
    val records = dates.map(date => (SpaceTimeKey(0, 0, date): Any) -> multi(bands))
    val min = SpaceTimeKey(0, 0, dates.head)
    val max = SpaceTimeKey(0, 0, dates.last)
    val bounds: Bounds[Any] = Bounds[Any](min, max)
    val metadata: TileLayerMetadata[Any] = TileLayerMetadata(DoubleConstantNoDataCellType, layout, extent,
      CRS.fromEpsgCode(32649), bounds)
    val rdd = new ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]](sc.parallelize(records, 1), metadata)
    new OpenEORasterCube[Any](rdd, metadata, new OpenEORasterCubeMetadata(names))
  }

  private def invoke(data: Object, id: String, args: java.util.Map[String, Object]): OpenEORasterCube[Any] =
    CubeProcessRegistry.invoke(data, id, args).asInstanceOf[OpenEORasterCube[Any]]

  private def reducerArgs(name: String): java.util.HashMap[String, Object] = {
    val args = new java.util.HashMap[String, Object]()
    args.put("reducer", name)
    args
  }

  private def runReducer(cube: Object, name: String): Array[Double] =
    invoke(cube, "local_ee_reduce_bands", reducerArgs(name)).first()._2.band(0).toArrayDouble

  private def rejects(action: => Any): Boolean = try {
    action
    false
  } catch {
    case error: InvocationTargetException if error.getCause.isInstanceOf[IllegalArgumentException] => true
    case error: InvocationTargetException => throw error.getCause
    case _: IllegalArgumentException => true
  }

  private def rejectsSpark(action: => Any): Boolean = try {
    action
    false
  } catch {
    case _: org.apache.spark.SparkException => true
  }

  private def close(actual: Double, expected: Double, tolerance: Double = 1e-9): Unit =
    assert((actual - expected).abs <= tolerance, s"expected $expected but got $actual")

  def main(args: Array[String]): Unit = {
    val conf = new SparkConf().setMaster("local[1]").setAppName("local-ee-reducer-probe")
      .set("spark.ui.enabled", "false").set("spark.driver.host", "127.0.0.1")
      .set("spark.driver.bindAddress", "127.0.0.1").set("spark.driver.memory", "1g")
    val sc = new SparkContext(conf)
    sc.setLogLevel("ERROR")
    try {
      CubeProcessRegistry.clear()
      CubeProcessRegistry.register(new LocalEeReduceCubeProcesses())
      val ids = CubeProcessRegistry.processIds().asScala.toSet
      assert(ids.contains("local_ee_drop_single_time") && ids.contains("local_ee_reduce_bands"), ids.toString)

      val dropInput = temporalCube(sc, Seq(instant), Seq(
        Array(0d, -7d, 16777219d, instant.toDouble, two53, Double.NaN),
        Array(Double.NaN, 5d, -16777219d, instant.toDouble, two53, 0d)), Seq("a", "b"))
      val emptyArgs = new java.util.HashMap[String, Object]()
      val dropped = invoke(dropInput, "local_ee_drop_single_time", emptyArgs)
      val droppedTiles = dropped.collect().toMap
      assert(droppedTiles.keySet == Set(key), droppedTiles.keySet.toString)
      assert(dropped.metadata.cellType == DoubleConstantNoDataCellType)
      assert(dropped.metadata.extent == extent && dropped.metadata.layout == layout)
      assert(dropped.openEOMetadata.bands == Seq("a", "b"))
      assert(droppedTiles(key).band(0).getDouble(0, 0) == 0d, "zero must remain valid")
      assert(droppedTiles(key).band(0).getDouble(2, 0) == 16777219d, "Float64 integer must remain exact")
      assert(droppedTiles(key).band(0).getDouble(0, 1) == instant.toDouble, "epoch milliseconds must remain exact")
      assert(droppedTiles(key).band(0).getDouble(1, 1) == two53, "2^53 must remain exact")
      assert(droppedTiles(key).band(0).getDouble(2, 1).isNaN, "NoData mask must remain NaN")
      droppedTiles(key).band(0).asInstanceOf[MutableArrayTile].setDouble(0, 0, -99d)
      assert(dropInput.first()._2.band(0).getDouble(0, 0) == 0d, "output tiles must not alias source arrays")

      val epochBase = 1700000000000d
      val epochTriplet = spatialCube(sc, Seq(key -> multi(Seq(
        Array(epochBase, Double.NaN, Double.NaN, Double.NaN, Double.NaN, Double.NaN),
        Array(epochBase + 1d, Double.NaN, Double.NaN, Double.NaN, Double.NaN, Double.NaN),
        Array(epochBase + 2d, Double.NaN, Double.NaN, Double.NaN, Double.NaN, Double.NaN)))),
        Seq("t0", "t1", "t2"))
      assert(runReducer(epochTriplet, "mean")(0) == epochBase + 1d)
      assert(runReducer(epochTriplet, "sum")(0) == 5100000000003d)
      assert(runReducer(epochTriplet, "sd")(0) == 1d)
      val adjacentIntegers = spatialCube(sc, Seq(key -> multi(Seq(
        Array(16777219d, Double.NaN, Double.NaN, Double.NaN, Double.NaN, Double.NaN),
        Array(16777221d, Double.NaN, Double.NaN, Double.NaN, Double.NaN, Double.NaN)))), Seq("i0", "i1"))
      assert(runReducer(adjacentIntegers, "mean")(0) == 16777220d)
      val medianEdges = spatialCube(sc, Seq(key -> multi(Seq(
        Array(java.lang.Double.MIN_VALUE, -Double.MaxValue, Double.MaxValue, 0d, 0d, 0d),
        Array(java.lang.Double.MIN_VALUE, Double.MaxValue, Double.MaxValue, 0d, 0d, 0d)))), Seq("e0", "e1"))
      val edgeMedian = runReducer(medianEdges, "median")
      assert(edgeMedian(0) == java.lang.Double.MIN_VALUE, "median must retain subnormal values")
      assert(edgeMedian(1) == 0d && edgeMedian(2) == Double.MaxValue, "median must avoid overflow")

      val reducerInput = spatialCube(sc, Seq(key -> multi(Seq(
        Array(16777219d, 0d, -4d, Double.NaN, Double.NaN, two53),
        Array(16777219d, -2d, Double.NaN, Double.NaN, Double.NaN, instant.toDouble),
        Array(16777219d, 4d, 5d, Double.NaN, 0d, -two53)))), Seq("a", "b", "c"))
      val mean = runReducer(reducerInput, "mean")
      close(mean(0), 16777219d)
      close(mean(1), 2d / 3d)
      close(mean(2), 0.5d)
      assert(mean(3).isNaN && mean(4) == 0d)
      close(mean(5), instant.toDouble / 3d, 1e-3)
      val sum = runReducer(reducerInput, "sum")
      assert(sum(0) == 50331657d && sum(1) == 2d && sum(2) == 1d && sum(4) == 0d)
      close(sum(5), instant.toDouble, 1e-3)
      assert(sum(3).isNaN, "all-NoData sum must remain NoData")
      val median = runReducer(reducerInput, "median")
      assert(median(0) == 16777219d && median(1) == 0d && median(4) == 0d)
      close(median(2), 0.5d)
      close(median(5), instant.toDouble, 1e-3)
      assert(median(3).isNaN)
      val count = runReducer(reducerInput, "count")
      assert(count.take(3).sameElements(Array(3d, 3d, 2d)) && count(3).isNaN && count(4) == 1d && count(5) == 3d)
      val minimum = runReducer(reducerInput, "min")
      val maximum = runReducer(reducerInput, "max")
      assert(minimum(0) == 16777219d && minimum(1) == -2d && minimum(2) == -4d &&
        minimum(3).isNaN && minimum(4) == 0d && minimum(5) == -two53)
      assert(maximum(0) == 16777219d && maximum(1) == 4d && maximum(2) == 5d &&
        maximum(3).isNaN && maximum(4) == 0d && maximum(5) == two53)
      val first = runReducer(reducerInput, "first")
      val last = runReducer(reducerInput, "last")
      assert(first(0) == 16777219d && first(1) == 0d && first(2) == -4d && first(4) == 0d && first(5) == two53)
      assert(last(0) == 16777219d && last(1) == 4d && last(2) == 5d && last(4) == 0d && last(5) == -two53)
      assert(first(3).isNaN && last(3).isNaN, "all-NoData first/last must remain NoData")
      val sd = runReducer(reducerInput, "sd")
      close(sd(0), 0d)
      close(sd(1), math.sqrt(28d / 3d))
      close(sd(2), 9d / math.sqrt(2d))
      assert(sd(3).isNaN && sd(4).isNaN, "all-NoData and one-valid sample SD must be NoData")
      val expectedLargeSd = math.sqrt(two53 * two53 + instant.toDouble * instant.toDouble / 3d)
      assert(sd(5).isFinite && math.abs(sd(5) - expectedLargeSd) / expectedLargeSd < 1e-14)

      val temporalReduction = invoke(temporalCube(sc, Seq(instant, instant + 1000), Seq(
        Array(1d, 2d, 3d, 4d, 5d, 6d), Array.fill(6)(2d)), Seq("x", "y")),
        "local_ee_reduce_bands", reducerArgs("sum"))
      assert(temporalReduction.keys.collect().toSet == Set(SpaceTimeKey(0, 0, instant), SpaceTimeKey(0, 0, instant + 1000)),
        "band reduction must preserve the original temporal key")
      assert(temporalReduction.openEOMetadata.bands == Seq("v"))

      assert(rejects { invoke(reducerInput, "local_ee_drop_single_time", emptyArgs) },
        "drop_single_time must reject an already-spatial cube")
      assert(rejects { invoke(reducerInput, "local_ee_reduce_bands", reducerArgs("medianish")) })
      val missingReducer = new java.util.HashMap[String, Object]()
      assert(rejects { invoke(reducerInput, "local_ee_reduce_bands", missingReducer) })
      val extraArgument = reducerArgs("mean")
      extraArgument.put("unexpected", "x")
      assert(rejects { invoke(reducerInput, "local_ee_reduce_bands", extraArgument) })
      val wrongType = new java.util.HashMap[String, Object]()
      wrongType.put("reducer", java.lang.Integer.valueOf(2))
      assert(rejects { invoke(reducerInput, "local_ee_reduce_bands", wrongType) })

      val duplicate = spatialCube(sc, Seq(key -> multi(Seq.fill(3)(Array.fill(6)(1d))),
        key -> multi(Seq.fill(3)(Array.fill(6)(2d)))), Seq("a", "b", "c"))
      assert(rejects { invoke(duplicate, "local_ee_reduce_bands", reducerArgs("mean")) })
      assert(rejects { invoke(duplicate, "local_ee_drop_single_time", emptyArgs) })
      val multiTime = temporalCube(sc, Seq(instant, instant + 1000), Seq.fill(2)(Array.fill(6)(1d)), Seq("a", "b"))
      assert(rejects { invoke(multiTime, "local_ee_drop_single_time", emptyArgs) })
      val duplicateTime = temporalCube(sc, Seq(instant, instant), Seq.fill(2)(Array.fill(6)(1d)), Seq("a", "b"))
      assert(rejects { invoke(duplicateTime, "local_ee_drop_single_time", emptyArgs) })
      val emptyMeta: TileLayerMetadata[Any] = TileLayerMetadata(DoubleConstantNoDataCellType, layout, extent,
        CRS.fromEpsgCode(32649), EmptyBounds)
      val emptyRDD = new ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]](
        sc.emptyRDD[(Any, MultibandTile)], emptyMeta)
      val emptyCube = new OpenEORasterCube[Any](emptyRDD, emptyMeta, new OpenEORasterCubeMetadata(Seq("a")))
      assert(rejects { invoke(emptyCube, "local_ee_reduce_bands", reducerArgs("sum")) })
      assert(rejects { invoke(emptyCube, "local_ee_drop_single_time", emptyArgs) })
      val wrongTile = ArrayMultibandTile(Array[Tile](DoubleArrayTile(Array.fill(4)(1d), 2, 2,
        DoubleConstantNoDataCellType)))
      val wrongLayout = spatialCube(sc, Seq(key -> wrongTile), Seq("a"))
      assert(rejects { invoke(wrongLayout, "local_ee_reduce_bands", reducerArgs("mean")) })
      val wrongBandNames = spatialCube(sc, Seq(key -> multi(Seq.fill(2)(Array.fill(6)(1d)))), Seq("a"))
      assert(rejects { invoke(wrongBandNames, "local_ee_reduce_bands", reducerArgs("mean")) })
      val tooManyBandNames = Seq.tabulate(1001)(index => s"b$index")
      val tooManyBands = spatialCube(sc, Seq(key -> multi(Seq.fill(1001)(Array.fill(6)(1d)))), tooManyBandNames)
      assert(rejects { invoke(tooManyBands, "local_ee_reduce_bands", reducerArgs("mean")) })
      val infinite = spatialCube(sc, Seq(key -> multi(Seq(Array(Double.PositiveInfinity, 1d, 1d, 1d, 1d, 1d)))), Seq("a"))
      assert(rejectsSpark { invoke(infinite, "local_ee_reduce_bands", reducerArgs("sum")).count() })

      println("SPI_OK drop_single_time=exact+spatial_keys reducers=9 Float64=exact masks=preserved sd=sample invalid_inputs=rejected")
    } finally sc.stop()
  }
}
''', encoding="utf-8")
    classes = tmp_path / "probe-classes"
    classes.mkdir()
    classpath = os.pathsep.join(map(str, runtime_jars))
    compiler_classpath = os.pathsep.join(map(str, compiler_jars))
    compile_result = subprocess.run([
        str(java_home / "bin/java"), "-cp", compiler_classpath, "scala.tools.nsc.Main",
        "-classpath", classpath, "-d", str(classes),
        str(ROOT / "engine/ee_reduce_support.scala"),
        str(ROOT / "engine/ee_reduce_numeric.scala"),
        str(ROOT / "engine/ee_reduce_adapter.scala"), str(source),
    ], check=False, cwd=ROOT, capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    environment = {**os.environ, "JAVA_HOME": str(java_home),
                   "SPARK_LOCAL_IP": "127.0.0.1", "SPARK_LOCAL_HOSTNAME": "localhost"}
    jvm_opens = [f"--add-opens=java.base/{module}=ALL-UNNAMED" for module in (
        "java.io", "java.lang", "java.lang.invoke", "java.lang.reflect", "java.net",
        "java.nio", "java.util", "java.util.concurrent", "java.util.concurrent.atomic",
        "sun.nio.ch", "sun.nio.cs", "sun.security.action", "sun.util.calendar",
    )]
    probe = subprocess.run([
        str(java_home / "bin/java"), "-Xmx1g", *jvm_opens,
        "-cp", os.pathsep.join([str(classes), classpath]), "ReduceAdapterProbe",
    ], check=False, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=90)
    assert probe.returncode == 0, probe.stdout[-2000:] + probe.stderr[-4000:]
    assert "SPI_OK drop_single_time=exact+spatial_keys" in probe.stdout
