package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, GridBounds, MultibandTile, Tile}
import geotrellis.spark.buffer.BufferTilesRDD

import scala.collection.JavaConverters._

object EeConvolveKernelProbe {
  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected convolve cases JSON path")
    validateSpecParser()
    val (threeByThreeWork, sevenBySevenWork) = validateBudgetAccounting()
    val root = new ObjectMapper().readTree(new java.io.File(args(0)))
    val cases = root.get("cases").elements().asScala.toVector
    var compared = 0
    var collectionCompared = 0
    cases.foreach { testCase =>
      compared += runManualCase(testCase)
      collectionCompared += runCollectionCase(testCase)
    }
    validateFinalOverflow(root.get("reject_overflow"))
    val temporalKeys = verifyTemporalIsolation()
    println(s"CONVOLVE_KERNEL_OK cases=${cases.length} manual_pixels=$compared " +
      s"collection_pixels=$collectionCompared temporal_keys=$temporalKeys " +
      s"budget_3x3_per_tile=$threeByThreeWork budget_7x7_per_tile=$sevenBySevenWork " +
      "budget_7x7_result=rejected budget_checks=9")
  }

  private def validateSpecParser(): Unit = {
    val valid = "{\"coefficients\":[[0,0,\"3ff0000000000000\"]],\"v\":1}"
    assert(LocalEeConvolveSpec.parse(valid).active.length == 1)
    val rejected = Seq(
      valid.replace("\"v\":1", "\"v\":2"),
      valid.replace("3ff0000000000000", "7ff0000000000000"),
      valid.replace("3ff0000000000000", "7ff8000000000000"),
      valid.replace("3ff0000000000000", "8000000000000000"),
      valid.replace("3ff0000000000000", "3FF0000000000000"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[0.0,0,\"3ff0000000000000\"]"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[33,0,\"3ff0000000000000\"]"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[0,0,\"3ff0000000000000\",0]"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[1,0,\"3ff0000000000000\"],[0,0,\"3ff0000000000000\"]"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[0,0,\"0000000000000000\"],[1,0,\"0000000000000000\"]"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[1,0,\"0000000000000000\"]"),
      valid.replace("[0,0,\"3ff0000000000000\"]", "[0,0,\"3ff0000000000000\"],[0,0,\"3ff0000000000000\"]"),
      valid.replace("{\"coefficients\":", "{\"coefficients\":").replace(",\"v\":1}", ",\"v\":1,\"v\":1}"),
      valid.dropRight(1) + " {}",
      valid.replace(",", ", "),
      "{\"v\":1,\"coefficients\":[[0,0,\"3ff0000000000000\"]]}",
      valid + (" " * 32768)
    )
    rejected.foreach { text =>
      var didReject = false
      try LocalEeConvolveSpec.parse(text)
      catch { case _: IllegalArgumentException => didReject = true }
      assert(didReject, s"convolve spec parser accepted invalid input: $text")
    }
  }

  private def validateBudgetAccounting(): (Long, Long) = {
    val ordinary = uniformKernel(3)
    val threeByThree = LocalEeConvolveBudget.plan(1L, 256, 256, ordinary)
    assert(threeByThree.perTileWork < LocalEeConvolveBudget.MaxPerTileWork,
      "ordinary 256x256 3x3 exact convolution should fit the work budget")
    assert(rejectedBudget(() => LocalEeConvolveBudget.plan(100000L, 4, 4, ordinary)),
      "aggregate exact-product work must count against the total work cap")
    val center = LocalEeConvolveSpec.parse("{\"coefficients\":[[0,0,\"3ff0000000000000\"]],\"v\":1}")
    assert(rejectedBudget(() => LocalEeConvolveBudget.plan(1L, 1400, 1400, center)),
      "exact dot work must count against the per-tile work cap")
    assert(rejectedBudget(() => LocalEeConvolveBudget.plan(20L, 1000, 10000, center)),
      "aggregate decoded input cells must be bounded")
    val radiusTwo = LocalEeConvolveSpec.parse("{\"coefficients\":[[2,0,\"3ff0000000000000\"]],\"v\":1}")
    assert(rejectedBudget(() => LocalEeConvolveBudget.plan(1L, 2, 3, radiusTwo)),
      "positive radius equal to the smaller tile dimension must reject")
    val zero = LocalEeConvolveSpec.parse("{\"coefficients\":[[0,0,\"0000000000000000\"]],\"v\":1}")
    assert(LocalEeConvolveBudget.plan(1L, 1, 1, zero).radius == 0,
      "canonical all-zero kernel should use the zero-radius budget")
    assert(rejectedBudget(() => LocalEeConvolveBudget.plan(100001L, 1, 1, center)),
      "source key count must remain bounded")

    val mixedWeightRange = LocalEeConvolveSpec.parse(
      "{\"coefficients\":[[0,0,\"0000000000000001\"],[1,0,\"7fefffffffffffff\"]],\"v\":1}")
    assert(mixedWeightRange.exactAccumulatorLimbs == 66,
      "mixed smallest-subnormal and largest-finite weights must retain the 66-limb bound")
    val seven = uniformKernel(7)
    val sevenEstimate = LocalEeConvolveBudget.estimate(1L, 256, 256, seven)
    assert(rejectedBudget(() => LocalEeConvolveBudget.plan(1L, 256, 256, seven)),
      "ordinary 256x256 7x7 exact convolution must report its per-tile budget rejection")
    assert(sevenEstimate.perTileWork > LocalEeConvolveBudget.MaxPerTileWork,
      "the 7x7 estimate must exceed the existing per-tile cap")
    (threeByThree.perTileWork, sevenEstimate.perTileWork)
  }

  private def uniformKernel(size: Int): LocalEeConvolveSpec.Value = {
    val radius = size / 2
    val coefficients = for {
      dy <- -radius to radius
      dx <- -radius to radius
    } yield s"[$dx,$dy,\"3ff0000000000000\"]"
    LocalEeConvolveSpec.parse(
      s"{\"coefficients\":[${coefficients.mkString(",")}],\"v\":1}")
  }

  private def rejectedBudget(action: () => Any): Boolean = {
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
    val spec = LocalEeConvolveSpec.parse(testCase.get("spec").asText())
    val tileKeys = readTileKeys(testCase)
    val values = readValues(testCase.get("values"))
    val expected = readValues(testCase.get("expected"))
    val result = Array.fill(width * height)(Double.NaN)
    val radius = spec.radius
    tileKeys.foreach { case (tileCol, tileRow) =>
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
            tileKeys((globalCol / tileCols, globalRow / tileRows))) {
            bufferedValues(row * bufferCols + col) = values(globalRow * width + globalCol)
          }
          col += 1
        }
        row += 1
      }
      val buffered = DoubleArrayTile(bufferedValues, bufferCols, bufferRows, DoubleConstantNoDataCellType)
      val target = GridBounds[Int](radius, radius, radius + tileCols - 1, radius + tileRows - 1)
      val output = LocalEeConvolveNumeric.applyBufferedTile(buffered, target, tileCols, tileRows, spec)
      writeTileOutput(result, width, tileCols, tileRow, tileCol, output)
    }
    compare(testCase, result, expected)
  }

  private def runCollectionCase(testCase: JsonNode): Int = {
    val width = testCase.get("width").asInt()
    val height = testCase.get("height").asInt()
    val tileCols = testCase.get("tile_cols").asInt()
    val tileRows = testCase.get("tile_rows").asInt()
    val spec = LocalEeConvolveSpec.parse(testCase.get("spec").asText())
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
    val result = Array.fill(width * height)(Double.NaN)
    val radius = spec.radius
    if (radius == 0) {
      tiles.foreach { case (key, tile) =>
        val output = LocalEeConvolveNumeric.applyBufferedTile(
          tile.band(0), GridBounds[Int](0, 0, tileCols - 1, tileRows - 1), tileCols, tileRows, spec)
        writeTileOutput(result, width, tileCols, key.row, key.col, output)
      }
    } else {
      val bounds = GridBounds[Int](0, 0, width / tileCols - 1, height / tileRows - 1)
      val buffered = BufferTilesRDD(tiles, radius, bounds).toMap
      assert(buffered.keySet == tiles.iterator.map(_._1).toSet,
        s"${testCase.get("name").asText()}: bufferTiles synthesized or dropped a source tile")
      buffered.foreach { case (key, tile) =>
        val output = LocalEeConvolveNumeric.applyBufferedTile(
          tile.tile.band(0), tile.targetArea, tileCols, tileRows, spec)
        writeTileOutput(result, width, tileCols, key.row, key.col, output)
      }
    }
    compare(testCase, result, expected)
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

  private def validateFinalOverflow(node: JsonNode): Unit = {
    val center = fromHex(node.get("center_bits").asText())
    val values = Array(center)
    val tile = DoubleArrayTile(values, 1, 1, DoubleConstantNoDataCellType)
    val spec = LocalEeConvolveSpec.parse(
      s"{\"coefficients\":[[0,0,\"${node.get("weight_bits").asText()}\"]],\"v\":1}")
    var rejected = false
    try LocalEeConvolveNumeric.applyBufferedTile(tile, GridBounds[Int](0, 0, 0, 0), 1, 1, spec)
    catch { case error: IllegalArgumentException =>
      rejected = error.getMessage.contains("final Float64 result overflowed")
    }
    assert(rejected, "final Float64 overflow must fail with an explicit convolve error")
  }

  private def verifyTemporalIsolation(): Int = {
    val cols = 3
    val rows = 2
    val times = Seq(1000L, 2000L)
    def tile(value: Double): MultibandTile = ArrayMultibandTile(Array[Tile](
      DoubleArrayTile(Array.fill(cols * rows)(value), cols, rows, DoubleConstantNoDataCellType)))
    val tileRows: Seq[(SpaceTimeKey, MultibandTile)] = Seq(
      SpaceTimeKey(0, 0, times.head) -> tile(1.0),
      SpaceTimeKey(1, 0, times.last) -> tile(10.0)
    )
    val spec = LocalEeConvolveSpec.parse(
      "{\"coefficients\":[[0,0,\"3ff0000000000000\"],[1,0,\"3ff0000000000000\"]],\"v\":1}")
    val bounds = GridBounds[Int](0, 0, 1, 0)
    val buffered = BufferTilesRDD(tileRows, 1, bounds).toMap
    val expectedKeys = tileRows.iterator.map(_._1).toSet
    assert(buffered.keySet == expectedKeys, "temporal buffer must preserve exactly the source SpaceTimeKeys")
    buffered.foreach { case (key, tile) =>
      val output = LocalEeConvolveNumeric.applyBufferedTile(
        tile.tile.band(0), tile.targetArea, cols, rows, spec)
      val base = if (key.instant == times.head) 1.0 else 10.0
      var row = 0
      while (row < rows) {
        var col = 0
        while (col < cols) {
          val value = output.getDouble(col, row)
          if (col == cols - 1) assert(value.isNaN,
            "a neighboring tile at another instant must not satisfy nonzero support")
          else assert(value == base * 2.0,
            "SpaceTimeKey convolution must use only the matching observation")
          col += 1
        }
        row += 1
      }
    }
    buffered.size
  }

  private def readTileKeys(testCase: JsonNode): Set[(Int, Int)] =
    testCase.get("tile_keys").elements().asScala.map { key => (key.get(0).asInt(), key.get(1).asInt()) }.toSet

  private def readValues(node: JsonNode): Array[Double] =
    node.elements().asScala.map { value =>
      if (value.isNull) Double.NaN else fromHex(value.asText())
    }.toArray

  private def fromHex(value: String): Double =
    java.lang.Double.longBitsToDouble(java.lang.Long.parseUnsignedLong(value, 16))
}
