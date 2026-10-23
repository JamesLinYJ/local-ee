package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, GridBounds, MultibandTile, Tile}
import geotrellis.spark.buffer.BufferTilesRDD

import scala.collection.JavaConverters._

object EeNeighborhoodKernelProbe {
  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected neighborhood cases JSON path")
    validateSpecParser()
    val (threeByThreeWork, sevenBySevenWork, varianceWork, variance128Work,
      stdDevWork, sampleStdDevWork) = validateBudgetAccounting()
    val root = new ObjectMapper().readTree(new java.io.File(args(0)))
    val cases = root.get("cases").elements().asScala.toVector
    var manualCompared = 0
    var collectionCompared = 0
    cases.foreach { testCase =>
      manualCompared += runManualCase(testCase)
      collectionCompared += runCollectionCase(testCase)
    }
    validateOverflow(root.get("reject_overflow"))
    val temporalKeys = verifyTemporalIsolation()
    println(s"NEIGHBORHOOD_KERNEL_OK cases=${cases.length} manual_pixels=$manualCompared " +
      s"collection_pixels=$collectionCompared temporal_keys=$temporalKeys " +
      s"budget_3x3_per_tile=$threeByThreeWork budget_7x7_per_tile=$sevenBySevenWork " +
      s"budget_7x7_result=rejected budget_3x3_variance_per_tile=$varianceWork " +
      s"budget_3x3_variance_result=rejected budget_128_variance_per_tile=$variance128Work " +
      s"budget_3x3_stdDev_per_tile=$stdDevWork budget_3x3_sampleStdDev_per_tile=$sampleStdDevWork " +
      "budget_checks=13")
  }

  private def validateSpecParser(): Unit = {
    val valid = "{\"coefficients\":[[0,0,\"3ff0000000000000\"]],\"operation\":\"mean\",\"skip_masked\":true,\"v\":1}"
    assert(LocalEeNeighborhoodSpec.parse(valid).coefficients.length == 1)
    val rejected = Seq(
      valid.replace("\"v\":1", "\"v\":2"),
      valid.replace("\"mean\"", "\"bogus\""),
      valid.replace("3ff0000000000000", "0000000000000000"),
      valid.replace("3ff0000000000000", "bff0000000000000"),
      valid.replace("3ff0000000000000", "7ff0000000000000"),
      valid.replace("3ff0000000000000", "7ff8000000000000"),
      valid.replace("3ff0000000000000", "3FF0000000000000"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[0.0,0,\"3ff0000000000000\"]"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[33,0,\"3ff0000000000000\"]"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[0,0,\"3ff0000000000000\",0]"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[1,0,\"3ff0000000000000\"],[0,0,\"3ff0000000000000\"]"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[0,0,\"3ff0000000000000\"],[0,0,\"3ff0000000000000\"]"),
      valid.replace("\"skip_masked\":true", "\"skip_masked\":\"yes\""),
      valid.replace("\"coefficients\":[", "\"coefficients\":[] ,\"extra\":["),
      valid.replace("{\"coefficients\":", "{\"coefficients\":").replace(",\"v\":1}", ",\"v\":1,\"v\":1}"),
      valid.replace("\"coefficients\":", "\"v\":1,\"coefficients\":").replace(",\"v\":1}", "}"),
      valid.replace(",\"operation\"", ", \"operation\""),
      valid + (" " * 32768),
      "{\"coefficients\":[],\"operation\":\"mean\",\"skip_masked\":true,\"v\":1}"
    )
    rejected.foreach { text =>
      var didReject = false
      try LocalEeNeighborhoodSpec.parse(text)
      catch { case _: IllegalArgumentException => didReject = true }
      assert(didReject, s"neighborhood spec parser accepted invalid input: $text")
    }
    val nonUniformUnweighted = valid.replace("\"mean\"", "\"median\"")
      .replace("3ff0000000000000", "4000000000000000")
    assert(rejectedInput(() => LocalEeNeighborhoodSpec.parse(nonUniformUnweighted)),
      "median must reject non-unit weights")
  }

  private def validateBudgetAccounting(): (Long, Long, Long, Long, Long, Long) = {
    val three = uniformKernel(3, "mean")
    val accepted = LocalEeNeighborhoodBudget.plan(1L, 256, 256, three)
    val seven = uniformKernel(7, "mean")
    val sevenEstimate = LocalEeNeighborhoodBudget.estimate(1L, 256, 256, seven)
    assert(accepted.perTileWork < LocalEeNeighborhoodBudget.MaxPerTileWork,
      "3x3 mean at 256x256 should fit the unchanged per-tile work cap")
    assert(sevenEstimate.perTileWork > LocalEeNeighborhoodBudget.MaxPerTileWork &&
      rejectedInput(() => LocalEeNeighborhoodBudget.plan(1L, 256, 256, seven)),
      "7x7 mean at 256x256 must report its per-tile budget rejection")
    val variance = uniformKernel(3, "variance")
    val varianceEstimate = LocalEeNeighborhoodBudget.estimate(1L, 256, 256, variance)
    assert(varianceEstimate.perTileWork > LocalEeNeighborhoodBudget.MaxPerTileWork &&
      rejectedInput(() => LocalEeNeighborhoodBudget.plan(1L, 256, 256, variance)),
      "exact rational 3x3 variance must charge large-integer moment work")
    val variance128 = LocalEeNeighborhoodBudget.plan(1L, 128, 128, variance)
    val stdDev = uniformKernel(3, "stdDev")
    val stdDevEstimate = LocalEeNeighborhoodBudget.estimate(1L, 256, 256, stdDev)
    assert(stdDevEstimate.perTileWork > varianceEstimate.perTileWork,
      "population stdDev must charge its exact integer square-root work")
    val sampleVariance = uniformKernel(3, "sampleVariance")
    val sampleStdDev = uniformKernel(3, "sampleStdDev")
    val sampleVarianceEstimate = LocalEeNeighborhoodBudget.estimate(1L, 256, 256, sampleVariance)
    val sampleStdDevEstimate = LocalEeNeighborhoodBudget.estimate(1L, 256, 256, sampleStdDev)
    assert(sampleStdDevEstimate.perTileWork > sampleVarianceEstimate.perTileWork,
      "sampleStdDev must charge its exact integer square-root work")
    val center = LocalEeNeighborhoodSpec.parse(
      "{\"coefficients\":[[0,0,\"3ff0000000000000\"]],\"operation\":\"mean\",\"skip_masked\":true,\"v\":1}")
    assert(rejectedInput(() => LocalEeNeighborhoodBudget.plan(100001L, 1, 1, center)),
      "source key count must stay bounded")
    assert(rejectedInput(() => LocalEeNeighborhoodBudget.plan(1L, 4000, 4000, center)),
      "decoded cells per tile must stay bounded")
    val radiusTwo = LocalEeNeighborhoodSpec.parse(
      "{\"coefficients\":[[2,0,\"3ff0000000000000\"]],\"operation\":\"mean\",\"skip_masked\":true,\"v\":1}")
    assert(rejectedInput(() => LocalEeNeighborhoodBudget.plan(1L, 2, 3, radiusTwo)),
      "positive radius equal to the smaller tile dimension must reject")
    assert(rejectedInput(() => LocalEeNeighborhoodBudget.plan(1000L, 256, 256, three)),
      "total weighted arithmetic must count against the aggregate work cap")
    (accepted.perTileWork, sevenEstimate.perTileWork, varianceEstimate.perTileWork,
      variance128.perTileWork, stdDevEstimate.perTileWork, sampleStdDevEstimate.perTileWork)
  }

  private def uniformKernel(size: Int, operation: String): LocalEeNeighborhoodSpec.Value = {
    val radius = size / 2
    val coefficients = for {
      dy <- -radius to radius
      dx <- -radius to radius
    } yield s"[$dx,$dy,\"3ff0000000000000\"]"
    LocalEeNeighborhoodSpec.parse(
      s"{\"coefficients\":[${coefficients.mkString(",")}],\"operation\":\"$operation\",\"skip_masked\":true,\"v\":1}")
  }

  private def rejectedInput(action: () => Any): Boolean = {
    try {
      action()
      false
    } catch {
      case _: IllegalArgumentException => true
    }
  }

  private def runManualCase(testCase: JsonNode): Int = {
    val width = testCase.get("width").asInt()
    val height = testCase.get("height").asInt()
    val tileCols = testCase.get("tile_cols").asInt()
    val tileRows = testCase.get("tile_rows").asInt()
    val spec = LocalEeNeighborhoodSpec.parse(testCase.get("spec").asText())
    val tileKeys = readTileKeys(testCase)
    val values = readValues(testCase.get("values"))
    val expected = readValues(testCase.get("expected"))
    val output = Array.fill(width * height)(Double.NaN)
    val radius = spec.radius
    tileKeys.toVector.sortBy(key => (key._2, key._1)).foreach { case (tileCol, tileRow) =>
      val bufferCols = tileCols + radius * 2
      val bufferRows = tileRows + radius * 2
      val bufferedValues = Array.fill(bufferCols * bufferRows)(Double.NaN)
      var row = 0
      while (row < bufferRows) {
        var col = 0
        while (col < bufferCols) {
          val globalCol = tileCol * tileCols + col - radius
          val globalRow = tileRow * tileRows + row - radius
          if (globalCol >= 0 && globalCol < width && globalRow >= 0 && globalRow < height &&
            tileKeys((globalCol / tileCols, globalRow / tileRows)))
            bufferedValues(row * bufferCols + col) = values(globalRow * width + globalCol)
          col += 1
        }
        row += 1
      }
      val buffered = DoubleArrayTile(bufferedValues, bufferCols, bufferRows, DoubleConstantNoDataCellType)
      val target = GridBounds[Int](radius, radius, radius + tileCols - 1, radius + tileRows - 1)
      val result = LocalEeNeighborhoodNumeric.applyBufferedTile(buffered, target, tileCols, tileRows, spec)
      writeTileOutput(output, width, tileCols, tileRow, tileCol, result)
    }
    compare(testCase, output, expected)
  }

  private def runCollectionCase(testCase: JsonNode): Int = {
    val width = testCase.get("width").asInt()
    val height = testCase.get("height").asInt()
    val tileCols = testCase.get("tile_cols").asInt()
    val tileRows = testCase.get("tile_rows").asInt()
    val spec = LocalEeNeighborhoodSpec.parse(testCase.get("spec").asText())
    val tileKeys = readTileKeys(testCase)
    val values = readValues(testCase.get("values"))
    val expected = readValues(testCase.get("expected"))
    val tiles: Seq[(SpatialKey, MultibandTile)] = tileKeys.toVector.map { case (tileCol, tileRow) =>
      val data = Array.ofDim[Double](tileCols * tileRows)
      var row = 0
      while (row < tileRows) {
        var col = 0
        while (col < tileCols) {
          data(row * tileCols + col) = values((tileRow * tileRows + row) * width + tileCol * tileCols + col)
          col += 1
        }
        row += 1
      }
      val band = DoubleArrayTile(data, tileCols, tileRows, DoubleConstantNoDataCellType)
      SpatialKey(tileCol, tileRow) -> ArrayMultibandTile(Array[Tile](band))
    }
    val output = Array.fill(width * height)(Double.NaN)
    if (spec.radius == 0) {
      tiles.foreach { case (key, tile) =>
        val result = LocalEeNeighborhoodNumeric.applyBufferedTile(tile.band(0),
          GridBounds[Int](0, 0, tileCols - 1, tileRows - 1), tileCols, tileRows, spec)
        writeTileOutput(output, width, tileCols, key.row, key.col, result)
      }
    } else {
      val bounds = GridBounds[Int](0, 0, width / tileCols - 1, height / tileRows - 1)
      val buffered = BufferTilesRDD(tiles, spec.radius, bounds).toMap
      assert(buffered.keySet == tiles.iterator.map(_._1).toSet,
        s"${testCase.get("name").asText()}: bufferTiles synthesized or dropped an observed source key")
      buffered.foreach { case (key, tile) =>
        val result = LocalEeNeighborhoodNumeric.applyBufferedTile(
          tile.tile.band(0), tile.targetArea, tileCols, tileRows, spec)
        writeTileOutput(output, width, tileCols, key.row, key.col, result)
      }
    }
    compare(testCase, output, expected)
  }

  private def writeTileOutput(
    destination: Array[Double], width: Int, tileCols: Int, tileRow: Int, tileCol: Int, output: Tile
  ): Unit = {
    var row = 0
    while (row < output.rows) {
      var col = 0
      while (col < output.cols) {
        val globalCol = tileCol * tileCols + col
        val globalRow = tileRow * output.rows + row
        destination(globalRow * width + globalCol) = output.getDouble(col, row)
        col += 1
      }
      row += 1
    }
  }

  private def compare(testCase: JsonNode, actual: Array[Double], expected: Array[Double]): Int = {
    assert(actual.length == expected.length)
    var index = 0
    while (index < expected.length) {
      val wanted = expected(index)
      val observed = actual(index)
      if (wanted.isNaN) assert(observed.isNaN,
        s"${testCase.get("name").asText()}[$index]: expected NoData, got $observed")
      else assert(java.lang.Double.doubleToRawLongBits(observed) ==
        java.lang.Double.doubleToRawLongBits(wanted),
        s"${testCase.get("name").asText()}[$index]: expected $wanted, got $observed")
      index += 1
    }
    expected.length
  }

  private def validateOverflow(node: JsonNode): Unit = {
    val maximum = fromHex(node.get("value_bits").asText())
    val tile = DoubleArrayTile(Array(maximum), 1, 1, DoubleConstantNoDataCellType)
    val spec = LocalEeNeighborhoodSpec.parse(
      s"{\"coefficients\":[[0,0,\"${node.get("weight_bits").asText()}\"]]," +
        "\"operation\":\"sum\",\"skip_masked\":true,\"v\":1}")
    var rejected = false
    try LocalEeNeighborhoodNumeric.applyBufferedTile(tile, GridBounds[Int](0, 0, 0, 0), 1, 1, spec)
    catch { case error: IllegalArgumentException =>
      rejected = error.getMessage.contains("sum final Float64 result overflowed")
    }
    assert(rejected, "final Float64 sum overflow must fail explicitly")
  }

  private def verifyTemporalIsolation(): Int = {
    val cols = 3
    val rows = 2
    val times = Seq(1000L, 2000L)
    def tile(value: Double): MultibandTile = ArrayMultibandTile(Array[Tile](
      DoubleArrayTile(Array.fill(cols * rows)(value), cols, rows, DoubleConstantNoDataCellType)))
    val source: Seq[(SpaceTimeKey, MultibandTile)] = Seq(
      SpaceTimeKey(0, 0, times.head) -> tile(1.0), SpaceTimeKey(1, 0, times.head) -> tile(2.0),
      SpaceTimeKey(0, 0, times.last) -> tile(10.0), SpaceTimeKey(1, 0, times.last) -> tile(20.0))
    val spec = LocalEeNeighborhoodSpec.parse(
      "{\"coefficients\":[[0,0,\"3ff0000000000000\"],[1,0,\"3ff0000000000000\"]]," +
        "\"operation\":\"mean\",\"skip_masked\":true,\"v\":1}")
    val buffered = BufferTilesRDD(source, 1, GridBounds[Int](0, 0, 1, 0)).toMap
    val expectedKeys = source.iterator.map(_._1).toSet
    assert(buffered.keySet == expectedKeys, "temporal buffer must preserve exactly observed SpaceTimeKeys")
    buffered.foreach { case (key, tile) =>
      val output = LocalEeNeighborhoodNumeric.applyBufferedTile(
        tile.tile.band(0), tile.targetArea, cols, rows, spec)
      val base = if (key.instant == times.head) 1.0 else 10.0
      var row = 0
      while (row < rows) {
        var col = 0
        while (col < cols) {
          val expected = if (key.col == 0 && col == cols - 1) base * 1.5
            else if (key.col == 1) base * 2.0 else base
          assert(output.getDouble(col, row) == expected,
            "SpaceTimeKey neighborhood support must use only the matching observation")
          col += 1
        }
        row += 1
      }
    }
    buffered.size
  }

  private def readTileKeys(testCase: JsonNode): Set[(Int, Int)] =
    testCase.get("tile_keys").elements().asScala.map(key => (key.get(0).asInt(), key.get(1).asInt())).toSet

  private def readValues(node: JsonNode): Array[Double] =
    node.elements().asScala.map(value => if (value.isNull) Double.NaN else fromHex(value.asText())).toArray

  private def fromHex(value: String): Double =
    java.lang.Double.longBitsToDouble(java.lang.Long.parseUnsignedLong(value, 16))
}
