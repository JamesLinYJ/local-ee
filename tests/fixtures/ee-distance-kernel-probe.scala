package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, GridBounds, IntArrayTile, IntConstantNoDataCellType, MultibandTile, Tile}
import geotrellis.spark.buffer.BufferTilesRDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, CubeProcessRegistry}

import scala.jdk.CollectionConverters._

/** Independent numeric check over real GeoTrellis tiles; never starts SparkContext. */
object EeDistanceKernelProbe {
  private val mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected distance fixture JSON path")
    val providers = java.util.ServiceLoader.load(classOf[CubeProcessProvider]).stream()
      .iterator().asScala.map(_.get())
    assert(providers.exists(_.isInstanceOf[LocalEeDistanceCubeProcessProvider]),
      "distance ServiceLoader provider missing from adapter JAR")
    assert(CubeProcessRegistry.processIds().asScala.contains("local_ee_distance"),
      "distance process annotation was not registered")

    val root = mapper.readTree(new java.io.File(args(0)))
    val cases = root.get("cases").elements().asScala.toVector
    var manualPixels = 0L
    var collectionPixels = 0L
    var maxEuclideanUlps = 0L
    cases.foreach { testCase =>
      val manual = runManualCase(testCase)
      val collection = runCollectionCase(testCase)
      manualPixels = Math.addExact(manualPixels, manual.pixels.toLong)
      collectionPixels = Math.addExact(collectionPixels, collection.pixels.toLong)
      maxEuclideanUlps = math.max(maxEuclideanUlps, math.max(manual.maxUlps, collection.maxUlps))
    }
    val wireRejects = verifySpecParser(root.get("invalid_specs"))
    val budgets = verifyBudgetBoundaries()
    val budgetGuardRejects = verifyBudgetGuards()
    val numericGuardRejects = verifyNumericGuards()
    val temporalKeys = verifyTemporalIsolation()
    val gridSlots = cases.map(_.get("expected").size().toLong).sum
    println(s"DISTANCE_KERNEL_OK cases=${cases.length} manual_pixels=$manualPixels " +
      s"collection_pixels=$collectionPixels grid_slots=$gridSlots " +
      s"temporal_keys=$temporalKeys max_euclidean_ulps=$maxEuclideanUlps " +
      s"wire_rejects=$wireRejects budget_metrics=3 " +
      s"budget_total_rejects=3 budget_guard_rejects=$budgetGuardRejects " +
      s"numeric_guard_rejects=$numericGuardRejects max_keys_euclidean=${budgets(0).acceptedKeys} " +
      s"max_keys_manhattan=${budgets(1).acceptedKeys} " +
      s"max_keys_chebyshev=${budgets(2).acceptedKeys} " +
      budgets.map(value => s"budget_${value.metric}=${value.summary}").mkString(" "))
  }

  private final case class NumericResult(pixels: Int, maxUlps: Long)

  private def runManualCase(testCase: JsonNode): NumericResult = {
    val setup = readCase(testCase)
    val output = Array.fill(setup.width * setup.height)(Double.NaN)
    setup.tileKeys.toVector.sortBy(key => (key._2, key._1)).foreach { case (tileCol, tileRow) =>
      val halo = setup.spec.halo
      val bufferCols = Math.addExact(setup.tileCols, Math.multiplyExact(2, halo))
      val bufferRows = Math.addExact(setup.tileRows, Math.multiplyExact(2, halo))
      val buffer = Array.fill(Math.multiplyExact(bufferCols, bufferRows))(Double.NaN)
      var row = 0
      while (row < bufferRows) {
        var col = 0
        while (col < bufferCols) {
          val globalCol = tileCol * setup.tileCols + col - halo
          val globalRow = tileRow * setup.tileRows + row - halo
          if (inside(globalCol, globalRow, setup) &&
              setup.tileKeys((globalCol / setup.tileCols, globalRow / setup.tileRows))) {
            buffer(row * bufferCols + col) = setup.values(globalRow * setup.width + globalCol)
          }
          col += 1
        }
        row += 1
      }
      val tile = DoubleArrayTile(buffer, bufferCols, bufferRows, DoubleConstantNoDataCellType)
      val target = GridBounds[Int](halo, halo, halo + setup.tileCols - 1,
        halo + setup.tileRows - 1)
      val result = LocalEeDistanceNumeric.applyBufferedTile(
        tile, target, setup.tileCols, setup.tileRows, setup.spec)
      write(output, setup, tileCol, tileRow, result)
    }
    NumericResult(evaluatedPixels(setup), compare(testCase, output, setup.expected, setup.spec.metric))
  }

  private def runCollectionCase(testCase: JsonNode): NumericResult = {
    val setup = readCase(testCase)
    val tiles: Seq[(SpatialKey, MultibandTile)] = setup.tileKeys.toVector.map { case (tileCol, tileRow) =>
      val values = Array.ofDim[Double](setup.tileCols * setup.tileRows)
      var row = 0
      while (row < setup.tileRows) {
        var col = 0
        while (col < setup.tileCols) {
          values(row * setup.tileCols + col) =
            setup.values((tileRow * setup.tileRows + row) * setup.width + tileCol * setup.tileCols + col)
          col += 1
        }
        row += 1
      }
      val band = DoubleArrayTile(values, setup.tileCols, setup.tileRows, DoubleConstantNoDataCellType)
      SpatialKey(tileCol, tileRow) -> ArrayMultibandTile(Array[Tile](band))
    }
    val output = Array.fill(setup.width * setup.height)(Double.NaN)
    if (setup.spec.halo == 0) {
      tiles.foreach { case (key, tile) =>
        val result = LocalEeDistanceNumeric.applyBufferedTile(
          tile.band(0), GridBounds[Int](0, 0, setup.tileCols - 1, setup.tileRows - 1),
          setup.tileCols, setup.tileRows, setup.spec)
        write(output, setup, key.col, key.row, result)
      }
    } else {
      val bounds = GridBounds[Int](0, 0, setup.width / setup.tileCols - 1,
        setup.height / setup.tileRows - 1)
      val buffered = BufferTilesRDD(tiles, setup.spec.halo, bounds).toMap
      val observed = tiles.iterator.map(_._1).toSet
      assert(buffered.keySet == observed,
        s"${testCase.get("name").asText()}: BufferTilesRDD changed observed source keys")
      buffered.foreach { case (key, tile) =>
        val result = LocalEeDistanceNumeric.applyBufferedTile(
          tile.tile.band(0), tile.targetArea, setup.tileCols, setup.tileRows, setup.spec)
        write(output, setup, key.col, key.row, result)
      }
    }
    NumericResult(evaluatedPixels(setup), compare(testCase, output, setup.expected, setup.spec.metric))
  }

  private final case class Setup(
    width: Int,
    height: Int,
    tileCols: Int,
    tileRows: Int,
    tileKeys: Set[(Int, Int)],
    values: Array[Double],
    expected: Array[Double],
    spec: LocalEeDistanceSpec.Value
  )

  private def readCase(node: JsonNode): Setup = {
    val width = node.get("width").asInt()
    val height = node.get("height").asInt()
    val tileCols = node.get("tile_cols").asInt()
    val tileRows = node.get("tile_rows").asInt()
    assert(width % tileCols == 0 && height % tileRows == 0)
    val values = doubles(node.get("values"))
    val expected = doubles(node.get("expected"))
    assert(values.length == width * height && expected.length == values.length)
    val keys = node.get("tile_keys").elements().asScala.map(value =>
      value.get(0).asInt() -> value.get(1).asInt()).toSet
    val spec = LocalEeDistanceSpec.parse(node.get("spec").asText())
    val radius = java.lang.Double.longBitsToDouble(spec.radiusBits)
    assert(radius == node.get("radius").asDouble())
    Setup(width, height, tileCols, tileRows, keys, values, expected, spec)
  }

  private def verifySpecParser(invalid: JsonNode): Int = {
    val rejects = invalid.elements().asScala.count(value => rejected {
      LocalEeDistanceSpec.parse(value.asText())
    })
    assert(rejects == invalid.size(), "malformed distance specifications must all fail closed")
    rejects
  }

  private final case class BudgetEvidence(
    metric: String, acceptedKeys: Long, offsetCount: Int, bufferedCells: Long, perTileWork: Long
  ) {
    def summary: String = s"offsets:$offsetCount,buffered:$bufferedCells,per_tile:$perTileWork,accepted_keys:$acceptedKeys"
  }

  private def verifyBudgetBoundaries(): Vector[BudgetEvidence] = {
    val cols = 256
    val rows = 256
    val radius = 16.0d
    val metrics = Vector("euclidean", "manhattan", "chebyshev")
    val plans = metrics.map { metric =>
      val spec = LocalEeDistanceSpec.parse(wire(metric, radius))
      val one = LocalEeDistanceBudget.plan(1L, cols, rows, spec)
      assert(one.halo == 16)
      assert(one.bufferedCells == 288L * 288L)
      assert(one.keyCount == 1L && one.offsetCount == spec.offsets.length)
      assert(one.perTileWork <= LocalEeDistanceBudget.MaxPerTileWork)
      val acceptedKeys = LocalEeDistanceBudget.MaxDistanceWork / one.perTileWork
      assert(acceptedKeys > 0L)
      val atBoundary = LocalEeDistanceBudget.plan(acceptedKeys, cols, rows, spec)
      assert(atBoundary.perTileWork == one.perTileWork)
      assert(Math.multiplyExact(atBoundary.keyCount, atBoundary.perTileWork) <=
        LocalEeDistanceBudget.MaxDistanceWork)
      assert(rejected {
        LocalEeDistanceBudget.plan(Math.addExact(acceptedKeys, 1L), cols, rows, spec)
      }, s"$metric must reject one key beyond the exact total-work boundary")
      BudgetEvidence(metric, acceptedKeys, one.offsetCount, one.bufferedCells, one.perTileWork)
    }
    plans
  }

  private def verifyBudgetGuards(): Int = {
    val normal = LocalEeDistanceSpec.parse(wire("euclidean", 1.0d))
    val wide = LocalEeDistanceSpec.parse(wire("chebyshev", 16.0d))
    val attempts = Seq[() => Any](
      () => LocalEeDistanceBudget.plan(0L, 256, 256, normal),
      () => LocalEeDistanceBudget.plan(-1L, 256, 256, normal),
      () => LocalEeDistanceBudget.plan(1L, 16, 16, wide),
      () => LocalEeDistanceBudget.plan(1L, 3163, 3163, normal),
      () => LocalEeDistanceBudget.plan(1L, 400, 500, wide))
    val rejects = attempts.count(attempt => rejected(attempt()))
    assert(rejects == attempts.length,
      "invalid key counts, too-small halo layout, decoded-cell and per-tile work limits must reject")
    rejects
  }

  private def verifyNumericGuards(): Int = {
    val radiusZero = LocalEeDistanceSpec.parse(wire("euclidean", 0.0d))
    val radiusOne = LocalEeDistanceSpec.parse(wire("euclidean", 1.0d))
    val wrongType = IntArrayTile(Array(1), 1, 1, IntConstantNoDataCellType)
    val small = DoubleArrayTile(Array(0.0d, 0.0d, 0.0d, 0.0d), 2, 2,
      DoubleConstantNoDataCellType)
    val centerInfinity = DoubleArrayTile(Array(Double.PositiveInfinity), 1, 1,
      DoubleConstantNoDataCellType)
    val targetInfinity = DoubleArrayTile(Array(0.0d, Double.PositiveInfinity), 2, 1,
      DoubleConstantNoDataCellType)
    val invalidAdapterInput = ArrayMultibandTile(Array[Tile](centerInfinity))
    val attempts = Seq[() => Any](
      () => LocalEeDistanceNumeric.applyBufferedTile(wrongType,
        GridBounds[Int](0, 0, 0, 0), 1, 1, radiusZero),
      () => LocalEeDistanceNumeric.applyBufferedTile(small,
        GridBounds[Int](0, 0, 0, 0), 2, 2, radiusZero),
      () => LocalEeDistanceNumeric.applyBufferedTile(centerInfinity,
        GridBounds[Int](0, 0, 0, 0), 1, 1, radiusZero),
      () => LocalEeDistanceNumeric.applyBufferedTile(targetInfinity,
        GridBounds[Int](0, 0, 0, 0), 1, 1, radiusOne),
      () => LocalEeReduceSupport.copyAsDouble(invalidAdapterInput, 1, 1, 1))
    val rejects = attempts.count(attempt => rejected(attempt()))
    assert(rejects == attempts.length,
      "numeric input type, target area, and non-finite adapter/kernel values must reject")
    rejects
  }

  private def verifyTemporalIsolation(): Int = {
    val cols = 2
    val rows = 2
    val firstTime = 1000L
    val secondTime = 2000L
    def tile(values: Double*): MultibandTile = ArrayMultibandTile(Array[Tile](
      DoubleArrayTile(values.toArray, cols, rows, DoubleConstantNoDataCellType)))
    val source: Seq[(SpaceTimeKey, MultibandTile)] = Seq(
      SpaceTimeKey(0, 0, firstTime) -> tile(0.0, 0.0, 0.0, 0.0),
      SpaceTimeKey(1, 0, firstTime) -> tile(-1.0, 0.0, 0.0, 0.0),
      SpaceTimeKey(0, 0, secondTime) -> tile(0.0, 0.0, 0.0, 0.0),
      SpaceTimeKey(1, 0, secondTime) -> tile(0.0, 0.0, 0.0, 0.0))
    val spec = LocalEeDistanceSpec.parse(wire("euclidean", 1.0d))
    val buffered = BufferTilesRDD(source, spec.halo, GridBounds[Int](0, 0, 1, 0)).toMap
    assert(buffered.keySet == source.iterator.map(_._1).toSet,
      "temporal BufferTilesRDD must preserve exactly observed SpaceTimeKeys")
    buffered.foreach { case (key, value) =>
      val result = LocalEeDistanceNumeric.applyBufferedTile(
        value.tile.band(0), value.targetArea, cols, rows, spec)
      if (key.instant == firstTime && key.col == 0)
        assert(result.getDouble(1, 0) == 1.0d,
          "same-timestamp cross-tile target must remain visible")
      if (key.instant == secondTime && key.col == 0)
        assert(result.getDouble(1, 0).isNaN,
          "distance target from another timestamp must remain isolated")
    }
    buffered.size
  }

  private def wire(metric: String, radius: Double): String =
    s"{\"metric\":\"$metric\",\"radius\":\"${hex(java.lang.Double.doubleToRawLongBits(radius))}\"," +
      "\"skip_masked\":true,\"v\":1}"

  private def hex(bits: Long): String = {
    val digits = "0123456789abcdef"
    val output = new Array[Char](16)
    var value = bits
    var index = output.length - 1
    while (index >= 0) {
      output(index) = digits.charAt((value & 0xfL).toInt)
      value = value >>> 4
      index -= 1
    }
    new String(output)
  }

  private def inside(col: Int, row: Int, setup: Setup): Boolean =
    col >= 0 && col < setup.width && row >= 0 && row < setup.height &&
      setup.tileKeys((col / setup.tileCols, row / setup.tileRows))

  private def evaluatedPixels(setup: Setup): Int =
    Math.multiplyExact(setup.tileKeys.size, Math.multiplyExact(setup.tileCols, setup.tileRows))

  private def write(
    destination: Array[Double], setup: Setup, tileCol: Int, tileRow: Int, tile: Tile
  ): Unit = {
    var row = 0
    while (row < tile.rows) {
      var col = 0
      while (col < tile.cols) {
        val globalCol = tileCol * setup.tileCols + col
        val globalRow = tileRow * setup.tileRows + row
        destination(globalRow * setup.width + globalCol) = tile.getDouble(col, row)
        col += 1
      }
      row += 1
    }
  }

  private def doubles(node: JsonNode): Array[Double] = node.elements().asScala.map { value =>
    if (value.isNull) Double.NaN
    else java.lang.Double.longBitsToDouble(java.lang.Long.parseUnsignedLong(value.asText(), 16))
  }.toArray

  private def compare(
    testCase: JsonNode, actual: Array[Double], expected: Array[Double], metric: String
  ): Long = {
    assert(actual.length == expected.length)
    var index = 0
    var maximumUlps = 0L
    while (index < expected.length) {
      val wanted = expected(index)
      val observed = actual(index)
      if (wanted.isNaN) assert(observed.isNaN,
        s"${testCase.get("name").asText()}[$index]: expected NaN NoData, got $observed")
      else if (metric == "euclidean") {
        val actualBits = java.lang.Double.doubleToRawLongBits(observed)
        val expectedBits = java.lang.Double.doubleToRawLongBits(wanted)
        val ulps = math.abs(actualBits - expectedBits)
        assert(ulps <= 1L,
          s"${testCase.get("name").asText()}[$index]: expected $wanted, got $observed ($ulps ULPs)")
        maximumUlps = math.max(maximumUlps, ulps)
      } else assert(java.lang.Double.doubleToRawLongBits(observed) ==
        java.lang.Double.doubleToRawLongBits(wanted),
        s"${testCase.get("name").asText()}[$index]: expected $wanted, got $observed")
      index += 1
    }
    maximumUlps
  }

  private def rejected(action: => Any, message: String = ""): Boolean = {
    try {
      action
      false
    } catch {
      case error: IllegalArgumentException =>
        if (message.nonEmpty) assert(error.getMessage.contains(message), error.getMessage)
        true
    }
  }
}
