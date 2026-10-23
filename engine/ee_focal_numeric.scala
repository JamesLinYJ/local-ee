package local.ee.reduce

import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, Tile}
import geotrellis.raster.GridBounds

/** Actual Float64 neighborhood kernel over one GeoTrellis buffered tile. */
private[reduce] object LocalEeFocalNumeric {
  private val FractionMask = (1L << 52) - 1L
  private val HiddenBit = 1L << 52
  private val NegativeSign = Long.MinValue
  private val BigOne = java.math.BigInteger.ONE
  private val BigZero = java.math.BigInteger.ZERO

  def applyBufferedTile(
    buffered: Tile,
    target: GridBounds[Int],
    outputCols: Int,
    outputRows: Int,
    spec: LocalEeFocalSpec.Value
  ): Tile = {
    require(buffered != null && buffered.cellType == DoubleConstantNoDataCellType,
      "focal input must be Float64 with NaN NoData")
    require(outputCols > 0 && outputRows > 0 && target != null &&
      target.colMin >= 0 && target.rowMin >= 0 &&
      target.colMax < buffered.cols && target.rowMax < buffered.rows &&
      target.colMax - target.colMin + 1 == outputCols &&
      target.rowMax - target.rowMin + 1 == outputRows,
      "focal buffered tile target area must match the original tile dimensions")
    val values = new Array[Double](spec.offsets.length)
    val output = new Array[Double](Math.multiplyExact(outputCols, outputRows))
    var row = 0
    while (row < outputRows) {
      var col = 0
      while (col < outputCols) {
        val centerX = target.colMin + col
        val centerY = target.rowMin + row
        val center = buffered.getDouble(centerX, centerY)
        require(center.isNaN || center.isFinite, "focal input pixels must be finite or NoData")
        output(row * outputCols + col) = if (spec.skipMasked && center.isNaN) Double.NaN
        else reduceAt(buffered, centerX, centerY, values, spec)
        col += 1
      }
      row += 1
    }
    DoubleArrayTile(output, outputCols, outputRows, DoubleConstantNoDataCellType)
  }

  private def reduceAt(
    tile: Tile, centerX: Int, centerY: Int, values: Array[Double], spec: LocalEeFocalSpec.Value
  ): Double = {
    var count = 0
    var minimum = Double.PositiveInfinity
    var maximum = Double.NegativeInfinity
    var index = 0
    while (index < spec.offsets.length) {
      val offset = spec.offsets(index)
      val col = centerX + offset.dx
      val row = centerY + offset.dy
      if (col >= 0 && col < tile.cols && row >= 0 && row < tile.rows) {
        val value = tile.getDouble(col, row)
        require(value.isNaN || value.isFinite, "focal input pixels must be finite or NoData")
        if (!value.isNaN) {
          values(count) = if (value == 0d) 0d else value
          minimum = math.min(minimum, value)
          maximum = math.max(maximum, value)
          count += 1
        }
      }
      index += 1
    }
    if (count == 0) Double.NaN
    else spec.operation match {
      case "min" => minimum
      case "max" => maximum
      case "mean" => mean(values, count)
      case "median" => median(values, count)
      case "mode" => mode(values, count)
      case operation => throw new IllegalArgumentException(s"unsupported focal operation: $operation")
    }
  }

  /** Sum exact binary64 units before one correctly rounded division by count. */
  private def mean(values: Array[Double], count: Int): Double = {
    var total = BigZero
    var index = 0
    while (index < count) {
      total = total.add(subnormalUnits(values(index)))
      index += 1
    }
    roundedAverage(total, count)
  }

  private def roundedAverage(total: java.math.BigInteger, count: Int): Double = {
    if (total.signum() == 0) return 0d
    val negative = total.signum() < 0
    val numerator = total.abs()
    val denominator = java.math.BigInteger.valueOf(count.toLong)
    var exponent = floorLog2Ratio(numerator, denominator) - 1074
    if (exponent < -1022) {
      val units = roundQuotientToEven(numerator, denominator).longValue()
      return java.lang.Double.longBitsToDouble(units | (if (negative) NegativeSign else 0L))
    }

    val shift = exponent + 1022
    var significand = roundQuotientToEven(numerator, denominator.shiftLeft(shift))
    if (significand.compareTo(BigOne.shiftLeft(53)) >= 0) {
      significand = significand.shiftRight(1)
      exponent += 1
    }
    require(exponent <= 1023, "focal mean exceeded the finite input range")
    val exponentBits = exponent + 1023
    val fractionBits = significand.longValue() & FractionMask
    val bits = (exponentBits.toLong << 52) | fractionBits | (if (negative) NegativeSign else 0L)
    java.lang.Double.longBitsToDouble(bits)
  }

  /** Every finite binary64 value is an integer multiple of 2^-1074. */
  private def subnormalUnits(value: Double): java.math.BigInteger = {
    val bits = java.lang.Double.doubleToRawLongBits(value)
    val exponent = ((bits >>> 52) & 0x7ffL).toInt
    val fraction = bits & FractionMask
    val significand = if (exponent == 0) fraction else fraction | HiddenBit
    val magnitude = java.math.BigInteger.valueOf(significand)
    val units = if (exponent == 0) magnitude else magnitude.shiftLeft(exponent - 1)
    if (bits < 0L) units.negate() else units
  }

  private def floorLog2Ratio(numerator: java.math.BigInteger, denominator: java.math.BigInteger): Int = {
    var exponent = numerator.bitLength() - denominator.bitLength()
    val comparison = if (exponent >= 0) numerator.compareTo(denominator.shiftLeft(exponent))
    else numerator.shiftLeft(-exponent).compareTo(denominator)
    if (comparison < 0) exponent -= 1
    exponent
  }

  private def roundQuotientToEven(
    numerator: java.math.BigInteger, denominator: java.math.BigInteger
  ): java.math.BigInteger = {
    val parts = numerator.divideAndRemainder(denominator)
    val halfComparison = parts(1).shiftLeft(1).compareTo(denominator)
    if (halfComparison > 0 || (halfComparison == 0 && parts(0).testBit(0))) parts(0).add(BigOne)
    else parts(0)
  }

  private def median(values: Array[Double], count: Int): Double = {
    java.util.Arrays.sort(values, 0, count)
    if (count % 2 == 1) values(count / 2)
    else {
      val left = values(count / 2 - 1)
      val right = values(count / 2)
      roundedAverage(subnormalUnits(left).add(subnormalUnits(right)), 2)
    }
  }

  /** Equal numeric values share a mode; signed zeros are normalized before sorting. */
  private def mode(values: Array[Double], count: Int): Double = {
    java.util.Arrays.sort(values, 0, count)
    var best = values(0)
    var bestCount = 0
    var index = 0
    while (index < count) {
      val candidate = values(index)
      var end = index + 1
      while (end < count && values(end) == candidate) end += 1
      val frequency = end - index
      if (frequency > bestCount) {
        best = candidate
        bestCount = frequency
      }
      index = end
    }
    best
  }
}
