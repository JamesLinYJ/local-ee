package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, GridBounds, MultibandTile, Tile}
import geotrellis.spark.buffer.BufferTilesRDD

import scala.collection.JavaConverters._

object EeFocalKernelProbe {
  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected focal cases JSON path")
    validateSpecParser()
    validateBudgetAccounting()
    val root = new ObjectMapper().readTree(new java.io.File(args(0)))
    val cases = root.get("cases").elements().asScala.toVector
    var compared = 0
    var collectionCompared = 0
    cases.foreach { testCase =>
      compared += runManualCase(testCase)
      collectionCompared += runCollectionCase(testCase)
    }
    val temporalKeys = verifyTemporalIsolation()
    println(s"FOCAL_KERNEL_OK cases=${cases.length} manual_pixels=$compared collection_pixels=$collectionCompared temporal_keys=$temporalKeys budget_checks=7")
  }

  private def validateSpecParser(): Unit = {
    val valid = "{\"iterations\":1,\"offsets\":[[0,0]],\"operation\":\"mean\",\"skip_masked\":true,\"v\":1}"
    assert(LocalEeFocalSpec.parse(valid).operation == "mean")
    val rejected = Seq(
      valid.replace("\"v\":1", "\"v\":2"),
      valid.replace("\"operation\":\"mean\"", "\"operation\":\"sum\""),
      valid.replace("[[0,0]]", "[[1,0],[0,0]]"),
      valid.replace("[[0,0]]", "[[0,0],[0,0]]"),
      valid.replace("\"iterations\":1", "\"iterations\":1.0"),
      valid.replace("\"iterations\":1", "\"iterations\":9"),
      valid.replace("\"skip_masked\":true", "\"skip_masked\":1"),
      valid.dropRight(1) + " {}",
      valid.replace("\"skip_masked\":true", "\"skip_masked\":true,\"extra\":0"),
      valid.replace(",", ", "),
      "{\"v\":1,\"iterations\":1,\"offsets\":[[0,0]],\"operation\":\"mean\",\"skip_masked\":true}",
      valid.dropRight(1) + ",\"v\":1}",
      valid.replace("\"operation\":\"mean\"", "\"operation\":\"m\u00e9an\""),
      valid + (" " * 32768)
    )
    rejected.foreach { text =>
      var didReject = false
      try LocalEeFocalSpec.parse(text)
      catch { case _: IllegalArgumentException => didReject = true }
      assert(didReject, s"focal spec parser accepted invalid input: $text")
    }
  }

  private def validateBudgetAccounting(): Unit = {
    val offsets = (-16 to 16).flatMap(dy => (-16 to 16).map(dx => LocalEeFocalSpec.Offset(dx, dy))).toVector
    val spec = LocalEeFocalSpec.Value("mean", offsets, 1, skipMasked = true)
    assert(LocalEeFocalBudget.ExactAccumulatorLimbs == 34L)
    assert(LocalEeFocalBudget.plan(12L, 32, 32, spec).keyCount == 12L)
    assert(rejectedBudget(() => LocalEeFocalBudget.plan(13L, 32, 32, spec)),
      "mean exact-accumulator work must count its 34-limb factor against the total cap")

    val pixelWork = LocalEeFocalSpec.Value("mean", Vector(LocalEeFocalSpec.Offset(0, 0)), 1, skipMasked = true)
    assert(rejectedBudget(() => LocalEeFocalBudget.plan(1L, 1400, 1400, pixelWork)),
      "mean exact-accumulator work must count against the per-tile cap")

    val radiusOne = (-1 to 1).flatMap(dy => (-1 to 1).map(dx => LocalEeFocalSpec.Offset(dx, dy))).toVector
    val ordinaryMean = LocalEeFocalSpec.Value("mean", radiusOne, 1, skipMasked = true)
    val ordinaryMedian = LocalEeFocalSpec.Value("median", radiusOne, 1, skipMasked = true)
    assert(LocalEeFocalBudget.plan(1L, 256, 256, ordinaryMean).keyCount == 1L,
      "ordinary 256x256 radius-1 mean should fit the work budget")
    assert(LocalEeFocalBudget.plan(1L, 256, 256, ordinaryMedian).keyCount == 1L,
      "ordinary 256x256 radius-1 median should fit the work budget")
    val edgeRadius = LocalEeFocalSpec.Value("mean", Vector(LocalEeFocalSpec.Offset(2, 0)), 1, skipMasked = true)
    assert(rejectedBudget(() => LocalEeFocalBudget.plan(1L, 3, 2, edgeRadius)),
      "positive radius equal to the smaller tile dimension must be rejected")
    val identity = LocalEeFocalSpec.Value("mean", Vector(LocalEeFocalSpec.Offset(0, 0)), 1, skipMasked = true)
    assert(LocalEeFocalBudget.plan(1L, 1, 1, identity).keyCount == 1L,
      "zero-radius identity should fit a one-cell tile")
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
    val offsets = testCase.get("offsets").elements().asScala.map { pair =>
      LocalEeFocalSpec.Offset(pair.get(0).asInt(), pair.get(1).asInt())
    }.toVector
    val operation = testCase.get("operation").asText()
    val iterations = testCase.get("iterations").asInt()
    val skipMasked = testCase.get("skip_masked").asBoolean()
    val spec = LocalEeFocalSpec.Value(operation, offsets, iterations, skipMasked)
    val radius = math.max(spec.radiusX, spec.radiusY)
      assert(radius == 0 || radius < math.min(tileCols, tileRows))
    val tileKeys = testCase.get("existing_tiles").elements().asScala.map { key =>
      (key.get(0).asInt(), key.get(1).asInt())
    }.toSet
    var values = doubles(testCase.get("values"))
    val expected = doubles(testCase.get("expected"))
    var iteration = 0
    while (iteration < iterations) {
      val next = Array.fill(width * height)(Double.NaN)
      tileKeys.foreach { case (tileCol, tileRow) =>
        val bufferCols = tileCols + radius * 2
        val bufferRows = tileRows + radius * 2
        val bufferValues = Array.fill(bufferCols * bufferRows)(Double.NaN)
        var row = 0
        while (row < bufferRows) {
          var col = 0
          while (col < bufferCols) {
            val globalCol = tileCol * tileCols + col - radius
            val globalRow = tileRow * tileRows + row - radius
            if (globalCol >= 0 && globalCol < width && globalRow >= 0 && globalRow < height &&
              tileKeys((globalCol / tileCols, globalRow / tileRows))) {
              bufferValues(row * bufferCols + col) = values(globalRow * width + globalCol)
            }
            col += 1
          }
          row += 1
        }
        val buffered = DoubleArrayTile(bufferValues, bufferCols, bufferRows, DoubleConstantNoDataCellType)
        val target = GridBounds[Int](radius, radius, radius + tileCols - 1, radius + tileRows - 1)
        val output = LocalEeFocalNumeric.applyBufferedTile(buffered, target, tileCols, tileRows, spec)
        row = 0
        while (row < tileRows) {
          var col = 0
          while (col < tileCols) {
            val globalCol = tileCol * tileCols + col
            val globalRow = tileRow * tileRows + row
            next(globalRow * width + globalCol) = output.getDouble(col, row)
            col += 1
          }
          row += 1
        }
      }
      values = next
      iteration += 1
    }
    var count = 0
    var index = 0
    while (index < expected.length) {
      val actual = values(index)
      val wanted = expected(index)
      if (wanted.isNaN) assert(actual.isNaN, s"${testCase.get("name").asText()}[$index]: expected NoData, got $actual")
      else {
        assert(actual.isFinite, s"${testCase.get("name").asText()}[$index]: expected finite $wanted, got $actual")
        assert(java.lang.Double.doubleToRawLongBits(actual) == java.lang.Double.doubleToRawLongBits(wanted),
          s"${testCase.get("name").asText()}[$index]: expected exact $wanted, got $actual")
      }
      count += 1
      index += 1
    }
    count
  }

  private def runCollectionCase(testCase: JsonNode): Int = {
    val width = testCase.get("width").asInt()
    val height = testCase.get("height").asInt()
    val tileCols = testCase.get("tile_cols").asInt()
    val tileRows = testCase.get("tile_rows").asInt()
    val offsets = testCase.get("offsets").elements().asScala.map { pair =>
      LocalEeFocalSpec.Offset(pair.get(0).asInt(), pair.get(1).asInt())
    }.toVector
    val operation = testCase.get("operation").asText()
    val iterations = testCase.get("iterations").asInt()
    val skipMasked = testCase.get("skip_masked").asBoolean()
    val spec = LocalEeFocalSpec.Value(operation, offsets, iterations, skipMasked)
    val radius = math.max(spec.radiusX, spec.radiusY)
    val tileKeys = testCase.get("existing_tiles").elements().asScala.map { key =>
      (key.get(0).asInt(), key.get(1).asInt())
    }.toSet
    val bounds = GridBounds[Int](0, 0, width / tileCols - 1, height / tileRows - 1)
    var values = doubles(testCase.get("values"))
    val expected = doubles(testCase.get("expected"))
    var iteration = 0
    while (iteration < iterations) {
      val tiles: Seq[(SpatialKey, MultibandTile)] = tileKeys.toVector.map { case (tileCol, tileRow) =>
        val data = Array.ofDim[Double](tileCols * tileRows)
        var row = 0
        while (row < tileRows) {
          var col = 0
          while (col < tileCols) {
            val globalCol = tileCol * tileCols + col
            val globalRow = tileRow * tileRows + row
            data(row * tileCols + col) = values(globalRow * width + globalCol)
            col += 1
          }
          row += 1
        }
        val band = DoubleArrayTile(data, tileCols, tileRows, DoubleConstantNoDataCellType)
        SpatialKey(tileCol, tileRow) -> ArrayMultibandTile(Array[Tile](band))
      }
      // Exercise GeoTrellis' collection overload directly; this path needs no SparkContext.
      val next = Array.fill(width * height)(Double.NaN)
      val observedKeys = tiles.iterator.map(_._1).toSet
      if (radius == 0) {
        tiles.foreach { case (key, tile) =>
          writeTileOutput(next, width, key,
            LocalEeFocalNumeric.applyBufferedTile(
              tile.band(0), GridBounds[Int](0, 0, tileCols - 1, tileRows - 1), tileCols, tileRows, spec))
        }
      } else {
        val buffered = BufferTilesRDD(tiles, radius, bounds).toMap
        assert(buffered.keySet == observedKeys,
          s"${testCase.get("name").asText()}: bufferTiles synthesized or dropped a source tile")
        buffered.foreach { case (key, tile) =>
          val output = LocalEeFocalNumeric.applyBufferedTile(
            tile.tile.band(0), tile.targetArea, tileCols, tileRows, spec)
          writeTileOutput(next, width, key, output)
        }
      }
      values = next
      iteration += 1
    }
    compare(testCase, values, expected)
  }

  private def writeTileOutput(
    destination: Array[Double], width: Int, key: SpatialKey, output: Tile
  ): Unit = {
    var row = 0
    while (row < output.rows) {
      var col = 0
      while (col < output.cols) {
        val globalCol = key.col * output.cols + col
        val globalRow = key.row * output.rows + row
        destination(globalRow * width + globalCol) = output.getDouble(col, row)
        col += 1
      }
      row += 1
    }
  }

  private def verifyTemporalIsolation(): Int = {
    def tile(value: Double): MultibandTile = {
      val band = DoubleArrayTile(Array(value, value, value, value), 2, 2, DoubleConstantNoDataCellType)
      ArrayMultibandTile(Array[Tile](band))
    }
    val tiles = Seq(
      SpaceTimeKey(0, 0, 100L) -> tile(1d),
      SpaceTimeKey(1, 0, 100L) -> tile(3d),
      SpaceTimeKey(0, 0, 200L) -> tile(100d),
      SpaceTimeKey(1, 0, 200L) -> tile(300d)
    )
    val spec = LocalEeFocalSpec.Value("mean", Vector(
      LocalEeFocalSpec.Offset(0, 0), LocalEeFocalSpec.Offset(1, 0)), 1, skipMasked = false)
    val buffered = BufferTilesRDD(tiles, 1, GridBounds[Int](0, 0, 1, 0)).toMap
    assert(buffered.keySet == tiles.iterator.map(_._1).toSet,
      "SpaceTimeKey bufferTiles changed the observed key set")
    val outputs = buffered.map { case (key, value) =>
      key -> LocalEeFocalNumeric.applyBufferedTile(
        value.tile.band(0), value.targetArea, 2, 2, spec)
    }
    assert(outputs(SpaceTimeKey(0, 0, 100L)).getDouble(1, 0) == 2d,
      "SpaceTimeKey bufferTiles mixed data across observed times")
    assert(outputs(SpaceTimeKey(0, 0, 200L)).getDouble(1, 0) == 200d,
      "SpaceTimeKey bufferTiles mixed data across observed times")
    assert(outputs(SpaceTimeKey(1, 0, 100L)).getDouble(1, 0) == 3d)
    assert(outputs(SpaceTimeKey(1, 0, 200L)).getDouble(1, 0) == 300d)
    outputs.size
  }

  private def compare(testCase: JsonNode, actualValues: Array[Double], expected: Array[Double]): Int = {
    assert(actualValues.length == expected.length)
    var index = 0
    while (index < expected.length) {
      val actual = actualValues(index)
      val wanted = expected(index)
      if (wanted.isNaN) assert(actual.isNaN, s"${testCase.get("name").asText()}[$index]: expected NoData, got $actual")
      else {
        assert(actual.isFinite, s"${testCase.get("name").asText()}[$index]: expected finite $wanted, got $actual")
        assert(java.lang.Double.doubleToRawLongBits(actual) == java.lang.Double.doubleToRawLongBits(wanted),
          s"${testCase.get("name").asText()}[$index]: expected exact $wanted, got $actual")
      }
      index += 1
    }
    expected.length
  }

  private def doubles(node: JsonNode): Array[Double] =
    node.elements().asScala.map(value => if (value.isNull) Double.NaN else value.asDouble()).toArray
}
