package local.ee.reduce

import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}

/** Pixel kernel for projecting NoData into independent finite mask weights. */
private[reduce] object LocalEeMaskWeightsNumeric {
  def applyTile(input: MultibandTile, spec: LocalEeMaskWeightsSpec.Value): Tile = {
    require(input != null, "mask weights input tile must not be null")
    require(input.cols > 0 && input.rows > 0, "mask weights tile dimensions must be positive")
    require(input.bandCount == spec.inputBands,
      s"mask weights ${spec.op} requires exactly ${spec.inputBands} input band(s)")

    val cols = input.cols
    val rows = input.rows
    val cells = Math.multiplyExact(cols.toLong, rows.toLong)
    require(cells <= Int.MaxValue, "mask weights tile has too many cells")
    val bands = Array.tabulate(spec.inputBands)(input.band)
    val output = new Array[Double](cells.toInt)
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        val index = row * cols + col
        output(index) = spec.op match {
          case "validity" => validityWeight(bands(0).getDouble(col, row))
          case "result_value" => finiteResultValue(bands(0).getDouble(col, row))
          case "update" =>
            val oldWeight = requiredWeight(bands(0).getDouble(col, row), "old mask weight")
            val maskValue = maskWeight(bands(1).getDouble(col, row))
            if (oldWeight == 0d) 0d else maskValue
          case "apply" =>
            val rawValue = bands(0).getDouble(col, row)
            require(rawValue.isNaN || rawValue.isFinite,
              "mask weights apply raw values must be finite or NoData")
            val weight = requiredWeight(bands(1).getDouble(col, row), "mask weight")
            if (weight > 0d) rawValue else Double.NaN
        }
        col += 1
      }
      row += 1
    }
    DoubleArrayTile(output, cols, rows, DoubleConstantNoDataCellType)
  }

  private def validityWeight(value: Double): Double = {
    require(value.isNaN || value.isFinite,
      "mask weights validity source values must be finite or NoData")
    if (value.isNaN) 0d else 1d
  }

  private def finiteResultValue(value: Double): Double =
    if (value.isFinite) value else Double.NaN

  private def maskWeight(value: Double): Double =
    if (value.isNaN) 0d else requiredWeight(value, "new mask value")

  private def requiredWeight(value: Double, label: String): Double = {
    require(value.isFinite && value >= 0d && value <= 1d,
      s"$label must be finite and in [0,1]")
    value
  }
}
