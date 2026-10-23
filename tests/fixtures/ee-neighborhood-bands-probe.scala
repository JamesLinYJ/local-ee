package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, Tile}
import geotrellis.raster.GridBounds

import scala.collection.JavaConverters._

/** Standalone actual GeoTrellis shifted-pixel check using compiler-emitted focal specs. */
object EeNeighborhoodBandsProbe {
  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected neighborhood-band cases JSON path")
    val root = new ObjectMapper().readTree(new java.io.File(args(0)))
    val width = root.get("width").asInt()
    val height = root.get("height").asInt()
    val tileCols = root.get("tile_cols").asInt()
    val tileRows = root.get("tile_rows").asInt()
    val tileKeys = root.get("existing_tiles").elements().asScala.map { key =>
      (key.get(0).asInt(), key.get(1).asInt())
    }.toSet
    val inputBands = root.get("input_bands").elements().asScala.map(readDoubles).toVector
    val cases = root.get("outputs").elements().asScala.toVector
    require(cases.nonEmpty, "compiled neighborhood expansion must have output cases")

    var compared = 0
    var centerFillChecks = 0
    var missingTileChecks = 0
    var missingNeighborChecks = 0
    val actualByName = scala.collection.mutable.Map.empty[String, Array[Double]]

    cases.foreach { outputCase =>
      val name = outputCase.get("name").asText()
      val source = inputBands(outputCase.get("input_band").asInt())
      val spec = LocalEeFocalSpec.parse(outputCase.get("spec").asText())
      require(spec.operation == "mean" && spec.iterations == 1 && !spec.skipMasked,
        s"$name must use the neighborhoodToBands copy spec")
      require(spec.offsets.length == 1, s"$name must contain one compiled offset")
      val offset = spec.offsets.head
      val radius = math.max(math.abs(offset.dx), math.abs(offset.dy))
      val actual = Array.fill(width * height)(Double.NaN)
      val bufferedCols = tileCols + 2 * radius
      val bufferedRows = tileRows + 2 * radius
      val target = GridBounds[Int](radius, radius, radius + tileCols - 1, radius + tileRows - 1)

      tileKeys.foreach { case (tileCol, tileRow) =>
        val bufferedValues = Array.fill(bufferedCols * bufferedRows)(Double.NaN)
        var row = 0
        while (row < bufferedRows) {
          var col = 0
          while (col < bufferedCols) {
            val globalCol = tileCol * tileCols + col - radius
            val globalRow = tileRow * tileRows + row - radius
            if (globalCol >= 0 && globalCol < width && globalRow >= 0 && globalRow < height &&
              tileKeys((globalCol / tileCols, globalRow / tileRows))) {
              bufferedValues(row * bufferedCols + col) = source(globalRow * width + globalCol)
            }
            col += 1
          }
          row += 1
        }
        val buffered = DoubleArrayTile(
          bufferedValues, bufferedCols, bufferedRows, DoubleConstantNoDataCellType,
        )
        val shifted: Tile = LocalEeFocalNumeric.applyBufferedTile(
          buffered, target, tileCols, tileRows, spec,
        )
        row = 0
        while (row < tileRows) {
          var col = 0
          while (col < tileCols) {
            val globalCol = tileCol * tileCols + col
            val globalRow = tileRow * tileRows + row
            actual(globalRow * width + globalCol) = shifted.getDouble(col, row)
            col += 1
          }
          row += 1
        }
      }

      val expected = readDoubles(outputCase.get("expected"))
      require(expected.length == actual.length, s"$name expected grid has the wrong size")
      var index = 0
      while (index < expected.length) {
        val wanted = expected(index)
        val found = actual(index)
        if (wanted.isNaN) assert(found.isNaN, s"$name[$index]: expected NoData, got $found")
        else {
          assert(found.isFinite, s"$name[$index]: expected $wanted, got NoData")
          assert(java.lang.Double.doubleToRawLongBits(found) == java.lang.Double.doubleToRawLongBits(wanted),
            s"$name[$index]: expected $wanted, got $found")
        }
        index += 1
      }
      actualByName(name) = actual
      compared += expected.length
    }

    val redCenterFill = actualByName("red_0_1")
    val redSource = inputBands(0)
    val maskedCenterIndex = 2 * width + 2
    val validNeighborIndex = 3 * width + 2
    assert(redSource(maskedCenterIndex).isNaN, "red center fixture must be masked")
    assert(redCenterFill(maskedCenterIndex) == redSource(validNeighborIndex),
      "valid red neighbor must fill a masked center")
    centerFillChecks += 1

    val redMissingTile = actualByName("red_2_-1")
    val tileGapNeighborIndex = 1 * width + 4
    assert(tileKeys((0, 0)) && !tileKeys((1, 0)), "fixture must omit the upper-right source tile")
    assert(redMissingTile(maskedCenterIndex).isNaN && redSource(tileGapNeighborIndex).isFinite,
      "neighbor in an absent tile must be NoData even when the backing array has a value")
    missingTileChecks += 1

    val redDown = actualByName("red_0_1")
    val missingNeighborCenter = 2 * width + 1
    val missingNeighborIndex = 3 * width + 1
    assert(redSource(missingNeighborIndex).isNaN && redDown(missingNeighborCenter).isNaN,
      "an explicitly masked neighbor must remain NoData")
    missingNeighborChecks += 1

    println(s"NEIGHBORHOOD_BANDS_KERNEL_OK outputs=${cases.length} compared=$compared " +
      s"masked_center_fills=$centerFillChecks missing_tile_nodata=$missingTileChecks " +
      s"missing_neighbor_nodata=$missingNeighborChecks")
  }

  private def readDoubles(node: JsonNode): Array[Double] = {
    node.elements().asScala.map { value =>
      if (value == null || value.isNull) Double.NaN else value.asDouble()
    }.toArray
  }
}
