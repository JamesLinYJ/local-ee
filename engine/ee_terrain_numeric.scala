package local.ee.reduce

import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, GridBounds, Tile}

/** Four-connected slope, aspect, and hillshade over real buffered Float64 cell values. */
private[reduce] object LocalEeTerrainNumeric {
  final case class Result(
    tile: Tile, transformCalls: Long, explicitArrayCount: Int, explicitArrayBytes: Long
  ) extends Serializable

  private val Ln2 = math.log(2.0d)
  private val LogDegreesPerRadian = math.log(180.0d / math.Pi)
  private val MaxExp = math.log(Double.MaxValue)
  private val BytesPerDouble = 8L

  def applyBufferedTile(
    buffered: Tile, target: GridBounds[Int], outputCols: Int, outputRows: Int,
    tileCol: Int, tileRow: Int, grid: LocalEeTerrainMetric.Grid,
    nativeToWgs84: (Double, Double) => (Double, Double), spec: LocalEeTerrainSpec.Value
  ): Result = {
    require(buffered != null && target != null && grid != null && nativeToWgs84 != null && spec != null,
      "local_ee_terrain buffered-tile arguments are required")
    require(outputCols > 0 && outputRows > 0 && target.colMin >= 0 && target.rowMin >= 0 &&
      target.colMax < buffered.cols && target.rowMax < buffered.rows &&
      target.colMax - target.colMin + 1 == outputCols &&
      target.rowMax - target.rowMin + 1 == outputRows,
      "local_ee_terrain buffered target must match the source tile dimensions")

    val cache = new LocalEeTerrainMetric.CoordinateCache(
      grid, tileCol, tileRow, outputCols, outputRows, nativeToWgs84)
    val metric = new Array[Double](12)
    val output = new Array[Double](Math.multiplyExact(outputCols, outputRows))
    val tileOriginCol = Math.multiplyExact(tileCol.toLong, outputCols.toLong)
    val tileOriginRow = Math.multiplyExact(tileRow.toLong, outputRows.toLong)
    var row = 0
    while (row < outputRows) {
      var col = 0
      while (col < outputCols) {
        val centerX = Math.addExact(target.colMin, col)
        val centerY = Math.addExact(target.rowMin, row)
        val center = sample(buffered, centerX, centerY)
        val globalCol = Math.addExact(tileOriginCol, col.toLong)
        val globalRow = Math.addExact(tileOriginRow, row.toLong)
        val index = Math.addExact(Math.multiplyExact(row, outputCols), col)
        output(index) = if (center.isNaN || globalCol <= 0L || globalRow <= 0L ||
          globalCol >= grid.columns - 1L || globalRow >= grid.rows - 1L) Double.NaN
        else {
          val east = sample(buffered, Math.addExact(centerX, 1), centerY)
          val west = sample(buffered, Math.subtractExact(centerX, 1), centerY)
          val north = sample(buffered, centerX, Math.subtractExact(centerY, 1))
          val south = sample(buffered, centerX, Math.addExact(centerY, 1))
          if (east.isNaN || west.isNaN || north.isNaN || south.isNaN) Double.NaN
          else {
            cache.matrixAt(globalCol, globalRow, metric)
            terrain(west, east, north, south, metric, spec)
          }
        }
        col += 1
      }
      row += 1
    }
    val tile = DoubleArrayTile(output, outputCols, outputRows, DoubleConstantNoDataCellType)
    val bytes = Math.addExact(Math.addExact(cache.allocatedBytes,
      Math.multiplyExact(output.length.toLong, BytesPerDouble)), 104L)
    Result(tile, cache.transformCalls, cache.allocatedArrays + 3, bytes)
  }

  private def sample(tile: Tile, col: Int, row: Int): Double = {
    require(col >= 0 && col < tile.cols && row >= 0 && row < tile.rows,
      "local_ee_terrain buffered tile lacks the complete one-pixel halo")
    val value = tile.getDouble(col, row)
    require(value.isNaN || value.isFinite, "local_ee_terrain input pixels must be finite or NoData")
    value
  }

  private def terrain(
    west: Double, east: Double, north: Double, south: Double,
    matrix: Array[Double], spec: LocalEeTerrainSpec.Value
  ): Double = {
    val distanceScale = LocalEeTerrainMetric.validateMatrix(matrix)
    val a = matrix(0) / distanceScale
    val b = matrix(1) / distanceScale
    val c = matrix(2) / distanceScale
    val d = matrix(3) / distanceScale
    val determinant = a * d - b * c

    // Keep the two central differences on independent power-of-two scales. This avoids
    // overflow for opposite extreme elevations and preserves a tiny orthogonal gradient.
    difference(east, west, matrix, 4)
    difference(south, north, matrix, 6)
    linearCombination(d / determinant / distanceScale, matrix(4), matrix(5).toInt,
      -b / determinant / distanceScale, matrix(6), matrix(7).toInt, matrix, 8)
    linearCombination(-c / determinant / distanceScale, matrix(4), matrix(5).toInt,
      a / determinant / distanceScale, matrix(6), matrix(7).toInt, matrix, 10)

    val eastMantissa = matrix(8)
    val eastExponent = matrix(9).toInt
    val northMantissa = matrix(10)
    val northExponent = matrix(11).toInt
    val commonExponent = if (eastMantissa == 0.0d && northMantissa == 0.0d) 0
    else if (eastMantissa == 0.0d) northExponent
    else if (northMantissa == 0.0d) eastExponent
    else math.max(eastExponent, northExponent)
    val eastGradient = if (eastMantissa == 0.0d) 0.0d
    else java.lang.Math.scalb(eastMantissa, eastExponent - commonExponent)
    val northGradient = if (northMantissa == 0.0d) 0.0d
    else java.lang.Math.scalb(northMantissa, northExponent - commonExponent)
    val scaledMagnitude = math.hypot(eastGradient, northGradient)

    spec.operation match {
      case "slope" => slopeDegrees(scaledMagnitude, commonExponent)
      case "aspect" => aspectDegrees(eastGradient, northGradient)
      case "hillshade" =>
        hillshade(eastGradient, northGradient, scaledMagnitude,
          commonExponent, spec.azimuth, spec.elevation)
      case operation => throw new IllegalArgumentException(s"unsupported terrain operation: $operation")
    }
  }

  private def difference(left: Double, right: Double, scratch: Array[Double], offset: Int): Unit = {
    val maximum = math.max(math.abs(left), math.abs(right))
    if (maximum == 0.0d) {
      scratch(offset) = 0.0d
      scratch(offset + 1) = 0.0d
    } else {
      val baseExponent = java.lang.Math.getExponent(maximum)
      val delta = java.lang.Math.scalb(left, -baseExponent) -
        java.lang.Math.scalb(right, -baseExponent)
      if (delta == 0.0d) {
        scratch(offset) = 0.0d
        scratch(offset + 1) = 0.0d
      } else {
        val deltaExponent = java.lang.Math.getExponent(math.abs(delta))
        scratch(offset) = java.lang.Math.scalb(delta, -deltaExponent)
        scratch(offset + 1) = baseExponent.toDouble + deltaExponent.toDouble
      }
    }
  }

  /** Store `c1 * x1 + c2 * x2` as a range-stable mantissa/exponent pair. */
  private def linearCombination(
    c1: Double, x1Mantissa: Double, x1Exponent: Int,
    c2: Double, x2Mantissa: Double, x2Exponent: Int,
    scratch: Array[Double], offset: Int
  ): Unit = {
    val c1Exponent = if (c1 == 0.0d) 0 else java.lang.Math.getExponent(math.abs(c1))
    val c2Exponent = if (c2 == 0.0d) 0 else java.lang.Math.getExponent(math.abs(c2))
    val c1Mantissa = if (c1 == 0.0d) 0.0d else java.lang.Math.scalb(c1, -c1Exponent)
    val c2Mantissa = if (c2 == 0.0d) 0.0d else java.lang.Math.scalb(c2, -c2Exponent)
    val first = c1Mantissa * x1Mantissa
    val second = c2Mantissa * x2Mantissa
    if (first == 0.0d && second == 0.0d) {
      scratch(offset) = 0.0d
      scratch(offset + 1) = 0.0d
    } else {
      val firstAdjust = if (first == 0.0d) 0 else java.lang.Math.getExponent(math.abs(first))
      val secondAdjust = if (second == 0.0d) 0 else java.lang.Math.getExponent(math.abs(second))
      val firstPower = if (first == 0.0d) Int.MinValue
      else Math.addExact(Math.addExact(x1Exponent, c1Exponent), firstAdjust)
      val secondPower = if (second == 0.0d) Int.MinValue
      else Math.addExact(Math.addExact(x2Exponent, c2Exponent), secondAdjust)
      val commonPower = math.max(firstPower, secondPower)
      val firstScaled = if (first == 0.0d) 0.0d
      else java.lang.Math.scalb(java.lang.Math.scalb(first, -firstAdjust), firstPower - commonPower)
      val secondScaled = if (second == 0.0d) 0.0d
      else java.lang.Math.scalb(java.lang.Math.scalb(second, -secondAdjust), secondPower - commonPower)
      val sum = firstScaled + secondScaled
      if (sum == 0.0d) {
        scratch(offset) = 0.0d
        scratch(offset + 1) = 0.0d
      } else {
        val sumAdjust = java.lang.Math.getExponent(math.abs(sum))
        scratch(offset) = java.lang.Math.scalb(sum, -sumAdjust)
        scratch(offset + 1) = Math.addExact(commonPower, sumAdjust).toDouble
      }
    }
  }

  private def logMagnitude(scaledMagnitude: Double, exponent: Int): Double =
    math.log(scaledMagnitude) + exponent.toDouble * Ln2

  private def slopeDegrees(scaledMagnitude: Double, exponent: Int): Double = {
    if (scaledMagnitude == 0.0d) 0.0d
    else {
      val log = logMagnitude(scaledMagnitude, exponent)
      if (log < -36.0d) {
        // atan(g) ~= g here; convert in log space so the degree result can remain
        // correctly rounded when the gradient is subnormal. Math.exp owns underflow
        // rounding, including the interval that rounds to Double.MIN_VALUE.
        math.exp(log + LogDegreesPerRadian)
      } else {
        val gradient = if (log > MaxExp) Double.PositiveInfinity else math.exp(log)
        math.toDegrees(math.atan(gradient))
      }
    }
  }

  private def aspectDegrees(eastGradient: Double, northGradient: Double): Double = {
    if (eastGradient == 0.0d && northGradient == 0.0d) 0.0d
    else {
      val angle = math.toDegrees(math.atan2(-eastGradient, -northGradient))
      val raw = angle % 360.0d
      val positive = if (raw < 0.0d) raw + 360.0d else raw
      if (positive >= 360.0d || positive == 0.0d) 0.0d else positive
    }
  }

  private def hillshade(
    eastGradient: Double, northGradient: Double, scaledMagnitude: Double,
    exponent: Int, azimuthDegrees: Double, elevationDegrees: Double
  ): Double = {
    val magnitudeLog = if (scaledMagnitude == 0.0d) Double.NegativeInfinity
    else logMagnitude(scaledMagnitude, exponent)
    var normalEast = 0.0d
    var normalNorth = 0.0d
    var normalUp = 1.0d
    if (scaledMagnitude != 0.0d) {
      // Divide the normal by max(1, |gradient|) before hypot to avoid overflow and underflow.
      val horizontal = if (magnitudeLog > 0.0d) 1.0d else math.exp(magnitudeLog)
      val vertical = if (magnitudeLog > 0.0d) math.exp(-magnitudeLog) else 1.0d
      val norm = math.hypot(horizontal, vertical)
      val directionEast = eastGradient / scaledMagnitude
      val directionNorth = northGradient / scaledMagnitude
      normalEast = -directionEast * horizontal / norm
      normalNorth = -directionNorth * horizontal / norm
      normalUp = vertical / norm
    }
    val azimuth = math.toRadians(azimuthDegrees)
    val elevation = math.toRadians(elevationDegrees)
    val sunEast = math.cos(elevation) * math.sin(azimuth)
    val sunNorth = math.cos(elevation) * math.cos(azimuth)
    val sunUp = math.sin(elevation)
    val illumination = normalEast * sunEast + normalNorth * sunNorth + normalUp * sunUp
    val clamped = math.max(0.0d, math.min(1.0d, illumination))
    math.floor(clamped * 255.0d + 0.5d)
  }
}
