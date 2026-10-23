package local.ee.reduce

import geotrellis.raster.MultibandTile
import org.apache.spark.rdd.RDD

/** Input-sensitive work admission for exact-rational LU factorization. */
private[reduce] object LocalEeMatrixFactorizationBudget {
  final case class Envelope(
    hasFiniteInput: Boolean, hasNonzeroInput: Boolean,
    minExponent: Int, maxExponent: Int, maxSignificandBits: Int
  ) extends Serializable

  private val EmptyEnvelope = Envelope(false, false, 0, 0, 1)
  private val RationalBitBound = LocalEeMatrixFactorization.RationalBitBound
  private val LimbBits = 64L
  private val FactorArithmeticMultiplier = 8L
  private val ExactOutputShiftLimit = 1074L

  /** Scan source tiles to scalar bounds before the output RDD can allocate factor bands. */
  def admitSource(
    source: RDD[(Any, MultibandTile)], keyCount: Long,
    spec: LocalEeMatrixValuesSpec.Value, cols: Int, rows: Int
  ): Envelope = {
    require(keyCount > 0L && keyCount <= LocalEeMatrixValuesBudget.MaxTileKeys,
      s"local_ee_matrix_values supports 1 to ${LocalEeMatrixValuesBudget.MaxTileKeys} tile keys")
    val tilePixels = Math.multiplyExact(cols.toLong, rows.toLong)
    val minimumTileWork = Math.multiplyExact(tilePixels, structuralWorkPerPixel(spec))
    require(minimumTileWork > 0L && minimumTileWork <= LocalEeMatrixValuesBudget.MaxTileWork,
      s"local_ee_matrix_values exceeds the ${LocalEeMatrixValuesBudget.MaxTileWork} per-tile work budget")
    aggregateWork(minimumTileWork, keyCount)
    val (envelope, actualKeyCount) = source.map { case (_, tile) =>
      LocalEeMatrixValuesNumeric.validateTileShape(tile, spec, cols, rows)
      (envelopeForTile(tile, spec, cols, rows), 1L)
    }.fold((EmptyEnvelope, 0L)) { case ((left, leftCount), (right, rightCount)) =>
      (merge(left, right), Math.addExact(leftCount, rightCount))
    }
    require(actualKeyCount == keyCount,
      "local_ee_matrix_values tile key count changed during budget admission")

    val tileWork = Math.multiplyExact(tilePixels, workPerPixel(spec, envelope))
    require(tileWork > 0L && tileWork <= LocalEeMatrixValuesBudget.MaxTileWork,
      s"local_ee_matrix_values exceeds the ${LocalEeMatrixValuesBudget.MaxTileWork} per-tile work budget")
    aggregateWork(tileWork, keyCount)
    envelope
  }

  private[reduce] def aggregateWork(tileWork: Long, keyCount: Long): Long = {
    require(tileWork >= 0L && keyCount >= 0L,
      "local_ee_matrix_values work estimates must be nonnegative")
    val totalWork = Math.multiplyExact(tileWork, keyCount)
    require(totalWork <= LocalEeMatrixValuesBudget.MaxTotalWork,
      s"local_ee_matrix_values exceeds the ${LocalEeMatrixValuesBudget.MaxTotalWork} aggregate work budget")
    totalWork
  }

  /** Re-scan recomputed output input and reject values outside the admitted envelope. */
  def requireWithinEnvelope(
    tile: MultibandTile, spec: LocalEeMatrixValuesSpec.Value,
    cols: Int, rows: Int, envelope: Envelope
  ): Unit = {
    LocalEeMatrixValuesNumeric.validateTileShape(tile, spec, cols, rows)
    val actual = envelopeForTile(tile, spec, cols, rows)
    require(!actual.hasFiniteInput || envelope.hasFiniteInput,
      "local_ee_matrix_values source values changed after LU budget admission")
    if (actual.hasNonzeroInput) {
      require(envelope.hasNonzeroInput && actual.minExponent >= envelope.minExponent &&
        actual.maxExponent <= envelope.maxExponent &&
        actual.maxSignificandBits <= envelope.maxSignificandBits,
        "local_ee_matrix_values source values changed after LU budget admission")
    }
  }

  /** Standalone trusted probe helper for a real synthetic GeoTrellis tile. */
  def workForTile(
    tile: MultibandTile, spec: LocalEeMatrixValuesSpec.Value, cols: Int, rows: Int
  ): Long = {
    LocalEeMatrixValuesNumeric.validateTileShape(tile, spec, cols, rows)
    val pixels = Math.multiplyExact(cols.toLong, rows.toLong)
    val minimumWork = Math.multiplyExact(pixels, structuralWorkPerPixel(spec))
    require(minimumWork <= LocalEeMatrixValuesBudget.MaxTileWork,
      s"local_ee_matrix_values exceeds the ${LocalEeMatrixValuesBudget.MaxTileWork} per-tile work budget")
    val work = Math.multiplyExact(pixels, workPerPixel(spec, envelopeForTile(tile, spec, cols, rows)))
    require(work <= LocalEeMatrixValuesBudget.MaxTileWork,
      s"local_ee_matrix_values exceeds the ${LocalEeMatrixValuesBudget.MaxTileWork} per-tile work budget")
    work
  }

  private[reduce] def envelopeForTile(
    tile: MultibandTile, spec: LocalEeMatrixValuesSpec.Value, cols: Int, rows: Int
  ): Envelope = {
    var hasFinite = false
    var hasNonzero = false
    var minimumExponent = Int.MaxValue
    var maximumExponent = Int.MinValue
    var maximumSignificandBits = 1
    val operandCount = spec.operands.length
    var pixel = 0
    val pixelCount = Math.multiplyExact(cols, rows)
    while (pixel < pixelCount) {
      var operand = 0
      while (operand < operandCount) {
        val value = spec.operands(operand) match {
          case LocalEeMatrixValuesSpec.Band(index) => tile.band(index).getDouble(pixel % cols, pixel / cols)
          case LocalEeMatrixValuesSpec.Constant(bits) => java.lang.Double.longBitsToDouble(bits)
        }
        require(!value.isInfinite,
          "matrix values input contains an infinite Float64 cell")
        if (!value.isNaN) {
          hasFinite = true
          if (value != 0d) {
            val raw = java.lang.Double.doubleToRawLongBits(value) & Long.MaxValue
            val exponentBits = ((raw >>> 52) & 0x7ffL).toInt
            val fraction = raw & 0x000fffffffffffffL
            val significand = if (exponentBits == 0) fraction else (1L << 52) | fraction
            val exponent = if (exponentBits == 0) -1074 else exponentBits - 1023 - 52
            val trailingZeros = java.lang.Long.numberOfTrailingZeros(significand)
            val normalizedExponent = exponent + trailingZeros
            val bits = 64 - java.lang.Long.numberOfLeadingZeros(significand >>> trailingZeros)
            hasNonzero = true
            minimumExponent = math.min(minimumExponent, normalizedExponent)
            maximumExponent = math.max(maximumExponent, normalizedExponent)
            maximumSignificandBits = math.max(maximumSignificandBits, bits)
          }
        }
        operand += 1
      }
      pixel += 1
    }
    if (!hasNonzero) Envelope(hasFinite, false, 0, 0, 1)
    else Envelope(hasFinite, true, minimumExponent, maximumExponent, maximumSignificandBits)
  }

  private[reduce] def merge(left: Envelope, right: Envelope): Envelope = {
    val nonzero = left.hasNonzeroInput || right.hasNonzeroInput
    if (!nonzero) Envelope(left.hasFiniteInput || right.hasFiniteInput, false, 0, 0, 1)
    else Envelope(
      left.hasFiniteInput || right.hasFiniteInput,
      true,
      if (!left.hasNonzeroInput) right.minExponent
      else if (!right.hasNonzeroInput) left.minExponent
      else math.min(left.minExponent, right.minExponent),
      if (!left.hasNonzeroInput) right.maxExponent
      else if (!right.hasNonzeroInput) left.maxExponent
      else math.max(left.maxExponent, right.maxExponent),
      math.max(left.maxSignificandBits, right.maxSignificandBits))
  }

  private[reduce] def workForEnvelope(
    spec: LocalEeMatrixValuesSpec.Value, envelope: Envelope
  ): Long = workPerPixel(spec, envelope)

  private def workPerPixel(spec: LocalEeMatrixValuesSpec.Value, envelope: Envelope): Long = {
    val cells = Math.multiplyExact(spec.rows, spec.cols)
    val structural = structuralWorkPerPixel(spec)
    if (!envelope.hasFiniteInput) return structural

    val size = spec.rows.toLong
    val scaledInputBits = if (envelope.hasNonzeroInput) {
      Math.addExact(envelope.maxSignificandBits.toLong,
        envelope.maxExponent.toLong - envelope.minExponent.toLong)
    } else 1L
    val determinantBits = Math.addExact(
      Math.multiplyExact(size, math.max(1L, scaledInputBits)), ceilLog2Factorial(spec.rows))
    // A common dyadic denominator turns the matrix into bounded integers. Each
    // minor is below n! * 2^(n*scaledInputBits); LU factors are ratios of minors,
    // while U also carries the common binary scale. The 3*D + 2*scale allowance
    // covers unreduced BigFraction products and subtraction cross-products.
    val scaleBits = if (envelope.hasNonzeroInput) math.abs(envelope.minExponent.toLong) else 0L
    val rawIntermediateBits = Math.addExact(
      Math.addExact(Math.multiplyExact(3L, determinantBits),
        Math.multiplyExact(2L, scaleBits)), 16L)
    // BigDecimal(double) builds decimal powers of ten before BigFraction reduces
    // them; their unreduced denominator can exceed the final dyadic denominator.
    val decimalScaleBits = if (envelope.hasNonzeroInput && envelope.minExponent < 0) scaleBits else 0L
    val decimalPowerBits = Math.multiplyExact(decimalScaleBits, 3322L)
    val decimalDenominatorBits = Math.addExact(
      decimalPowerBits / 1000L, if (decimalPowerBits % 1000L == 0L) 0L else 1L)
    val inputDecimalBits = Math.addExact(
      math.max(decimalDenominatorBits + envelope.maxSignificandBits.toLong,
        math.max(1L, envelope.maxExponent.toLong + envelope.maxSignificandBits.toLong)), 2L)
    val outputFactorBits = Math.addExact(
      Math.addExact(Math.multiplyExact(2L, determinantBits), scaleBits), 4L)
    val outputShiftBits = math.min(ExactOutputShiftLimit, Math.addExact(outputFactorBits, 52L))
    val outputRoundingBits = Math.addExact(outputFactorBits, outputShiftBits)
    val checkedIntermediateBits = math.max(rawIntermediateBits,
      math.max(inputDecimalBits, outputRoundingBits))
    require(checkedIntermediateBits <= RationalBitBound,
      s"matrix values LU rational intermediate exceeds the $RationalBitBound-bit bound")
    val limbs = Math.addExact(math.max(rawIntermediateBits, inputDecimalBits), LimbBits - 1L) / LimbBits
    val limbSquare = Math.multiplyExact(limbs, limbs)
    val outputLimbs = Math.addExact(outputRoundingBits, LimbBits - 1L) / LimbBits
    val outputLimbSquare = Math.multiplyExact(outputLimbs, outputLimbs)
    val comparisonsAndDivisions = Math.multiplyExact(size, size - 1L)
    val updates = Math.multiplyExact(size,
      Math.multiplyExact(size - 1L, 2L * size - 1L)) / 6L
    val rationalOperations = Math.addExact(
      Math.addExact(cells.toLong, Math.multiplyExact(2L, comparisonsAndDivisions)),
      Math.addExact(Math.multiplyExact(2L, updates), 2L * cells.toLong))
    val rationalWork = Math.multiplyExact(limbSquare,
      Math.multiplyExact(FactorArithmeticMultiplier, rationalOperations))
    val outputConversions = 2L * cells.toLong
    val outputRoundingWork = Math.multiplyExact(outputConversions,
      Math.addExact(32L, Math.multiplyExact(8L, Math.addExact(limbs, outputLimbSquare))))
    Math.addExact(structural, Math.addExact(rationalWork, outputRoundingWork))
  }

  private def structuralWorkPerPixel(spec: LocalEeMatrixValuesSpec.Value): Long = {
    val operandCount = spec.operands.length.toLong
    val preflightScan = Math.multiplyExact(16L, operandCount)
    val runtimeEnvelopeCheck = Math.multiplyExact(16L, operandCount)
    val numericOperandRead = Math.multiplyExact(8L, operandCount)
    val workingBandCopy = Math.multiplyExact(8L, spec.inputBands.toLong)
    val outputWritesAndArrays = Math.addExact(Math.multiplyExact(16L, spec.outputCells.toLong), 64L)
    Math.addExact(Math.addExact(preflightScan, runtimeEnvelopeCheck),
      Math.addExact(numericOperandRead, Math.addExact(workingBandCopy, outputWritesAndArrays)))
  }

  private def ceilLog2Factorial(size: Int): Long = size match {
    case 1 => 0L
    case 2 => 1L
    case 3 => 3L
    case 4 => 5L
    case _ => throw new IllegalArgumentException("LU budget supports matrix sizes 1 through 4")
  }
}
