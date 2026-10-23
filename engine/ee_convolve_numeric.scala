package local.ee.reduce

import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, GridBounds, Tile}

/** Exact finite-binary64 convolution over one GeoTrellis tile with its spatial halo. */
private[reduce] object LocalEeConvolveNumeric {
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
    spec: LocalEeConvolveSpec.Value
  ): Tile = {
    require(buffered != null && buffered.cellType == DoubleConstantNoDataCellType,
      "convolve input must be Float64 with NaN NoData")
    require(outputCols > 0 && outputRows > 0 && target != null &&
      target.colMin >= 0 && target.rowMin >= 0 &&
      target.colMax < buffered.cols && target.rowMax < buffered.rows &&
      target.colMax - target.colMin + 1 == outputCols &&
      target.rowMax - target.rowMin + 1 == outputRows,
      "convolve buffered tile target area must match the original tile dimensions")

    val output = new Array[Double](Math.multiplyExact(outputCols, outputRows))
    var row = 0
    while (row < outputRows) {
      var col = 0
      while (col < outputCols) {
        val centerX = target.colMin + col
        val centerY = target.rowMin + row
        val center = buffered.getDouble(centerX, centerY)
        require(center.isNaN || center.isFinite, "convolve input pixels must be finite or NoData")
        output(row * outputCols + col) = if (center.isNaN) Double.NaN
        else if (spec.active.isEmpty) 0.0
        else convolveAt(buffered, centerX, centerY, spec.active, spec.unitExponent)
        col += 1
      }
      row += 1
    }
    DoubleArrayTile(output, outputCols, outputRows, DoubleConstantNoDataCellType)
  }

  private def convolveAt(
    tile: Tile, centerX: Int, centerY: Int, coefficients: Vector[LocalEeConvolveSpec.Coefficient],
    unitExponent: Int
  ): Double = {
    var total = BigZero
    var completeSupport = true
    var index = 0
    while (index < coefficients.length) {
      val coefficient = coefficients(index)
      val col = centerX + coefficient.dx
      val row = centerY + coefficient.dy
      if (col < 0 || col >= tile.cols || row < 0 || row >= tile.rows) {
        completeSupport = false
      } else {
        val value = tile.getDouble(col, row)
        require(value.isNaN || value.isFinite, "convolve input pixels must be finite or NoData")
        if (value.isNaN) completeSupport = false
        else total = total.add(exactProductUnits(value, coefficient, unitExponent))
      }
      index += 1
    }
    if (!completeSupport) Double.NaN else roundedFloat64(total, unitExponent)
  }

  /** Product is represented exactly in the kernel's precomputed common binary unit. */
  private def exactProductUnits(
    left: Double, coefficient: LocalEeConvolveSpec.Coefficient, unitExponent: Int
  ): java.math.BigInteger = {
    val leftParts = binaryParts(left)
    if (leftParts.significand == 0L || coefficient.significand == 0L) return BigZero
    val shift = leftParts.exponent + coefficient.exponent + unitExponent
    require(shift >= 0, "convolve exact-product scale is invalid")
    val product = java.math.BigInteger.valueOf(leftParts.significand)
      .multiply(java.math.BigInteger.valueOf(coefficient.significand)).shiftLeft(shift)
    if (leftParts.negative ^ coefficient.negative) product.negate() else product
  }

  private final case class BinaryParts(significand: Long, exponent: Int, negative: Boolean)

  private def binaryParts(value: Double): BinaryParts = {
    val bits = java.lang.Double.doubleToRawLongBits(value)
    val exponentBits = ((bits >>> 52) & 0x7ffL).toInt
    val fraction = bits & FractionMask
    val significand = if (exponentBits == 0) fraction else fraction | HiddenBit
    val exponent = if (exponentBits == 0) -1074 else exponentBits - 1075
    BinaryParts(significand, exponent, bits < 0L)
  }

  /** Round the exact integer sum to binary64 once, using round-to-nearest, ties-to-even. */
  private def roundedFloat64(units: java.math.BigInteger, unitExponent: Int): Double = {
    if (units.signum() == 0) return 0.0
    val negative = units.signum() < 0
    val magnitude = units.abs()
    val sign = if (negative) NegativeSign else 0L
    var exponent = magnitude.bitLength() - 1 - unitExponent

    if (exponent < -1022) {
      val subnormalShift = unitExponent - 1074
      val subnormalMagnitude = if (subnormalShift >= 0)
        roundRightToEven(magnitude, subnormalShift)
      else magnitude.shiftLeft(-subnormalShift)
      val subnormalUnits = subnormalMagnitude.longValue()
      return java.lang.Double.longBitsToDouble(subnormalUnits | sign)
    }

    val shift = magnitude.bitLength() - 53
    var significand = if (shift >= 0) roundRightToEven(magnitude, shift)
      else magnitude.shiftLeft(-shift)
    if (significand.compareTo(BigOne.shiftLeft(53)) >= 0) {
      significand = significand.shiftRight(1)
      exponent += 1
    }
    require(exponent <= 1023, "local_ee_convolve final Float64 result overflowed")
    val exponentBits = exponent + 1023
    val fractionBits = significand.longValue() & FractionMask
    val bits = (exponentBits.toLong << 52) | fractionBits | sign
    java.lang.Double.longBitsToDouble(bits)
  }

  private def roundRightToEven(value: java.math.BigInteger, shift: Int): java.math.BigInteger = {
    require(shift >= 0, "convolve rounding shift must be nonnegative")
    if (shift == 0) return value
    val quotient = value.shiftRight(shift)
    val remainder = value.subtract(quotient.shiftLeft(shift))
    val midpoint = BigOne.shiftLeft(shift - 1)
    val comparison = remainder.compareTo(midpoint)
    if (comparison > 0 || (comparison == 0 && quotient.testBit(0))) quotient.add(BigOne)
    else quotient
  }
}
