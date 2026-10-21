"""Opt-in native probes for finite EE constants and precision-safe unmask."""
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


def test_native_grid_and_unmask_spi_semantics(tmp_path):
    """Compile and run a 2x2-tile Spark probe only when explicitly enabled."""
    if os.environ.get("LOCAL_EE_RUN_NATIVE_GRID_TEST") != "1":
        pytest.skip("set LOCAL_EE_RUN_NATIVE_GRID_TEST=1 for the opt-in local[1] JVM/Spark probe")
    native, java_home, spark_jars = _native_runtime()
    runtime_jars = [*spark_jars.glob("*.jar"), *(native / "jars").glob("*.jar")]
    compiler_jars = [*spark_jars.glob("scala-compiler-*.jar"),
                     *spark_jars.glob("scala-library-*.jar"),
                     *spark_jars.glob("scala-reflect-*.jar")]
    assert len(compiler_jars) == 3
    source = tmp_path / "GridMaskAdapterProbe.scala"
    source.write_text(r'''import geotrellis.layer.{Bounds, EmptyBounds, LayoutDefinition, SpatialKey, SpaceTimeKey, TileLayerMetadata}
import geotrellis.proj4.CRS
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, MutableArrayTile, Tile, TileLayout}
import geotrellis.spark.ContextRDD
import org.apache.spark.{SparkConf, SparkContext}
import org.openeo.geotrelliscommon.{CubeProcessRegistry, OpenEORasterCube, OpenEORasterCubeMetadata}
import local.ee.grid.LocalEeGridCubeProcesses
import local.ee.mask.LocalEeMaskCubeProcesses
import java.lang.reflect.InvocationTargetException
import scala.collection.immutable.Seq
import scala.jdk.CollectionConverters._
import geotrellis.vector.Extent

object GridMaskAdapterProbe {
  private val gridExtent = Extent(0, 0, 6, 2)
  private val layout = LayoutDefinition(gridExtent, TileLayout(3, 1, 2, 2))
  private val key0 = SpatialKey(0, 0)
  private val key1 = SpatialKey(1, 0)
  private val key2 = SpatialKey(2, 0)
  private val date1 = 1700000000123L
  private val date2 = 1700000000456L

  private def multi(values: Array[Double]): MultibandTile =
    ArrayMultibandTile(Array[Tile](DoubleArrayTile(values, 2, 2, DoubleConstantNoDataCellType)))

  private def spatialCube(sc: SparkContext, extent: Extent, bounds: Bounds[SpatialKey],
                          records: Seq[(SpatialKey, MultibandTile)], name: String): OpenEORasterCube[SpatialKey] = {
    val metadata = TileLayerMetadata(DoubleConstantNoDataCellType, layout, extent,
      CRS.fromEpsgCode(32649), bounds)
    new OpenEORasterCube[SpatialKey](sc.parallelize(records, 1), metadata,
      new OpenEORasterCubeMetadata(Seq(name)))
  }

  private def rawSpatialCube(sc: SparkContext, extent: Extent, bounds: Bounds[SpatialKey],
                             records: Seq[(SpatialKey, MultibandTile)]): ContextRDD[SpatialKey, MultibandTile, TileLayerMetadata[SpatialKey]] = {
    val metadata = TileLayerMetadata(DoubleConstantNoDataCellType, layout, extent,
      CRS.fromEpsgCode(32649), bounds)
    new ContextRDD[SpatialKey, MultibandTile, TileLayerMetadata[SpatialKey]](
      sc.parallelize(records, 1), metadata)
  }

  private def temporalCube(sc: SparkContext, dates: Seq[Long] = Seq(date1, date2)):
      OpenEORasterCube[SpaceTimeKey] = {
    val first = SpaceTimeKey(0, 0, dates.head)
    val last = SpaceTimeKey(0, 0, dates.last)
    val metadata = TileLayerMetadata(DoubleConstantNoDataCellType, layout, gridExtent,
      CRS.fromEpsgCode(32649), Bounds(first, last))
    val records = dates.zipWithIndex.map { case (date, index) =>
      SpaceTimeKey(0, 0, date) -> multi(Array.fill(4)(index.toDouble + 1d))
    }
    new OpenEORasterCube[SpaceTimeKey](sc.parallelize(records, 1), metadata,
      new OpenEORasterCubeMetadata(Seq("date")))
  }

  private def invoke(data: Object, process: String, args: java.util.Map[String, Object]): OpenEORasterCube[Any] =
    CubeProcessRegistry.invoke(data, process, args).asInstanceOf[OpenEORasterCube[Any]]

  private def processArgs(value: Object, sameFootprint: Boolean = true): java.util.HashMap[String, Object] = {
    val result = new java.util.HashMap[String, Object]()
    result.put("value", value)
    result.put("same_footprint", java.lang.Boolean.valueOf(sameFootprint))
    result
  }

  private def rejectsArgument(action: => Any): Boolean = try {
    action
    false
  } catch {
    case error: InvocationTargetException if error.getCause.isInstanceOf[IllegalArgumentException] => true
    case error: InvocationTargetException => throw error.getCause
    case _: IllegalArgumentException => true
  }

  def main(args: Array[String]): Unit = {
    val conf = new SparkConf().setMaster("local[1]").setAppName("local-ee-grid-mask-probe")
      .set("spark.ui.enabled", "false").set("spark.driver.host", "127.0.0.1")
      .set("spark.driver.bindAddress", "127.0.0.1").set("spark.driver.memory", "1g")
    val sc = new SparkContext(conf)
    sc.setLogLevel("ERROR")
    try {
      CubeProcessRegistry.clear()
      CubeProcessRegistry.register(new LocalEeGridCubeProcesses())
      CubeProcessRegistry.register(new LocalEeMaskCubeProcesses())
      val ids = CubeProcessRegistry.processIds().asScala.toSet
      assert(ids.contains("local_ee_constant_on_grid") && ids.contains("local_ee_unmask"), ids.toString)

      // A finite 3-tile extent with only the first source key proves both the
      // missing middle tile and missing edge tile are actually materialized.
      val inputTile = multi(Array(0d, Double.NaN, 16777217d, 1700000000123d))
      val input = spatialCube(sc, gridExtent, Bounds(key0, key0), Seq(key0 -> inputTile), "value")
      val constantArgs = new java.util.HashMap[String, Object]()
      constantArgs.put("value", java.lang.Long.valueOf(16777217L))
      val exactConstant = invoke(input, "local_ee_constant_on_grid", constantArgs)
      val constantTiles = exactConstant.collect().toMap
      assert(constantTiles.keySet == Set(key0, SpatialKey(1, 0), key2), constantTiles.keySet.toString)
      assert(constantTiles(key2).band(0).getDouble(1, 1) == 16777217d)
      assert(exactConstant.metadata.cellType == DoubleConstantNoDataCellType)
      assert(exactConstant.openEOMetadata.bands == Seq("value"))
      constantTiles(key0).band(0).asInstanceOf[MutableArrayTile].setDouble(0, 0, -11d)
      assert(constantTiles(key2).band(0).getDouble(0, 0) == 16777217d,
        "each materialized key must own an independent mutable tile")

      def constantPixel(value: Object): Double = {
        val scalarArgs = new java.util.HashMap[String, Object]()
        scalarArgs.put("value", value)
        invoke(input, "local_ee_constant_on_grid", scalarArgs).first()._2.band(0).getDouble(0, 0)
      }
      assert(constantPixel(java.lang.Long.valueOf(0L)) == 0d)
      assert(constantPixel(java.lang.Long.valueOf(-7L)) == -7d)
      assert(constantPixel(java.lang.Long.valueOf(1700000000123L)) == 1700000000123d)
      assert(constantPixel(java.lang.Long.valueOf(9007199254740992L)) == 9007199254740992d,
        "2^53 is exactly representable and must be accepted")

      val fillArgs = new java.util.HashMap[String, Object]()
      fillArgs.put("value", java.lang.Double.valueOf(9d))
      val fill = invoke(input, "local_ee_constant_on_grid", fillArgs)
      val restored = invoke(input, "local_ee_unmask", processArgs(fill, sameFootprint = true))
      val restoredTiles = restored.collect().toMap
      assert(restoredTiles.keySet == constantTiles.keySet, restoredTiles.keySet.toString)
      val restoredInput = restoredTiles(key0).band(0)
      assert(restoredInput.getDouble(0, 0) == 0d, "valid zero must stay original")
      assert(restoredInput.getDouble(1, 0) == 9d, "partial NoData must be filled")
      assert(restoredInput.getDouble(0, 1) == 16777217d, "Float64 integer must remain exact")
      assert(restoredInput.getDouble(1, 1) == 1700000000123d, "epoch milliseconds must remain exact")
      assert(restoredTiles(SpatialKey(1, 0)).band(0).getDouble(0, 0) == 9d,
        "sameFootprint=true must fill missing keys inside metadata.extent")

      val rawReplacement = rawSpatialCube(sc, gridExtent, Bounds(key0, key0),
        Seq(key0 -> multi(Array(21d, 22d, 23d, 24d))))
      val rawReplacementResult = invoke(input, "local_ee_unmask", processArgs(rawReplacement))
      assert(rawReplacementResult.first()._2.band(0).getDouble(1, 0) == 22d,
        "raw GeoTrellis ContextRDD arguments must be wrapped with raster metadata")
      assert(rawReplacementResult.openEOMetadata.bands == Seq("value"),
        "replacement band placeholder must not replace the input band name")

      // same_footprint=false allows a finite aligned raster union. Right-only
      // tiles copied from a shared input object must not alias each other.
      val unionInput = spatialCube(sc, Extent(0, 0, 2, 2), Bounds(key0, key0),
        Seq(key0 -> inputTile), "value")
      val sharedFallback = multi(Array(4d, 5d, 6d, 7d))
      val unionFallback = spatialCube(sc, Extent(2, 0, 6, 2), Bounds(key1, key2),
        Seq(key1 -> sharedFallback, key2 -> sharedFallback), "replacement")
      val finiteUnion = invoke(unionInput, "local_ee_unmask", processArgs(unionFallback, sameFootprint = false))
      val unionTiles = finiteUnion.collect().toMap
      assert(unionTiles.keySet == Set(key0, key1, key2), unionTiles.keySet.toString)
      assert(finiteUnion.metadata.extent == gridExtent, finiteUnion.metadata.extent.toString)
      assert(finiteUnion.metadata.bounds.get.minKey == key0 && finiteUnion.metadata.bounds.get.maxKey == key2,
        finiteUnion.metadata.bounds.toString)
      unionTiles(key1).band(0).asInstanceOf[MutableArrayTile].setDouble(0, 0, -22d)
      assert(unionTiles(key2).band(0).getDouble(0, 0) == 4d,
        "right-only output tiles must not alias their shared source tile")
      val sameOnly = invoke(unionInput, "local_ee_unmask", processArgs(unionFallback, sameFootprint = true))
      assert(sameOnly.keys.collect().toSet == Set(key0), "same_footprint=true must clip outside keys")

      val sharedOriginal = multi(Array(13d, 14d, 15d, 16d))
      val sparseOriginal = spatialCube(sc, gridExtent, Bounds(key0, key2),
        Seq(key0 -> inputTile, key1 -> sharedOriginal, key2 -> sharedOriginal), "value")
      val sparseFallback = spatialCube(sc, gridExtent, Bounds(key0, key0),
        Seq(key0 -> multi(Array.fill(4)(9d))), "replacement")
      val leftOnly = invoke(sparseOriginal, "local_ee_unmask", processArgs(sparseFallback, sameFootprint = true))
        .collect().toMap
      leftOnly(key1).band(0).asInstanceOf[MutableArrayTile].setDouble(0, 0, -33d)
      assert(leftOnly(key2).band(0).getDouble(0, 0) == 13d,
        "left-only output tiles must not alias their shared source tile")

      val allNoData = spatialCube(sc, gridExtent, Bounds(key0, key0),
        Seq(key0 -> multi(Array.fill(4)(Double.NaN))), "value")
      val allFilled = invoke(allNoData, "local_ee_unmask",
        processArgs(invoke(allNoData, "local_ee_constant_on_grid", fillArgs), sameFootprint = true))
      assert(allFilled.first()._2.band(0).toArrayDouble.forall(_ == 9d))

      val noDataFill = spatialCube(sc, gridExtent, Bounds(key0, key0),
        Seq(key0 -> multi(Array.fill(4)(Double.NaN))), "replacement")
      val stillNoData = invoke(input, "local_ee_unmask", processArgs(noDataFill, sameFootprint = true))
      assert(stillNoData.first()._2.band(0).getDouble(1, 0).isNaN,
        "NoData replacement must remain NoData")

      // Explicit time keys are copied exactly, with a full spatial tile grid
      // generated for each observed timestamp and no fabricated dates.
      val temporal = temporalCube(sc)
      val dateArgs = new java.util.HashMap[String, Object]()
      dateArgs.put("value", java.lang.Long.valueOf(date1))
      val temporalConstant = invoke(temporal, "local_ee_constant_on_grid", dateArgs)
      val temporalKeys = temporalConstant.keys.collect().toSet
      assert(temporalKeys.size == 6, temporalKeys.toString)
      assert(temporalKeys.collect { case key: SpaceTimeKey => key.instant }.toSet == Set(date1, date2))

      val rejectedSpatialTemporal = rejectsArgument {
        invoke(input, "local_ee_unmask", processArgs(temporal))
      }
      assert(rejectedSpatialTemporal, "SpatialKey and SpaceTimeKey cubes must not be mixed")
      val wrongTimes = temporalCube(sc, Seq(date1))
      val rejectedTimeMismatch = rejectsArgument {
        invoke(temporal, "local_ee_unmask", processArgs(wrongTimes))
      }
      assert(rejectedTimeMismatch, "temporal cubes with different observed instants must be rejected")

      val duplicateOriginal = spatialCube(sc, gridExtent, Bounds(key0, key0),
        Seq(key0 -> inputTile, key0 -> inputTile), "value")
      val rejectedDuplicateInput = rejectsArgument {
        invoke(duplicateOriginal, "local_ee_unmask", processArgs(fill))
      }
      assert(rejectedDuplicateInput, "duplicate input keys must be rejected before fullOuterJoin")
      val duplicateFallback = spatialCube(sc, gridExtent, Bounds(key0, key0),
        Seq(key0 -> multi(Array.fill(4)(9d)), key0 -> multi(Array.fill(4)(8d))), "replacement")
      val rejectedDuplicateReplacement = rejectsArgument {
        invoke(input, "local_ee_unmask", processArgs(duplicateFallback))
      }
      assert(rejectedDuplicateReplacement, "duplicate replacement keys must be rejected before fullOuterJoin")

      val emptyMetadata: TileLayerMetadata[SpatialKey] = TileLayerMetadata(DoubleConstantNoDataCellType, layout, gridExtent,
        CRS.fromEpsgCode(32649), EmptyBounds)
      val empty = new OpenEORasterCube[SpatialKey](sc.emptyRDD[(SpatialKey, MultibandTile)],
        emptyMetadata, new OpenEORasterCubeMetadata(Seq("empty")))
      val rejectedEmpty = rejectsArgument {
        invoke(empty, "local_ee_constant_on_grid", fillArgs)
      }
      assert(rejectedEmpty, "empty spatial templates without trustworthy key bounds must be rejected")

      val boundedEmptyMetadata: TileLayerMetadata[SpatialKey] = TileLayerMetadata(
        DoubleConstantNoDataCellType, layout, gridExtent, CRS.fromEpsgCode(32649), Bounds(key0, key2))
      val boundedEmpty = new OpenEORasterCube[SpatialKey](sc.emptyRDD[(SpatialKey, MultibandTile)],
        boundedEmptyMetadata, new OpenEORasterCubeMetadata(Seq("template")))
      val materializedEmpty = invoke(boundedEmpty, "local_ee_constant_on_grid", fillArgs)
      val emptyTiles = materializedEmpty.collect().toMap
      assert(emptyTiles.keySet == Set(key0, key1, key2), emptyTiles.keySet.toString)
      assert(emptyTiles.values.forall(_.band(0).toArrayDouble.forall(_ == 9d)),
        "trusted finite spatial metadata must materialize independent constant tiles")
      assert(materializedEmpty.metadata.bounds.get.minKey == key0 &&
        materializedEmpty.metadata.bounds.get.maxKey == key2)
      assert(materializedEmpty.openEOMetadata.bands == Seq("template"))
      emptyTiles(key0).band(0).asInstanceOf[MutableArrayTile].setDouble(0, 0, -44d)
      assert(emptyTiles(key1).band(0).getDouble(0, 0) == 9d,
        "empty-template generated keys must own independent tiles")

      val emptyTemporalBounds = Bounds(SpaceTimeKey(0, 0, date1), SpaceTimeKey(2, 0, date1))
      val emptyTemporalMetadata: TileLayerMetadata[SpaceTimeKey] = TileLayerMetadata(
        DoubleConstantNoDataCellType, layout, gridExtent, CRS.fromEpsgCode(32649), emptyTemporalBounds)
      val emptyTemporal = new OpenEORasterCube[SpaceTimeKey](sc.emptyRDD[(SpaceTimeKey, MultibandTile)],
        emptyTemporalMetadata, new OpenEORasterCubeMetadata(Seq("temporal-template")))
      assert(rejectsArgument {
        invoke(emptyTemporal, "local_ee_constant_on_grid", fillArgs)
      }, "empty temporal templates must not infer an instant from metadata bounds")

      val budgetExtent = Extent(0, 0, 626, 1)
      val budgetLayout = LayoutDefinition(budgetExtent, TileLayout(626, 1, 400, 400))
      val budgetKey = SpatialKey(0, 0)
      val budgetTile = multi(Array.fill(400 * 400)(1d))
      val budgetMetadata = TileLayerMetadata(DoubleConstantNoDataCellType, budgetLayout, budgetExtent,
        CRS.fromEpsgCode(32649), Bounds(budgetKey, budgetKey))
      val budgetCube = new OpenEORasterCube[SpatialKey](sc.parallelize(Seq(budgetKey -> budgetTile), 1),
        budgetMetadata, new OpenEORasterCubeMetadata(Seq("budget")))
      val rejectedBudget = rejectsArgument {
        invoke(budgetCube, "local_ee_constant_on_grid", fillArgs)
      }
      assert(rejectedBudget, "more than 100 million generated cells must be rejected before allocation")

      val unsafeArgs = new java.util.HashMap[String, Object]()
      unsafeArgs.put("value", java.lang.Long.valueOf(9007199254740993L))
      val rejectedUnsafeInteger = rejectsArgument {
        invoke(input, "local_ee_constant_on_grid", unsafeArgs)
      }
      assert(rejectedUnsafeInteger, "inexact Java integer input must fail before raster generation")
      val nonFiniteArgs = new java.util.HashMap[String, Object]()
      nonFiniteArgs.put("value", java.lang.Double.valueOf(Double.NaN))
      assert(rejectsArgument { invoke(input, "local_ee_constant_on_grid", nonFiniteArgs) },
        "non-finite constant values must be rejected")

      val shiftedLayout = LayoutDefinition(Extent(-1, 0, 5, 2), TileLayout(3, 1, 2, 2))
      val shiftedMetadata = TileLayerMetadata(DoubleConstantNoDataCellType, shiftedLayout, Extent(0, 0, 2, 2),
        CRS.fromEpsgCode(32649), Bounds(key0, key0))
      val shifted = new OpenEORasterCube[SpatialKey](sc.parallelize(Seq(key0 -> inputTile), 1), shiftedMetadata,
        new OpenEORasterCubeMetadata(Seq("replacement")))
      val rejectedLayoutMismatch = rejectsArgument {
        invoke(input, "local_ee_unmask", processArgs(shifted))
      }
      assert(rejectedLayoutMismatch, "different origins/resolutions must be rejected")

      println("SPI_OK constant_grid=complete missing_keys=middle+edge unmask=Float64 finite_union=true sameFootprint=true/false_precision=exact dates=preserved time_mismatch=rejected duplicate_keys=rejected bounded_empty_spatial=materialized ambiguous_empty_temporal=rejected empty_without_bounds=rejected cell_budget=rejected aliasing=checked")
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
        str(ROOT / "engine/ee_grid_adapter.scala"),
        str(ROOT / "engine/ee_mask_adapter.scala"), str(source),
    ], check=False, cwd=ROOT, capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stdout + compile_result.stderr
    environment = {**os.environ, "JAVA_HOME": str(java_home),
                   "SPARK_LOCAL_IP": "127.0.0.1", "SPARK_LOCAL_HOSTNAME": "localhost"}
    jvm_opens = [f"--add-opens=java.base/{module}=ALL-UNNAMED" for module in (
        "java.io", "java.lang", "java.lang.invoke", "java.lang.reflect", "java.net",
        "java.nio", "java.util", "java.util.concurrent", "java.util.concurrent.atomic",
        "sun.nio.ch", "sun.nio.cs", "sun.security.action", "sun.util.calendar",
    )]
    run_classpath = os.pathsep.join([str(classes), classpath])
    probe = subprocess.run([
        str(java_home / "bin/java"), "-Xmx1g", *jvm_opens, "-cp", run_classpath, "GridMaskAdapterProbe",
    ], check=False, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=90)
    assert probe.returncode == 0, probe.stdout[-2000:] + probe.stderr[-4000:]
    assert "SPI_OK constant_grid=complete missing_keys=middle+edge" in probe.stdout
    assert "bounded_empty_spatial=materialized ambiguous_empty_temporal=rejected" in probe.stdout
