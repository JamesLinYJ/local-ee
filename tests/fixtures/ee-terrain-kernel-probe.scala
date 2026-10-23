package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.proj4.CRS
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, GridBounds, MultibandTile, Tile}
import geotrellis.spark.buffer.BufferTilesRDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, CubeProcessRegistry}

import scala.jdk.CollectionConverters._

/** Trusted standalone terrain tile probe: no SparkContext, service, or user script. */
object EeTerrainKernelProbe {
  private val mapper = new ObjectMapper()
  private val defaultSpec = LocalEeTerrainSpec.parse(
    "{\"azimuth\":\"4070e00000000000\",\"elevation\":\"4046800000000000\",\"operation\":\"slope\",\"v\":1}")

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected terrain fixture JSON path")
    val providers = java.util.ServiceLoader.load(classOf[CubeProcessProvider]).stream()
      .iterator().asScala.map(_.get())
    assert(providers.exists(_.isInstanceOf[LocalEeTerrainCubeProcessProvider]),
      "terrain ServiceLoader provider missing from adapter JAR")
    assert(CubeProcessRegistry.processIds().asScala.contains("local_ee_terrain"),
      "terrain process annotation was not registered")
    val wireRejects = verifySpecParser()
    val (budgetRejects, metricRejects) = validateBudgetAndGridLimits()
    val root = mapper.readTree(new java.io.File(args(0)))
    val cases = root.get("cases").elements().asScala.toVector
    var manualPixels = 0
    var collectionPixels = 0
    var transformCalls = 0L
    var transformObjects = 0L
    var explicitArrays = 0L
    var maxAngularError = 0.0d
    cases.foreach { testCase =>
      val manual = runManualCase(testCase)
      val collection = runCollectionCase(testCase)
      manualPixels += manual.pixels
      collectionPixels += collection.pixels
      transformCalls = Math.addExact(transformCalls, manual.transforms + collection.transforms)
      transformObjects = Math.addExact(transformObjects, manual.transformObjects + collection.transformObjects)
      explicitArrays = Math.addExact(explicitArrays, manual.arrays + collection.arrays)
      maxAngularError = math.max(maxAngularError, math.max(manual.maxAngularError, collection.maxAngularError))
    }
    val temporalKeys = verifyTemporalIsolation()
    val largeGlobalColumn = verifyLongGlobalIndex()
    println(s"TERRAIN_KERNEL_OK cases=${cases.length} manual_pixels=$manualPixels " +
      s"collection_pixels=$collectionPixels transforms=$transformCalls " +
      s"transform_objects=$transformObjects explicit_arrays=$explicitArrays " +
      s"temporal_keys=$temporalKeys global_col=$largeGlobalColumn " +
      s"max_angle_error=$maxAngularError budget_256_per_tile=21037312 " +
      s"budget_256_3x3=189335808 wire_rejects=$wireRejects " +
      s"budget_rejects=$budgetRejects metric_rejects=$metricRejects")
  }

  private final case class Counts(
    pixels: Int, transforms: Long, transformObjects: Long, arrays: Long, maxAngularError: Double
  )

  private def runManualCase(testCase: JsonNode): Counts = {
    val setup = readCase(testCase)
    val output = Array.fill(setup.width * setup.height)(Double.NaN)
    var transforms = 0L
    var transformObjects = 0L
    var arrays = 0L
    setup.tileKeys.foreach { case (tileCol, tileRow) =>
      val bufferCols = Math.addExact(setup.tileCols, 2)
      val bufferRows = Math.addExact(setup.tileRows, 2)
      val bufferValues = Array.fill(Math.multiplyExact(bufferCols, bufferRows))(Double.NaN)
      var row = 0
      while (row < bufferRows) {
        var col = 0
        while (col < bufferCols) {
          val globalCol = Math.addExact(Math.multiplyExact(tileCol.toLong, setup.tileCols.toLong), col.toLong - 1L)
          val globalRow = Math.addExact(Math.multiplyExact(tileRow.toLong, setup.tileRows.toLong), row.toLong - 1L)
          if (inside(globalCol, globalRow, setup) &&
              setup.tileKeys((globalCol.toInt / setup.tileCols, globalRow.toInt / setup.tileRows))) {
            bufferValues(row * bufferCols + col) = setup.values(globalRow.toInt * setup.width + globalCol.toInt)
          }
          col += 1
        }
        row += 1
      }
      val buffered = DoubleArrayTile(bufferValues, bufferCols, bufferRows, DoubleConstantNoDataCellType)
      val result = LocalEeTerrainNumeric.applyBufferedTile(buffered,
        GridBounds[Int](1, 1, setup.tileCols, setup.tileRows), setup.tileCols, setup.tileRows,
        tileCol, tileRow, setup.grid, setup.transform, setup.spec)
      write(output, setup, tileCol, tileRow, result.tile)
      transforms = Math.addExact(transforms, result.transformCalls)
      transformObjects = Math.addExact(transformObjects, result.transformCalls)
      arrays = Math.addExact(arrays, result.explicitArrayCount.toLong)
    }
    val maxError = compare(testCase, setup, output)
    Counts(output.length, transforms, transformObjects, arrays, maxError)
  }

  private def runCollectionCase(testCase: JsonNode): Counts = {
    val setup = readCase(testCase)
    val tiles: Seq[(SpatialKey, MultibandTile)] = setup.tileKeys.toVector.map { case (tileCol, tileRow) =>
      val values = Array.ofDim[Double](setup.tileCols * setup.tileRows)
      var row = 0
      while (row < setup.tileRows) {
        var col = 0
        while (col < setup.tileCols) {
          val globalCol = tileCol * setup.tileCols + col
          val globalRow = tileRow * setup.tileRows + row
          values(row * setup.tileCols + col) = setup.values(globalRow * setup.width + globalCol)
          col += 1
        }
        row += 1
      }
      val band = DoubleArrayTile(values, setup.tileCols, setup.tileRows, DoubleConstantNoDataCellType)
      SpatialKey(tileCol, tileRow) -> ArrayMultibandTile(Array[Tile](band))
    }
    val bounds = GridBounds[Int](0, 0, setup.width / setup.tileCols - 1,
      setup.height / setup.tileRows - 1)
    val buffered = BufferTilesRDD(tiles, 1, bounds).toMap
    val observed = tiles.iterator.map(_._1).toSet
    assert(buffered.keySet == observed,
      s"${testCase.get("name").asText()}: collection buffering changed observed tile keys")

    val output = Array.fill(setup.width * setup.height)(Double.NaN)
    var transforms = 0L
    var arrays = 0L
    buffered.foreach { case (key, tile) =>
      val result = LocalEeTerrainNumeric.applyBufferedTile(tile.tile.band(0), tile.targetArea,
        setup.tileCols, setup.tileRows, key.col, key.row, setup.grid, setup.transform, setup.spec)
      write(output, setup, key.col, key.row, result.tile)
      transforms = Math.addExact(transforms, result.transformCalls)
      arrays = Math.addExact(arrays, result.explicitArrayCount.toLong)
    }
    val maxError = compare(testCase, setup, output)
    Counts(output.length, transforms, transforms, arrays, maxError)
  }

  private final case class CaseData(
    width: Int, height: Int, tileCols: Int, tileRows: Int, values: Array[Double],
    expected: Array[Double], tileKeys: Set[(Int, Int)], grid: LocalEeTerrainMetric.Grid,
    transform: (Double, Double) => (Double, Double), spec: LocalEeTerrainSpec.Value,
    tolerance: Double
  )

  private def readCase(node: JsonNode): CaseData = {
    val width = node.get("width").asInt()
    val height = node.get("height").asInt()
    val tileCols = node.get("tile_cols").asInt()
    val tileRows = node.get("tile_rows").asInt()
    val values = doubles(node.get("values"))
    val expected = doubles(node.get("expected"))
    assert(values.length == width * height && expected.length == width * height)
    val keys = node.get("existing_tiles").elements().asScala.map(value =>
      value.get(0).asInt() -> value.get(1).asInt()).toSet
    val grid = LocalEeTerrainMetric.Grid(node.get("xmin").asDouble(), node.get("ymax").asDouble(),
      node.get("cell_width").asDouble(), node.get("cell_height").asDouble(), width.toLong, height.toLong)
    CaseData(width, height, tileCols, tileRows, values, expected, keys, grid,
      LocalEeTerrainMetric.fromCrs(parseCrs(node.get("crs").asText())),
      LocalEeTerrainSpec.parse(node.get("spec").asText()), node.get("tolerance_degrees").asDouble())
  }

  private def write(output: Array[Double], setup: CaseData, tileCol: Int, tileRow: Int, tile: Tile): Unit = {
    var row = 0
    while (row < tile.rows) {
      var col = 0
      while (col < tile.cols) {
        val globalCol = Math.addExact(Math.multiplyExact(tileCol.toLong, tile.cols.toLong), col.toLong)
        val globalRow = Math.addExact(Math.multiplyExact(tileRow.toLong, tile.rows.toLong), row.toLong)
        output(globalRow.toInt * setup.width + globalCol.toInt) = tile.getDouble(col, row)
        col += 1
      }
      row += 1
    }
  }

  private def compare(node: JsonNode, setup: CaseData, actual: Array[Double]): Double = {
    var compared = 0
    var maxError = 0.0d
    var index = 0
    while (index < actual.length) {
      val wanted = setup.expected(index)
      val got = actual(index)
      val col = index % setup.width
      val row = index / setup.width
      val outputKey = (col / setup.tileCols, row / setup.tileRows)
      if (!setup.tileKeys(outputKey) || wanted.isNaN) {
        assert(got.isNaN,
          s"${node.get("name").asText()}[$col,$row]: expected NoData, got $got")
      } else {
        assert(got.isFinite,
          s"${node.get("name").asText()}[$col,$row]: expected $wanted, got $got")
        if (setup.spec.operation == "hillshade") {
          assert(got == wanted && got >= 0.0d && got <= 255.0d,
            s"${node.get("name").asText()}[$col,$row]: hillshade rounding expected $wanted, got $got")
        } else if (setup.spec.operation == "slope" &&
                   math.abs(wanted) < 1.0e-300 && wanted != 0.0d) {
          val tolerance = math.max(32.0d * math.ulp(wanted), math.abs(wanted) * 1.0e-6d)
          assert(math.abs(got - wanted) <= tolerance && got != 0.0d,
            s"${node.get("name").asText()}[$col,$row]: subnormal-scale expected $wanted ± $tolerance, got $got")
          maxError = math.max(maxError, math.abs(got - wanted))
        } else {
          val tolerance = setup.tolerance + math.abs(wanted) * 2.0e-8d
          val rawError = math.abs(got - wanted)
          val error = if (setup.spec.operation == "aspect") math.min(rawError, 360.0d - rawError)
            else rawError
          assert(error <= tolerance,
            s"${node.get("name").asText()}[$col,$row]: expected $wanted ± $tolerance, got $got")
          maxError = math.max(maxError, error)
        }
        if (setup.spec.operation == "aspect")
          assert(got >= 0.0d && got < 360.0d,
            s"${node.get("name").asText()}[$col,$row]: aspect must be canonical [0,360), got $got")
      }
      compared += 1
      index += 1
    }
    assert(compared == setup.width * setup.height)
    maxError
  }

  private def verifySpecParser(): Int = {
    val slope = "{\"azimuth\":\"4070e00000000000\",\"elevation\":\"4046800000000000\",\"operation\":\"slope\",\"v\":1}"
    assert(LocalEeTerrainSpec.parse(slope) == defaultSpec)
    val hillshade = "{\"azimuth\":\"0000000000000000\",\"elevation\":\"0000000000000000\",\"operation\":\"hillshade\",\"v\":1}"
    assert(LocalEeTerrainSpec.parse(hillshade).azimuth == 0.0d)
    val invalid = Seq(
      slope.replace("\"v\":1", "\"v\":2"),
      slope.replace("4070e00000000000", "c070e00000000000"),
      slope.replace("4070e00000000000", "4076800000000000"),
      slope.replace("4070e00000000000", "4070E00000000000"),
      slope.replace(",\"elevation\"", ", \"elevation\""),
      slope.dropRight(1) + ",\"v\":1}",
      slope.dropRight(1) + " {}",
      slope.replace("\"operation\":\"slope\"", "\"operation\":\"unknown\""),
      slope.replace("\"operation\":\"slope\"", "\"operation\":\"slope\",\"extra\":0")
    )
    invalid.foreach { text =>
      assert(rejected(() => LocalEeTerrainSpec.parse(text)), s"accepted invalid terrain wire: $text")
    }
    invalid.length
  }

  private def validateBudgetAndGridLimits(): (Int, Int) = {
    val plan = LocalEeTerrainBudget.plan(9L, 256, 256)
    assert(plan.perTileWork == 21037312L)
    assert(plan.totalWork == 189335808L)
    assert(plan.bufferedCells == 66564L && plan.maxTransformCalls == 599076L)
    assert(plan.transformResultObjects == plan.maxTransformCalls)
    assert(plan.explicitArrayCount == 81L)
    assert(plan.explicitArrayBytes == 9L * (256L * 256L * 8L + 66564L * 41L + 104L))
    val rejects = Seq(
      () => LocalEeTerrainBudget.plan(0L, 3, 3),
      () => LocalEeTerrainBudget.plan(100001L, 3, 3),
      () => LocalEeTerrainBudget.plan(1L, 1, 3),
      () => LocalEeTerrainBudget.plan(100000L, 32, 32),
      () => LocalEeTerrainBudget.plan(1L, 600, 600),
      () => LocalEeTerrainBudget.plan(48L, 256, 256),
      () => LocalEeTerrainBudget.plan(1L, 3163, 3163)
    )
    rejects.foreach(action => assert(rejected(action), "terrain work/cell/key cap was not enforced"))

    assert(rejected(() => LocalEeTerrainMetric.Grid(0.0d, 1.0d, 1.0d, 1.0d,
      (1L << 52) + 1L, 2L)), "half-cell indexing cap must reject dimensions above 2^52")
    assert(rejected(() => LocalEeTerrainMetric.Grid(0.0d, 1.0d, Double.NaN, 1.0d, 3L, 3L)),
      "non-finite grid spacing must be rejected")
    val singular = Array(0.0d, 0.0d, 0.0d, 0.0d)
    assert(rejected(() => LocalEeTerrainMetric.validateMatrix(singular)),
      "unresolvable/singular metric must fail clearly")
    val polar = new LocalEeTerrainMetric.CoordinateCache(
      LocalEeTerrainMetric.Grid(-1.5d, 91.5d, 1.0d, 1.0d, 3L, 3L),
      0, 0, 3, 3, (_: Double, _: Double) => (0.0d, 90.0d))
    val polarError = try {
      polar.matrixAt(1L, 1L, new Array[Double](4))
      None
    } catch {
      case error: IllegalArgumentException => Option(error.getMessage)
    }
    assert(polarError.exists(message =>
      message.contains("valid WGS84 coordinates") || message.contains("poles")),
      s"polar metric must fail for invalid WGS84/polar coordinates, got: ${polarError.orNull}")
    assert(rejected(() => new LocalEeTerrainMetric.CoordinateCache(
      LocalEeTerrainMetric.Grid(0.0d, 1.0d, 1.0d, 1.0d, 3L, 3L), 0, 0,
      Int.MaxValue, 2, (_: Double, _: Double) => (0.0d, 0.0d))),
      "one-pixel cache-size overflow must be rejected before allocation")
    (rejects.length, 5)
  }

  private def verifyLongGlobalIndex(): Long = {
    val grid = LocalEeTerrainMetric.Grid(-20.0d, 1.0d, 1.0e-8d, 0.01d,
      4294967296L, 4L)
    val cache = new LocalEeTerrainMetric.CoordinateCache(grid, Int.MaxValue, 0, 2, 2,
      (x: Double, y: Double) => (x, y))
    val col = Math.multiplyExact(Int.MaxValue.toLong, 2L)
    assert(col > Int.MaxValue.toLong)
    val matrix = new Array[Double](4)
    cache.matrixAt(col, 1L, matrix)
    assert(LocalEeTerrainMetric.validateMatrix(matrix) > 0.0d)
    assert(cache.transformCalls <= 16L)
    col
  }

  private def verifyTemporalIsolation(): Int = {
    val tileCols = 3
    val tileRows = 3
    val grid = LocalEeTerrainMetric.Grid(499970.0d, 4200030.0d, 10.0d, 10.0d, 6L, 6L)
    val transform = LocalEeTerrainMetric.fromCrs(CRS.fromEpsgCode(32610))
    val spec = defaultSpec
    val tiles: Seq[(SpaceTimeKey, MultibandTile)] = (100L to 200L by 100L).flatMap { instant =>
      for {
        tileRow <- 0 until 2
        tileCol <- 0 until 2
      } yield {
        val values = Array.ofDim[Double](tileCols * tileRows)
        var row = 0
        while (row < tileRows) {
          var col = 0
          while (col < tileCols) {
            val globalCol = tileCol * tileCols + col
            val globalRow = tileRow * tileRows + row
            values(row * tileCols + col) = globalCol + 2.0d * globalRow +
              (if (instant == 200L) 100.0d else 0.0d)
            col += 1
          }
          row += 1
        }
        val band = DoubleArrayTile(values, tileCols, tileRows, DoubleConstantNoDataCellType)
        SpaceTimeKey(tileCol, tileRow, instant) -> ArrayMultibandTile(Array[Tile](band))
      }
    }
    val bounds = GridBounds[Int](0, 0, 1, 1)
    val buffered = BufferTilesRDD(tiles, 1, bounds).toMap
    assert(buffered.keySet == tiles.iterator.map(_._1).toSet,
      "SpaceTimeKey BufferTilesRDD must preserve all and only observed temporal keys")
    val outputs = buffered.map { case (key, item) =>
      val tile = LocalEeTerrainNumeric.applyBufferedTile(item.tile.band(0), item.targetArea,
        tileCols, tileRows, key.col, key.row, grid, transform, spec).tile
      key -> tile
    }
    val seamChecks = Seq(
      (SpaceTimeKey(0, 0, 100L), 2, 1), (SpaceTimeKey(1, 0, 100L), 0, 1),
      (SpaceTimeKey(0, 0, 100L), 1, 2), (SpaceTimeKey(0, 1, 100L), 1, 0)
    )
    seamChecks.foreach { case (key, col, row) =>
      val first = outputs(key).getDouble(col, row)
      val second = outputs(SpaceTimeKey(key.col, key.row, 200L)).getDouble(col, row)
      assert(first.isFinite && first == second,
        s"temporal terrain halo leaked across times at ${key.col},${key.row}: $first vs $second")
    }
    for (tileRow <- 0 until 2; tileCol <- 0 until 2) {
      val first = outputs(SpaceTimeKey(tileCol, tileRow, 100L))
      val second = outputs(SpaceTimeKey(tileCol, tileRow, 200L))
      var row = 0
      while (row < tileRows) {
        var col = 0
        while (col < tileCols) {
          val firstValue = first.getDouble(col, row)
          val secondValue = second.getDouble(col, row)
          assert((firstValue.isNaN && secondValue.isNaN) || firstValue == secondValue,
            s"temporal terrain output differed at $tileCol,$tileRow,$col,$row")
          col += 1
        }
        row += 1
      }
    }
    outputs.size
  }

  private def inside(col: Long, row: Long, setup: CaseData): Boolean =
    col >= 0L && col < setup.width && row >= 0L && row < setup.height

  private def doubles(node: JsonNode): Array[Double] = node.elements().asScala.map { value =>
    if (value.isNull) Double.NaN else value.asDouble()
  }.toArray

  private def parseCrs(text: String): CRS = {
    require(text.startsWith("EPSG:"), s"unsupported test CRS identifier: $text")
    CRS.fromEpsgCode(text.substring("EPSG:".length).toInt)
  }

  private def rejected(action: () => Any): Boolean = {
    try { action(); false }
    catch { case _: IllegalArgumentException | _: ArithmeticException => true }
  }
}
