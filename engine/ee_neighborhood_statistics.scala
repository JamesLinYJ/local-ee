package local.ee.reduce

/** Exact per-pixel weighted sums, rational moments and unweighted order statistics. */
private[reduce] object LocalEeNeighborhoodStatistics {
  private val BigZero = java.math.BigInteger.ZERO
  private val BigOne = java.math.BigInteger.ONE
  private val BigTwo = java.math.BigInteger.valueOf(2L)
  private val FractionMask = (1L << 52) - 1L
  private val HiddenBit = 1L << 52

  def reduce(
    values: Array[Double], coefficientIndexes: Array[Int], count: Int,
    spec: LocalEeNeighborhoodSpec.Value
  ): Double = {
    if (count == 0) return Double.NaN
    spec.operation match {
      case "count" => count.toDouble
      case "min" => extremum(values, count, minimum = true)
      case "max" => extremum(values, count, minimum = false)
      case "sum" => weightedSum(values, coefficientIndexes, count, spec)
      case "mean" => weightedMean(values, coefficientIndexes, count, spec)
      case "variance" => variance(values, coefficientIndexes, count, spec, sample = false)
      case "stdDev" => standardDeviation(values, coefficientIndexes, count, spec, sample = false)
      case "sampleVariance" => if (count < 2) Double.NaN
        else variance(values, coefficientIndexes, count, spec, sample = true)
      case "sampleStdDev" => if (count < 2) Double.NaN
        else standardDeviation(values, coefficientIndexes, count, spec, sample = true)
      case "product" => product(values, count)
      case "median" => median(values, count)
      case "mode" => mode(values, count)
      case operation => throw new IllegalArgumentException(s"unsupported neighborhood operation: $operation")
    }
  }

  private def weightedSum(
    values: Array[Double], indexes: Array[Int], count: Int, spec: LocalEeNeighborhoodSpec.Value
  ): Double = {
    val valueExponent = minimumValueExponent(values, count)
    var total = BigZero
    var index = 0
    while (index < count) {
      val parts = LocalEeNeighborhoodExact.parts(values(index))
      if (parts.significand != 0L)
        total = total.add(weightedValueUnits(parts, spec.coefficients(indexes(index)),
          spec.weightUnitExponent, valueExponent))
      index += 1
    }
    LocalEeNeighborhoodExact.roundedRational(total.abs(), BigOne,
      Math.addExact(spec.weightUnitExponent, valueExponent), total.signum() < 0, "sum")
  }

  private def weightedMean(
    values: Array[Double], indexes: Array[Int], count: Int, spec: LocalEeNeighborhoodSpec.Value
  ): Double = {
    val valueExponent = minimumValueExponent(values, count)
    var totalWeight = BigZero
    var total = BigZero
    var index = 0
    while (index < count) {
      val coefficient = spec.coefficients(indexes(index))
      totalWeight = totalWeight.add(weightUnits(coefficient, spec.weightUnitExponent))
      val parts = LocalEeNeighborhoodExact.parts(values(index))
      if (parts.significand != 0L)
        total = total.add(weightedValueUnits(parts, coefficient, spec.weightUnitExponent, valueExponent))
      index += 1
    }
    LocalEeNeighborhoodExact.roundedRational(total.abs(), totalWeight, valueExponent,
      total.signum() < 0, "mean")
  }

  private def variance(
    values: Array[Double], indexes: Array[Int], count: Int,
    spec: LocalEeNeighborhoodSpec.Value, sample: Boolean
  ): Double = {
    val valueExponent = minimumValueExponent(values, count)
    val (totalWeight, total, squares) = exactMoments(values, indexes, count, spec, valueExponent)
    val numerator = squares.multiply(totalWeight).subtract(total.multiply(total))
    require(numerator.signum() >= 0, "local_ee_neighborhood exact variance became negative")
    val denominator = if (sample)
      totalWeight.multiply(java.math.BigInteger.valueOf((count - 1).toLong))
    else totalWeight.multiply(totalWeight)
    LocalEeNeighborhoodExact.roundedRational(numerator, denominator,
      Math.multiplyExact(2, valueExponent), negative = false,
      if (sample) "sampleVariance" else "variance")
  }

  private def standardDeviation(
    values: Array[Double], indexes: Array[Int], count: Int,
    spec: LocalEeNeighborhoodSpec.Value, sample: Boolean
  ): Double = {
    val valueExponent = minimumValueExponent(values, count)
    val (totalWeight, total, squares) = exactMoments(values, indexes, count, spec, valueExponent)
    val numerator = squares.multiply(totalWeight).subtract(total.multiply(total))
    require(numerator.signum() >= 0, "local_ee_neighborhood exact variance became negative")
    val denominator = if (sample)
      totalWeight.multiply(java.math.BigInteger.valueOf((count - 1).toLong))
    else totalWeight.multiply(totalWeight)
    LocalEeNeighborhoodExact.roundedSqrt(numerator, denominator, Math.multiplyExact(2, valueExponent))
  }

  private def exactMoments(
    values: Array[Double], indexes: Array[Int], count: Int,
    spec: LocalEeNeighborhoodSpec.Value, valueExponent: Int
  ): (java.math.BigInteger, java.math.BigInteger, java.math.BigInteger) = {
    var totalWeight = BigZero
    var total = BigZero
    var squares = BigZero
    var index = 0
    while (index < count) {
      val coefficient = spec.coefficients(indexes(index))
      val weightShift = coefficient.exponent - spec.weightUnitExponent
      val weight = java.math.BigInteger.valueOf(coefficient.significand).shiftLeft(weightShift)
      totalWeight = totalWeight.add(weight)
      val value = LocalEeNeighborhoodExact.parts(values(index))
      if (value.significand != 0L) {
        val valueShift = value.exponent - valueExponent
        val valueSignificand = java.math.BigInteger.valueOf(value.significand)
        val firstMoment = java.math.BigInteger.valueOf(coefficient.significand)
          .multiply(valueSignificand).shiftLeft(Math.addExact(weightShift, valueShift))
        total = total.add(if (value.negative) firstMoment.negate() else firstMoment)
        val squareMoment = java.math.BigInteger.valueOf(coefficient.significand)
          .multiply(valueSignificand.multiply(valueSignificand))
          .shiftLeft(Math.addExact(weightShift, Math.multiplyExact(2, valueShift)))
        squares = squares.add(squareMoment)
      }
      index += 1
    }
    (totalWeight, total, squares)
  }

  private def weightedValueUnits(
    value: LocalEeNeighborhoodExact.BinaryParts, coefficient: LocalEeNeighborhoodSpec.Coefficient,
    weightExponent: Int, valueExponent: Int
  ): java.math.BigInteger = {
    val shift = Math.addExact(coefficient.exponent - weightExponent, value.exponent - valueExponent)
    val product = java.math.BigInteger.valueOf(coefficient.significand)
      .multiply(java.math.BigInteger.valueOf(value.significand)).shiftLeft(shift)
    if (value.negative) product.negate() else product
  }

  private def weightUnits(
    coefficient: LocalEeNeighborhoodSpec.Coefficient, weightExponent: Int
  ): java.math.BigInteger = java.math.BigInteger.valueOf(coefficient.significand)
    .shiftLeft(coefficient.exponent - weightExponent)

  private def minimumValueExponent(values: Array[Double], count: Int): Int = {
    var selected = Int.MaxValue
    var index = 0
    while (index < count) {
      val parts = LocalEeNeighborhoodExact.parts(values(index))
      if (parts.significand != 0L) selected = math.min(selected, parts.exponent)
      index += 1
    }
    if (selected == Int.MaxValue) 0 else selected
  }

  private def product(values: Array[Double], count: Int): Double = {
    var exact = BigOne
    var exponent = 0
    var negative = false
    var hasZero = false
    var index = 0
    while (index < count) {
      val parts = LocalEeNeighborhoodExact.parts(values(index))
      negative ^= parts.negative
      if (parts.significand == 0L) hasZero = true
      else if (!hasZero) {
        exact = exact.multiply(java.math.BigInteger.valueOf(parts.significand))
        exponent = Math.addExact(exponent, parts.exponent)
      }
      index += 1
    }
    if (hasZero) return java.lang.Double.longBitsToDouble(if (negative) Long.MinValue else 0L)
    LocalEeNeighborhoodExact.roundedRational(exact, BigOne, exponent, negative, "product")
  }

  private def median(values: Array[Double], count: Int): Double = {
    java.util.Arrays.sort(values, 0, count)
    if ((count & 1) == 1) values(count / 2)
    else {
      val total = subnormalUnits(values(count / 2 - 1)).add(subnormalUnits(values(count / 2)))
      LocalEeNeighborhoodExact.roundedRational(total.abs(), BigTwo, -1074, total.signum() < 0, "median")
    }
  }

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

  private def extremum(values: Array[Double], count: Int, minimum: Boolean): Double = {
    var result = values(0)
    var index = 1
    while (index < count) {
      result = if (minimum) math.min(result, values(index)) else math.max(result, values(index))
      index += 1
    }
    result
  }

  private def subnormalUnits(value: Double): java.math.BigInteger = {
    val bits = java.lang.Double.doubleToRawLongBits(value)
    val exponentBits = ((bits >>> 52) & 0x7ffL).toInt
    val fraction = bits & FractionMask
    val significand = if (exponentBits == 0) fraction else fraction | HiddenBit
    val units = java.math.BigInteger.valueOf(significand)
      .shiftLeft(if (exponentBits == 0) 0 else exponentBits - 1)
    if (bits < 0L) units.negate() else units
  }
}
