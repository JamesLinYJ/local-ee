package local.ee.reduce

import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, GridBounds, Tile}

/** Actual nearest-nonzero distance kernel over a Float64 tile and its spatial halo. */
private[reduce] object LocalEeDistanceNumeric {
  def applyBufferedTile(
    buffered: Tile,
    target: GridBounds[Int],
    outputCols: Int,
    outputRows: Int,
    spec: LocalEeDistanceSpec.Value
  ): Tile = {
    require(buffered != null && buffered.cellType == DoubleConstantNoDataCellType,
      "distance input must be Float64 with NaN NoData")
    require(outputCols > 0 && outputRows > 0 && target != null &&
      target.colMin >= 0 && target.rowMin >= 0 && target.colMax < buffered.cols &&
      target.rowMax < buffered.rows && target.colMax - target.colMin + 1 == outputCols &&
      target.rowMax - target.rowMin + 1 == outputRows,
      "distance buffered tile target area must match the original tile dimensions")
    val output = new Array[Double](Math.toIntExact(Math.multiplyExact(outputCols.toLong, outputRows.toLong)))
    var row = 0
    while (row < outputRows) {
      var col = 0
      while (col < outputCols) {
        val centerX = target.colMin + col
        val centerY = target.rowMin + row
        val center = buffered.getDouble(centerX, centerY)
        require(center.isNaN || center.isFinite, "distance input pixels must be finite or NoData")
        output(row * outputCols + col) = if (spec.skipMasked && center.isNaN) Double.NaN
        else nearestDistance(buffered, centerX, centerY, spec)
        col += 1
      }
      row += 1
    }
    DoubleArrayTile(output, outputCols, outputRows, DoubleConstantNoDataCellType)
  }

  private def nearestDistance(tile: Tile, centerX: Int, centerY: Int, spec: LocalEeDistanceSpec.Value): Double = {
    var index = 0
    while (index < spec.offsets.length) {
      val offset = spec.offsets(index)
      val col = centerX + offset.dx
      val row = centerY + offset.dy
      if (col >= 0 && col < tile.cols && row >= 0 && row < tile.rows) {
        val value = tile.getDouble(col, row)
        require(value.isNaN || value.isFinite, "distance input pixels must be finite or NoData")
        if (!value.isNaN && value != 0.0d) return numericDistance(offset, spec.metric)
      }
      index += 1
    }
    Double.NaN
  }

  private def numericDistance(offset: LocalEeDistanceSpec.Offset, metric: String): Double = metric match {
    case "euclidean" => math.sqrt(offset.distance.toDouble)
    case "manhattan" | "chebyshev" => offset.distance.toDouble
  }
}
