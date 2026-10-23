package local.ee.reduce

/** Correctly rounded binary64 helpers for exact rational sums, products and square roots. */
private[reduce] object LocalEeNeighborhoodExact {
  final case class BinaryParts(significand: Long, exponent: Int, negative: Boolean)

  private val FractionMask = (1L << 52) - 1L
  private val HiddenBit = 1L << 52
  private val NegativeSign = Long.MinValue
  private val BigOne = java.math.BigInteger.ONE

  def parts(value: Double): BinaryParts = {
    val bits = java.lang.Double.doubleToRawLongBits(value)
    val exponentBits = ((bits >>> 52) & 0x7ffL).toInt
    val fraction = bits & FractionMask
    val rawSignificand = if (exponentBits == 0) fraction else fraction | HiddenBit
    if (rawSignificand == 0L) BinaryParts(0L, 0, bits < 0L)
    else {
      val trailingZeros = java.lang.Long.numberOfTrailingZeros(rawSignificand)
      val baseExponent = if (exponentBits == 0) -1074 else exponentBits - 1075
      BinaryParts(rawSignificand >>> trailingZeros, baseExponent + trailingZeros, bits < 0L)
    }
  }

  /** Round numerator / denominator * 2^scale once using round-to-nearest, ties-to-even. */
  def roundedRational(
    numerator: java.math.BigInteger, denominator: java.math.BigInteger, scale: Int,
    negative: Boolean, operation: String
  ): Double = {
    require(numerator.signum() >= 0 && denominator.signum() > 0,
      "neighborhood exact rational must have a nonnegative numerator and positive denominator")
    val sign = if (negative) NegativeSign else 0L
    if (numerator.signum() == 0) return java.lang.Double.longBitsToDouble(sign)
    var exponent = Math.addExact(floorLog2Ratio(numerator, denominator), scale)
    require(exponent <= 1023, s"local_ee_neighborhood $operation final Float64 result overflowed")
    if (exponent < -1075) return java.lang.Double.longBitsToDouble(sign)

    if (exponent < -1022) {
      val shift = Math.addExact(scale, 1074)
      val (scaledNumerator, scaledDenominator) = scaledRatio(numerator, denominator, shift)
      val units = roundQuotientToEven(scaledNumerator, scaledDenominator)
      return java.lang.Double.longBitsToDouble(units.longValue() | sign)
    }

    val shift = Math.subtractExact(scale, exponent - 52)
    val (scaledNumerator, scaledDenominator) = scaledRatio(numerator, denominator, shift)
    var significand = roundQuotientToEven(scaledNumerator, scaledDenominator)
    if (significand.compareTo(BigOne.shiftLeft(53)) >= 0) {
      significand = significand.shiftRight(1)
      exponent = Math.addExact(exponent, 1)
    }
    require(exponent <= 1023, s"local_ee_neighborhood $operation final Float64 result overflowed")
    val exponentBits = exponent + 1023
    val fractionBits = significand.longValue() & FractionMask
    java.lang.Double.longBitsToDouble((exponentBits.toLong << 52) | fractionBits | sign)
  }

  /** Exact integer-square-root rounding; no floating seed or unbounded correction loop. */
  def roundedSqrt(
    numerator: java.math.BigInteger, denominator: java.math.BigInteger, scale: Int
  ): Double = {
    require(numerator.signum() >= 0 && denominator.signum() > 0,
      "neighborhood variance rational must have a nonnegative numerator and positive denominator")
    if (numerator.signum() == 0) return 0.0d
    val squaredExponent = Math.addExact(floorLog2Ratio(numerator, denominator), scale)
    val resultExponent = Math.floorDiv(squaredExponent, 2)
    require(resultExponent <= 1023,
      "local_ee_neighborhood standard deviation final Float64 result overflowed")
    if (resultExponent < -1075) return 0.0d
    val subnormal = resultExponent < -1022
    val targetExponent = if (subnormal) -1074 else resultExponent - 52
    val shift = Math.subtractExact(scale, Math.multiplyExact(2, targetExponent))
    val (scaledNumerator, scaledDenominator) = scaledRatio(numerator, denominator, shift)
    val integerRatio = scaledNumerator.divide(scaledDenominator)
    var significand = integerRatio.sqrt()

    // Compare sqrt(A/B) with floor + 1/2 without approximating either side.
    val twiceMidpoint = significand.shiftLeft(1).add(BigOne)
    val midpointSquared = scaledDenominator.multiply(twiceMidpoint.multiply(twiceMidpoint))
    val midpointComparison = scaledNumerator.shiftLeft(2).compareTo(midpointSquared)
    if (midpointComparison > 0 || (midpointComparison == 0 && significand.testBit(0)))
      significand = significand.add(BigOne)

    if (subnormal) {
      require(significand.bitLength() <= 53,
        "local_ee_neighborhood subnormal standard deviation rounding exceeded its range")
      return java.lang.Double.longBitsToDouble(significand.longValue())
    }
    var roundedExponent = resultExponent
    if (significand.compareTo(BigOne.shiftLeft(53)) >= 0) {
      significand = significand.shiftRight(1)
      roundedExponent = Math.addExact(roundedExponent, 1)
    }
    require(roundedExponent <= 1023,
      "local_ee_neighborhood standard deviation final Float64 result overflowed")
    val exponentBits = roundedExponent + 1023
    val fractionBits = significand.longValue() & FractionMask
    java.lang.Double.longBitsToDouble((exponentBits.toLong << 52) | fractionBits)
  }

  def floorLog2Ratio(
    numerator: java.math.BigInteger, denominator: java.math.BigInteger
  ): Int = {
    var exponent = numerator.bitLength() - denominator.bitLength()
    val comparison = if (exponent >= 0) numerator.compareTo(denominator.shiftLeft(exponent))
    else numerator.shiftLeft(-exponent).compareTo(denominator)
    if (comparison < 0) exponent -= 1
    exponent
  }

  private def scaledRatio(
    numerator: java.math.BigInteger, denominator: java.math.BigInteger, shift: Int
  ): (java.math.BigInteger, java.math.BigInteger) =
    if (shift >= 0) (numerator.shiftLeft(shift), denominator)
    else (numerator, denominator.shiftLeft(-shift))

  private def roundQuotientToEven(
    numerator: java.math.BigInteger, denominator: java.math.BigInteger
  ): java.math.BigInteger = {
    val parts = numerator.divideAndRemainder(denominator)
    val comparison = parts(1).shiftLeft(1).compareTo(denominator)
    if (comparison > 0 || (comparison == 0 && parts(0).testBit(0))) parts(0).add(BigOne)
    else parts(0)
  }
}
