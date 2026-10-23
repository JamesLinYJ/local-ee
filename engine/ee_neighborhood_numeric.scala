package local.ee.reduce

import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, GridBounds, Tile}

/** Actual Float64 neighborhood statistics over one GeoTrellis tile and its spatial halo. */
private[reduce] object LocalEeNeighborhoodNumeric {
  def applyBufferedTile(
    buffered: Tile,
    target: GridBounds[Int],
    outputCols: Int,
    outputRows: Int,
    spec: LocalEeNeighborhoodSpec.Value
  ): Tile = {
    require(buffered != null && buffered.cellType == DoubleConstantNoDataCellType,
      "neighborhood input must be Float64 with NaN NoData")
    require(outputCols > 0 && outputRows > 0 && target != null &&
      target.colMin >= 0 && target.rowMin >= 0 && target.colMax < buffered.cols &&
      target.rowMax < buffered.rows && target.colMax - target.colMin + 1 == outputCols &&
      target.rowMax - target.rowMin + 1 == outputRows,
      "neighborhood buffered tile target area must match the original tile dimensions")
    val values = new Array[Double](spec.coefficients.length)
    val coefficientIndexes = new Array[Int](spec.coefficients.length)
    val output = new Array[Double](Math.multiplyExact(outputCols, outputRows))
    var row = 0
    while (row < outputRows) {
      var col = 0
      while (col < outputCols) {
        val centerX = target.colMin + col
        val centerY = target.rowMin + row
        val center = buffered.getDouble(centerX, centerY)
        require(center.isNaN || center.isFinite, "neighborhood pixels must be finite or NoData")
        output(row * outputCols + col) = if (spec.skipMasked && center.isNaN) Double.NaN
        else reduceAt(buffered, centerX, centerY, values, coefficientIndexes, spec)
        col += 1
      }
      row += 1
    }
    DoubleArrayTile(output, outputCols, outputRows, DoubleConstantNoDataCellType)
  }

  private def reduceAt(
    tile: Tile, centerX: Int, centerY: Int, values: Array[Double], indexes: Array[Int],
    spec: LocalEeNeighborhoodSpec.Value
  ): Double = {
    var count = 0
    var index = 0
    while (index < spec.coefficients.length) {
      val coefficient = spec.coefficients(index)
      val col = centerX + coefficient.dx
      val row = centerY + coefficient.dy
      if (col >= 0 && col < tile.cols && row >= 0 && row < tile.rows) {
        val value = tile.getDouble(col, row)
        require(value.isNaN || value.isFinite, "neighborhood pixels must be finite or NoData")
        if (!value.isNaN) {
          values(count) = if (value == 0.0d) 0.0d else value
          indexes(count) = index
          count += 1
        }
      }
      index += 1
    }
    LocalEeNeighborhoodStatistics.reduce(values, indexes, count, spec)
  }
}
