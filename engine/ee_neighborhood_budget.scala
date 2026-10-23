package local.ee.reduce

/** Conservative work accounting for exact Float64 moments, sorting and buffered cells. */
private[reduce] object LocalEeNeighborhoodBudget {
  final case class Plan(
    keyCount: Long, radius: Int, bufferedCells: Long, exactLimbs: Int, perTileWork: Long
  ) extends Serializable

  val MaxSourceKeys = 100000L
  val MaxDecodedCells = 100000000L
  val MaxTileDecodedCells = 10000000L
  val MaxNeighborhoodWork = 1000000000L
  val MaxPerTileWork = 100000000L

  private val MaximumValueUnitBits = 2098L // full subnormal-to-largest-normal exponent span
  private val SignificandMultiplyWork = 4L

  def plan(keyCount: Long, cols: Int, rows: Int, spec: LocalEeNeighborhoodSpec.Value): Plan = {
    val result = estimate(keyCount, cols, rows, spec)
    require(result.perTileWork <= MaxPerTileWork,
      s"local_ee_neighborhood exceeds the $MaxPerTileWork per-tile work limit (${result.perTileWork})")
    require(Math.multiplyExact(result.perTileWork, keyCount) <= MaxNeighborhoodWork,
      s"local_ee_neighborhood exceeds the $MaxNeighborhoodWork total work limit")
    result
  }

  /** Compute the same bounded estimate without authorizing work beyond the work caps. */
  def estimate(keyCount: Long, cols: Int, rows: Int, spec: LocalEeNeighborhoodSpec.Value): Plan = {
    require(keyCount > 0L && keyCount <= MaxSourceKeys,
      s"local_ee_neighborhood supports 1 to $MaxSourceKeys source tile keys")
    require(cols > 0 && rows > 0, "local_ee_neighborhood tile dimensions must be positive")
    val tileCells = Math.multiplyExact(cols.toLong, rows.toLong)
    require(tileCells <= MaxTileDecodedCells,
      s"local_ee_neighborhood tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    require(keyCount <= MaxDecodedCells / tileCells,
      s"local_ee_neighborhood exceeds the $MaxDecodedCells aggregate decoded-cell limit")

    val radius = spec.radius
    require(radius == 0 || radius < math.min(cols, rows),
      "local_ee_neighborhood positive radius must be smaller than the smaller tile dimension")
    val bufferCols = Math.addExact(cols.toLong, Math.multiplyExact(2L, radius.toLong))
    val bufferRows = Math.addExact(rows.toLong, Math.multiplyExact(2L, radius.toLong))
    val bufferedCells = Math.multiplyExact(bufferCols, bufferRows)
    require(bufferedCells <= MaxTileDecodedCells,
      s"local_ee_neighborhood buffered tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    require(bufferedCells <= MaxDecodedCells / keyCount,
      s"local_ee_neighborhood exceeds the $MaxDecodedCells aggregate buffered-cell limit")

    val terms = spec.coefficients.length.toLong
    val termBits = if (terms <= 1L) 0L else 64 - java.lang.Long.numberOfLeadingZeros(terms - 1L)
    val weightBits = spec.weightUnitBits.toLong
    val weightSumBits = Math.addExact(weightBits, termBits)
    val weightSumLimbs = limbs(weightSumBits)
    val valueLimbs = limbs(MaximumValueUnitBits)
    val weightedValueLimbs = limbs(Math.addExact(Math.addExact(weightBits, MaximumValueUnitBits), termBits))
    val weightedSquareLimbs = limbs(Math.addExact(Math.addExact(weightBits,
      Math.multiplyExact(2L, MaximumValueUnitBits)), termBits))
    val momentResultLimbs = math.max(
      limbs(Math.addExact(weightedSquareLimbs.toLong * 64L, weightSumBits)),
      limbs(Math.multiplyExact(2L, weightedValueLimbs.toLong * 64L)))
    val weightedValueLimbCount = weightedValueLimbs.toLong
    val weightedSquareLimbCount = weightedSquareLimbs.toLong
    // scaledRatio may shift either side of a rational division. The shifted
    // operand is at most the larger original operand plus the 53-bit result
    // precision; charge the copy and each linear pass over that extent.
    val meanRoundingLimbs = Math.addExact(math.max(weightedValueLimbCount,
      weightSumLimbs.toLong), 1L)
    val meanRoundingWork = Math.multiplyExact(8L, meanRoundingLimbs)
    val weightedValueTermWork = Math.addExact(SignificandMultiplyWork,
      Math.addExact(1L, Math.multiplyExact(2L, weightedValueLimbCount)))
    // exactMoments also shifts and adds every weight into W. The second
    // significand multiply forms value² before multiplying by the weight.
    val exactMomentTermWork = Math.addExact(Math.multiplyExact(2L, weightSumLimbs.toLong),
      Math.addExact(weightedValueTermWork,
        Math.addExact(2L * SignificandMultiplyWork,
          Math.addExact(1L, Math.multiplyExact(2L, weightedSquareLimbCount)))))

    val perPixelWork = spec.operation match {
      case "sum" => Math.addExact(Math.multiplyExact(2L, terms), Math.addExact(
        Math.multiplyExact(terms, weightedValueTermWork),
        Math.addExact(weightedValueLimbCount, meanRoundingWork)))
      case "mean" =>
        val weightAdds = Math.multiplyExact(terms, Math.multiplyExact(2L, weightSumLimbs.toLong))
        val divideWork = meanRoundingWork
        Math.addExact(Math.multiplyExact(2L, terms), Math.addExact(
          Math.addExact(weightAdds, Math.multiplyExact(terms, weightedValueTermWork)),
          Math.addExact(weightedValueLimbCount, divideWork)))
      case "variance" | "sampleVariance" | "stdDev" | "sampleStdDev" =>
        val termWork = Math.multiplyExact(terms, exactMomentTermWork)
        val resultProducts = Math.addExact(
          Math.multiplyExact(weightedSquareLimbs.toLong, weightSumLimbs.toLong),
          Math.addExact(Math.multiplyExact(weightedValueLimbCount, weightedValueLimbCount),
            momentResultLimbs.toLong))
        val denominatorLimbs = if (spec.operation.startsWith("sample")) weightSumLimbs + 1L
          else Math.multiplyExact(weightSumLimbs.toLong, 2L)
        val denominatorWork = if (spec.operation.startsWith("sample"))
          Math.addExact(weightSumLimbs.toLong, 1L)
        else Math.multiplyExact(weightSumLimbs.toLong, weightSumLimbs.toLong)
        val rationalLimbs = Math.addExact(math.max(momentResultLimbs.toLong, denominatorLimbs), 1L)
        val sqrtLimbs = Math.addExact(math.max(momentResultLimbs.toLong, denominatorLimbs), 2L)
        // Rounded quotient is at most 53 bits, so division scans the aligned
        // operands linearly; the extra limb covers exact power-of-two shifts.
        val divideWork = Math.multiplyExact(8L, rationalLimbs)
        val sqrtWork = if (spec.operation == "stdDev" || spec.operation == "sampleStdDev")
          // roundedSqrt does one bounded-size quotient, a <=106-bit integer
          // square root, and one exact midpoint multiply/compare. No ULP walk.
          Math.addExact(Math.multiplyExact(12L, sqrtLimbs),
            Math.addExact(Math.multiplyExact(4L, denominatorLimbs), 32L))
        else 0L
        Math.addExact(Math.multiplyExact(2L, terms), Math.addExact(termWork,
          Math.addExact(resultProducts, Math.addExact(denominatorWork,
            Math.addExact(divideWork, sqrtWork)))))
      case "product" =>
        val productLimbs = limbs(Math.multiplyExact(53L, terms))
        Math.addExact(terms, Math.addExact(Math.multiplyExact(terms, productLimbs.toLong),
          Math.multiplyExact(8L, productLimbs.toLong + 1L)))
      case "median" | "mode" =>
        val sortBits = if (terms <= 1L) 0L else 64 - java.lang.Long.numberOfLeadingZeros(terms - 1L)
        val sortWork = Math.multiplyExact(terms, sortBits)
        if (spec.operation == "median") Math.addExact(terms,
          Math.addExact(sortWork, Math.multiplyExact(8L, valueLimbs.toLong)))
        else Math.addExact(terms, sortWork)
      case _ => terms // count/min/max only scan and compare the selected offsets
    }
    val perTileWork = Math.addExact(Math.multiplyExact(tileCells, perPixelWork), bufferedCells)
    Plan(keyCount, radius, bufferedCells, math.max(weightedValueLimbs, weightedSquareLimbs), perTileWork)
  }

  private def limbs(bits: Long): Int = Math.toIntExact(math.max(1L, (bits + 63L) / 64L))
}
