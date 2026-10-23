package local.ee.reduce

/** Stable Float64 product and dispersion kernels for actual raster cells. */
private[reduce] object LocalEeReduceStatistics {
  private final case class Moments(scale: Double, m2: Double, scaled: Boolean)

  def reduce(values: Array[Double], count: Int, reducer: String): Double = reducer match {
    case "product" => product(values, count)
    case "sd" =>
      if (count < 2) Double.NaN else dispersion(values, count, count - 1, squareRoot = true)
    case "stdDev" => dispersion(values, count, count, squareRoot = true)
    case "variance" => dispersion(values, count, count, squareRoot = false)
    case "sampleVariance" =>
      if (count < 2) Double.NaN else dispersion(values, count, count - 1, squareRoot = false)
    case _ => throw new IllegalArgumentException(s"unsupported raster statistic: $reducer")
  }

  private def product(values: Array[Double], count: Int): Double = {
    var negative = false
    var hasZero = false
    var index = 0
    while (index < count) {
      val value = values(index)
      if (java.lang.Double.doubleToRawLongBits(value) < 0L) negative = !negative
      if (value == 0d) hasZero = true
      index += 1
    }
    if (hasZero) return if (negative) -0d else 0d

    var mantissa = 1d
    var exponent = 0L
    index = 0
    while (index < count) {
      val value = math.abs(values(index))
      val valueExponent = java.lang.Math.getExponent(value)
      mantissa *= java.lang.Math.scalb(value, -valueExponent)
      exponent = Math.addExact(exponent, valueExponent.toLong)

      val mantissaExponent = java.lang.Math.getExponent(mantissa)
      mantissa = java.lang.Math.scalb(mantissa, -mantissaExponent)
      exponent = Math.addExact(exponent, mantissaExponent.toLong)
      index += 1
    }

    if (exponent < -1075L) return if (negative) -0d else 0d
    require(exponent <= 1024L, "product reducer overflowed Float64")
    val signedMantissa = if (negative) -mantissa else mantissa
    val result = java.lang.Math.scalb(signedMantissa, exponent.toInt)
    require(result.isFinite, "product reducer overflowed Float64")
    result
  }

  private def dispersion(values: Array[Double], count: Int, denominator: Int,
                         squareRoot: Boolean): Double = {
    if (count < 2) return 0d
    val moments = centeredMoments(values, count)
    val variance = math.max(0d, moments.m2) / denominator
    val result = if (squareRoot) {
      val root = math.sqrt(variance)
      if (moments.scaled) moments.scale * root else root
    } else if (moments.scaled) {
      rescaleVariance(moments.scale, variance)
    } else {
      variance
    }
    require(result.isFinite, s"${if (squareRoot) "stdDev" else "variance"} reducer overflowed Float64")
    result
  }

  /** Center first to retain small differences beside a large common offset. */
  private def centeredMoments(values: Array[Double], count: Int): Moments = {
    val origin = values(0)
    var mean = 0d
    var m2 = 0d
    var valid = true
    var subtractionOverflowed = false
    var hasVariation = false
    var index = 0
    while (index < count && valid) {
      val centered = values(index) - origin
      if (!centered.isFinite) {
        valid = false
        subtractionOverflowed = true
      }
      else {
        if (centered != 0d) hasVariation = true
        val delta = centered - mean
        val nextMean = mean + delta / (index + 1)
        val contribution = delta * (centered - nextMean)
        val nextM2 = m2 + contribution
        if (!nextMean.isFinite || !contribution.isFinite || !nextM2.isFinite) valid = false
        else {
          mean = nextMean
          m2 = nextM2
        }
      }
      index += 1
    }
    val underflowedMoment = hasVariation &&
      (m2 == 0d || m2 < java.lang.Double.MIN_NORMAL)
    if (valid && !underflowedMoment) Moments(1d, m2, scaled = false)
    else if (subtractionOverflowed) scaledOriginalMoments(values, count)
    else scaledCenteredMoments(values, count, origin)
  }

  /** Scale finite centered deltas so large offsets cannot erase their differences. */
  private def scaledCenteredMoments(values: Array[Double], count: Int, origin: Double): Moments = {
    var scale = 0d
    var index = 0
    while (index < count) {
      val centered = values(index) - origin
      if (!centered.isFinite) return scaledOriginalMoments(values, count)
      scale = math.max(scale, math.abs(centered))
      index += 1
    }
    if (scale == 0d) return Moments(0d, 0d, scaled = true)

    var mean = 0d
    var m2 = 0d
    index = 0
    while (index < count) {
      val centered = (values(index) - origin) / scale
      val delta = centered - mean
      mean += delta / (index + 1)
      m2 += delta * (centered - mean)
      index += 1
    }
    require(m2.isFinite, "centered variance reducer exceeded its bounded Float64 domain")
    Moments(scale, m2, scaled = true)
  }

  /** Scale original inputs only when subtracting the common offset overflows. */
  private def scaledOriginalMoments(values: Array[Double], count: Int): Moments = {
    var scale = 0d
    var index = 0
    while (index < count) {
      scale = math.max(scale, math.abs(values(index)))
      index += 1
    }
    if (scale == 0d) return Moments(0d, 0d, scaled = true)

    var mean = 0d
    var m2 = 0d
    index = 0
    while (index < count) {
      val centered = values(index) / scale
      val delta = centered - mean
      mean += delta / (index + 1)
      m2 += delta * (centered - mean)
      index += 1
    }
    require(m2.isFinite, "scaled variance reducer exceeded its bounded Float64 domain")
    Moments(scale, m2, scaled = true)
  }

  /** Multiply scale² by a normalized variance without transient overflow/underflow. */
  private def rescaleVariance(scale: Double, normalizedVariance: Double): Double = {
    if (normalizedVariance == 0d || scale == 0d) return 0d
    val scaleExponent = java.lang.Math.getExponent(scale)
    val normalizedScale = java.lang.Math.scalb(scale, -scaleExponent)
    var mantissa = normalizedScale * normalizedScale * normalizedVariance
    if (mantissa == 0d) return 0d
    val mantissaExponent = java.lang.Math.getExponent(mantissa)
    mantissa = java.lang.Math.scalb(mantissa, -mantissaExponent)
    val exponent = 2L * scaleExponent.toLong + mantissaExponent.toLong
    if (exponent < -1075L) return 0d
    require(exponent <= 1024L, "variance reducer overflowed Float64")
    java.lang.Math.scalb(mantissa, exponent.toInt)
  }
}
