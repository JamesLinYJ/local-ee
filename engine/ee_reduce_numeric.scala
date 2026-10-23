package local.ee.reduce

import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}

/** Per-tile Float64 kernels; NoData is NaN and input band order is stable. */
private[reduce] object LocalEeReduceNumeric {
  private val Reducers = Set(
    "first", "last", "min", "max", "count", "median", "sum", "mean", "sd",
    "product", "stdDev", "variance", "sampleVariance")

  def reduceTile(tile: MultibandTile, bands: Int, cols: Int, rows: Int, reducer: String): Tile = {
    require(Reducers.contains(reducer), s"unsupported raster reducer: $reducer")
    require(tile.bandCount == bands && tile.cols == cols && tile.rows == rows,
      "tile band count or dimensions changed within the input cube")
    val source = Array.tabulate(bands)(band => tile.band(band).convert(DoubleConstantNoDataCellType))
    val values = new Array[Double](bands)
    val output = new Array[Double](cols * rows)
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        var count = 0
        var first = Double.NaN
        var last = Double.NaN
        var minimum = Double.PositiveInfinity
        var maximum = Double.NegativeInfinity
        var scale = 0d
        var band = 0
        while (band < bands) {
          val value = source(band).getDouble(col, row)
          require(value.isNaN || value.isFinite, "input pixels must be finite or NoData")
          if (!value.isNaN) {
            if (count == 0) first = value
            last = value
            minimum = math.min(minimum, value)
            maximum = math.max(maximum, value)
            scale = math.max(scale, math.abs(value))
            values(count) = value
            count += 1
          }
          band += 1
        }
        output(row * cols + col) = if (count == 0) Double.NaN else reducer match {
          case "first" => first
          case "last" => last
          case "min" => minimum
          case "max" => maximum
          case "count" => count.toDouble
          case "median" => median(values, count)
          case "sum" | "mean" => compensatedReduction(values, count, scale, reducer)
          case "sd" | "product" | "stdDev" | "variance" | "sampleVariance" =>
            LocalEeReduceStatistics.reduce(values, count, reducer)
        }
        col += 1
      }
      row += 1
    }
    DoubleArrayTile(output, cols, rows, DoubleConstantNoDataCellType)
  }

  private def median(values: Array[Double], count: Int): Double = {
    java.util.Arrays.sort(values, 0, count)
    if (count % 2 == 1) values(count / 2) else {
      val left = values(count / 2 - 1)
      val right = values(count / 2)
      val sum = left + right
      // Sum first to retain subnormal values; halve first only on overflow.
      if (sum.isFinite) sum / 2d else left / 2d + right / 2d
    }
  }

  private def compensatedReduction(values: Array[Double], count: Int, scale: Double, reducer: String): Double = {
    var sum = 0d
    var correction = 0d
    var index = 0
    while (index < count) {
      val value = values(index)
      val next = sum + value
      if (!next.isFinite) return scaledReduction(values, count, scale, reducer)
      if (math.abs(sum) >= math.abs(value)) correction += (sum - next) + value
      else correction += (value - next) + sum
      if (!correction.isFinite) return scaledReduction(values, count, scale, reducer)
      sum = next
      index += 1
    }
    val total = sum + correction
    if (!total.isFinite) return scaledReduction(values, count, scale, reducer)
    val result = if (reducer == "mean") total / count else total
    require(result.isFinite, s"$reducer reducer overflowed Float64")
    result
  }

  private def scaledReduction(values: Array[Double], count: Int, scale: Double, reducer: String): Double = {
    if (scale == 0d) return 0d
    var sum = 0d
    var correction = 0d
    var index = 0
    while (index < count) {
      val value = values(index) / scale
      val next = sum + value
      if (math.abs(sum) >= math.abs(value)) correction += (sum - next) + value
      else correction += (value - next) + sum
      sum = next
      index += 1
    }
    val scaledTotal = sum + correction
    val result = if (reducer == "mean") scale * (scaledTotal / count) else scale * scaledTotal
    require(result.isFinite, s"$reducer reducer overflowed Float64")
    result
  }

}
