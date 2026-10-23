package local.ee.reduce

import geotrellis.raster.MultibandTile
import org.apache.spark.rdd.RDD

/** Input-sensitive preflight for QR/SVD exact intermediates and bounded fallback work. */
private[reduce] object LocalEeMatrixOrthogonalBudget {
  type Envelope = LocalEeMatrixFactorizationBudget.Envelope
  private[reduce] final class DecimalEnvelopeExceeded extends RuntimeException
  // Separate fixed resource ceiling for MC80 Jacobi scales. It is fail-closed,
  // not a proof that every finite matrix's intermediate scale remains below it.
  private[reduce] val JacobiDecimalScaleLimit = 65536

  def admitSource(
    source: RDD[(Any, MultibandTile)], keyCount: Long,
    spec: LocalEeMatrixValuesSpec.Value, cols: Int, rows: Int
  ): Envelope = {
    require(keyCount > 0L && keyCount <= LocalEeMatrixValuesBudget.MaxTileKeys,
      s"local_ee_matrix_values supports 1 to ${LocalEeMatrixValuesBudget.MaxTileKeys} tile keys")
    val pixels = Math.multiplyExact(cols.toLong, rows.toLong)
    val minimumWork = Math.multiplyExact(pixels, structuralWorkPerPixel(spec))
    require(pixels > 0L && minimumWork <= LocalEeMatrixValuesBudget.MaxTileWork,
      s"local_ee_matrix_values exceeds the ${LocalEeMatrixValuesBudget.MaxTileWork} per-tile work budget")
    aggregateWork(minimumWork, keyCount)
    val (envelope, actualKeyCount) = source.map { case (_, tile) =>
      LocalEeMatrixValuesNumeric.validateTileShape(tile, spec, cols, rows)
      (LocalEeMatrixFactorizationBudget.envelopeForTile(tile, spec, cols, rows), 1L)
    }.fold((emptyEnvelope, 0L)) { case ((left, leftCount), (right, rightCount)) =>
      (LocalEeMatrixFactorizationBudget.merge(left, right), Math.addExact(leftCount, rightCount))
    }
    require(actualKeyCount == keyCount,
      "local_ee_matrix_values tile key count changed during orthogonal budget admission")
    val tileWork = Math.multiplyExact(pixels, workPerPixel(spec, envelope))
    require(tileWork > 0L && tileWork <= LocalEeMatrixValuesBudget.MaxTileWork,
      s"local_ee_matrix_values exceeds the ${LocalEeMatrixValuesBudget.MaxTileWork} per-tile work budget")
    aggregateWork(tileWork, keyCount)
    envelope
  }

  def requireWithinEnvelope(
    tile: MultibandTile, spec: LocalEeMatrixValuesSpec.Value,
    cols: Int, rows: Int, envelope: Envelope
  ): Unit = {
    LocalEeMatrixValuesNumeric.validateTileShape(tile, spec, cols, rows)
    val actual = LocalEeMatrixFactorizationBudget.envelopeForTile(tile, spec, cols, rows)
    require(!actual.hasFiniteInput || envelope.hasFiniteInput,
      "local_ee_matrix_values source values changed after orthogonal budget admission")
    if (actual.hasNonzeroInput) {
      require(envelope.hasNonzeroInput && actual.minExponent >= envelope.minExponent &&
        actual.maxExponent <= envelope.maxExponent &&
        actual.maxSignificandBits <= envelope.maxSignificandBits,
        "local_ee_matrix_values source values changed after orthogonal budget admission")
    }
  }

  def workForTile(
    tile: MultibandTile, spec: LocalEeMatrixValuesSpec.Value, cols: Int, rows: Int
  ): Long = {
    LocalEeMatrixValuesNumeric.validateTileShape(tile, spec, cols, rows)
    val pixels = Math.multiplyExact(cols.toLong, rows.toLong)
    val envelope = LocalEeMatrixFactorizationBudget.envelopeForTile(tile, spec, cols, rows)
    val work = Math.multiplyExact(pixels, workPerPixel(spec, envelope))
    require(work <= LocalEeMatrixValuesBudget.MaxTileWork,
      s"local_ee_matrix_values exceeds the ${LocalEeMatrixValuesBudget.MaxTileWork} per-tile work budget")
    work
  }

  def envelopeForValues(values: Array[Double]): Envelope = {
    var hasFinite = false
    var hasNonzero = false
    var minExponent = Int.MaxValue
    var maxExponent = Int.MinValue
    var maxSignificandBits = 1
    var index = 0
    while (index < values.length) {
      val value = values(index)
      if (!value.isFinite) return LocalEeMatrixFactorizationBudget.Envelope(false, false, 0, 0, 1)
      hasFinite = true
      if (value != 0d) {
        val bits = java.lang.Double.doubleToRawLongBits(value) & Long.MaxValue
        val fraction = bits & 0x000fffffffffffffL
        val exponentBits = ((bits >>> 52) & 0x7ffL).toInt
        val significand = if (exponentBits == 0) fraction else (1L << 52) | fraction
        val rawExponent = if (exponentBits == 0) -1074 else exponentBits - 1023 - 52
        val trailingZeros = java.lang.Long.numberOfTrailingZeros(significand)
        val reduced = significand >>> trailingZeros
        val exponent = rawExponent + trailingZeros
        minExponent = math.min(minExponent, exponent)
        maxExponent = math.max(maxExponent, exponent)
        maxSignificandBits = math.max(maxSignificandBits,
          64 - java.lang.Long.numberOfLeadingZeros(reduced))
        hasNonzero = true
      }
      index += 1
    }
    if (!hasNonzero) LocalEeMatrixFactorizationBudget.Envelope(hasFinite, false, 0, 0, 1)
    else LocalEeMatrixFactorizationBudget.Envelope(
      hasFinite, true, minExponent, maxExponent, maxSignificandBits)
  }

  def decimalDigitLimit(spec: LocalEeMatrixValuesSpec.Value, envelope: Envelope): Int =
    Math.toIntExact(decimalDigitsFor(spec, envelope))

  private[reduce] def requireDecimalWidth(value: java.math.BigDecimal, limit: Int): Unit = {
    if (value.precision().toLong > limit.toLong ||
      math.abs(value.scale().toLong) > limit.toLong) throw new DecimalEnvelopeExceeded
  }

  private[reduce] def requireJacobiDecimalWidth(
    value: java.math.BigDecimal, scaleLimit: Int
  ): Unit = {
    if (value.precision() > 80 || math.abs(value.scale().toLong) > scaleLimit.toLong) {
      throw new DecimalEnvelopeExceeded
    }
  }

  def workPerPixel(
    spec: LocalEeMatrixValuesSpec.Value, envelope: Envelope
  ): Long = {
    val rows = spec.rows.toLong
    val cols = spec.cols.toLong
    val p = math.min(rows, cols)
    val tallRows = math.max(rows, cols)
    val cells = Math.multiplyExact(rows, cols)
    val structure = structuralWorkPerPixel(spec)
    if (!envelope.hasFiniteInput) return structure

    val significandBits = envelope.maxSignificandBits.toLong
    val scaledInputBits = if (envelope.hasNonzeroInput) Math.addExact(significandBits,
      envelope.maxExponent.toLong - envelope.minExponent.toLong) else 1L
    // QR has no exact-rank or spectral-invariant pass. Charge those expensive
    // input-sensitive BigInteger paths only when the SVD producer will use them.
    val (rankWork, gramWork) = if (spec.op == "svd") {
      val determinantBits = Math.addExact(Math.multiplyExact(p, scaledInputBits), ceilLog2Factorial(p))
      val previousMinorBits = if (p <= 1L) scaledInputBits
        else Math.addExact(Math.multiplyExact(p - 1L, scaledInputBits), ceilLog2Factorial(p - 1L))
      // Bareiss temporary products are bounded by twice the previous minor size.
      val rankTemporaryBits = if (p <= 1L) scaledInputBits
        else Math.addExact(Math.multiplyExact(2L, previousMinorBits), 1L)
      val checkedRankBits = math.max(scaledInputBits, math.max(determinantBits, rankTemporaryBits))
      require(checkedRankBits <= LocalEeMatrixFactorization.RationalBitBound,
        s"matrix orthogonal exact-rank temporary exceeds the ${LocalEeMatrixFactorization.RationalBitBound}-bit bound")
      val rankLimbs = ceilDiv(checkedRankBits, 64L)
      val rankLimbSquare = Math.multiplyExact(rankLimbs, rankLimbs)
      val rankUpdates = bareissUpdates(rows, cols, p)
      val rankInputLimbs = ceilDiv(scaledInputBits, 64L)
      val rankWork = Math.addExact(
        Math.multiplyExact(8L, Math.multiplyExact(rankUpdates, rankLimbSquare)),
        Math.addExact(Math.multiplyExact(16L, Math.multiplyExact(cells, rankInputLimbs)),
          Math.multiplyExact(16L, Math.multiplyExact(cells, p))))

      val gramBits = Math.addExact(Math.multiplyExact(2L, scaledInputBits),
        Math.addExact(ceilLog2(math.max(rows, cols)), 1L))
      val gramMinorBits = Math.addExact(Math.multiplyExact(p, gramBits),
        Math.addExact(ceilLog2Factorial(p), p))
      require(gramMinorBits <= LocalEeMatrixFactorization.RationalBitBound,
        s"matrix orthogonal Gram invariant exceeds the ${LocalEeMatrixFactorization.RationalBitBound}-bit bound")
      val gramLimbs = ceilDiv(gramBits, 64L)
      val minorLimbs = ceilDiv(gramMinorBits, 64L)
      val gramDotWork = Math.multiplyExact(8L,
        Math.multiplyExact(Math.multiplyExact(p, p),
          Math.multiplyExact(math.max(rows, cols), Math.multiplyExact(gramLimbs, gramLimbs))))
      val determinantTerms = principalMinorTerms(p)
      val gramMinorWork = Math.multiplyExact(8L,
        Math.multiplyExact(determinantTerms, Math.multiplyExact(p,
          Math.multiplyExact(minorLimbs, minorLimbs))))
      val dyadicPowerBits = ceilDiv(Math.multiplyExact(2322L,
        Math.multiplyExact(2L * p, math.abs(envelope.minExponent.toLong))), 1000L)
      val dyadicPowerLimbs = ceilDiv(dyadicPowerBits, 64L)
      val gramConversionWork = Math.multiplyExact(8L * p,
        Math.multiplyExact(p,
          Math.addExact(Math.multiplyExact(dyadicPowerLimbs, dyadicPowerLimbs),
            Math.multiplyExact(minorLimbs, minorLimbs))))
      (rankWork, Math.addExact(gramDotWork,
        Math.addExact(gramMinorWork, gramConversionWork)))
    } else (0L, 0L)

    val decimalLimbs = decimalLimbsFor(spec, envelope)
    val decimalLimbSquare = Math.multiplyExact(decimalLimbs, decimalLimbs)
    val decimalOperations = if (spec.op == "qr") {
      val matrixAndQ = Math.addExact(cells, Math.multiplyExact(rows, rows))
      Math.multiplyExact(5L, Math.multiplyExact(matrixAndQ, p))
    } else {
      val pairs = Math.multiplyExact(p, p - 1L) / 2L
      val pairSweep = Math.addExact(Math.multiplyExact(18L, tallRows), 20L)
      val jacobi = Math.multiplyExact(32L, Math.multiplyExact(pairs, pairSweep))
      val initialCorrelations = Math.multiplyExact(pairs,
        Math.addExact(Math.multiplyExact(6L, tallRows), 10L))
      val columnNorms = Math.multiplyExact(p, Math.addExact(Math.multiplyExact(2L, tallRows), 1L))
      val normalizeU = Math.multiplyExact(tallRows, p)
      val validation = Math.addExact(Math.multiplyExact(16L, Math.multiplyExact(cells, p)),
        Math.multiplyExact(16L, cells))
      val spectrum = Math.multiplyExact(8L, Math.multiplyExact(p, (1L << p) - 1L))
      Math.addExact(Math.addExact(jacobi, initialCorrelations),
        Math.addExact(columnNorms,
        Math.addExact(normalizeU, Math.addExact(validation, spectrum)))
      )
    }
    val decimalWork = Math.multiplyExact(decimalLimbSquare, decimalOperations)
    // Source binary64 -> exact decimal conversion can be wider than the 80-digit
    // Jacobi working context (up to the binary64 subnormal spelling). Charge four
    // bounded passes for initialization, Commons validation, and fallback
    // validation separately instead of multiplying that width by every sweep.
    val sourceLimbs = ceilDiv(Math.multiplyExact(3322L,
      sourceDecimalPrecisionDigits(envelope)), 64000L)
    val sourceRoundWork = if (spec.op == "svd") Math.multiplyExact(32L,
      Math.multiplyExact(cells, Math.multiplyExact(sourceLimbs, sourceLimbs))) else 0L
    val outputProductDigits = if (spec.op == "svd") Math.multiplyExact(
      Math.multiplyExact(2L, p), outputSingularDigits(spec, envelope)) else 0L
    val outputProductLimbs = ceilDiv(Math.multiplyExact(3322L, outputProductDigits), 64000L)
    val outputProductWork = if (spec.op == "svd") Math.multiplyExact(16L * p,
      Math.multiplyExact(outputProductLimbs, outputProductLimbs)) else 0L
    val floatingWork = if (spec.op == "svd") {
      val pairs = Math.multiplyExact(p, p - 1L) / 2L
      Math.addExact(Math.multiplyExact(8L, Math.multiplyExact(cells, p)),
        Math.multiplyExact(32L, Math.multiplyExact(pairs, tallRows + 2L * p)))
    } else Math.multiplyExact(8L, Math.multiplyExact(cells, p))
    val temporaryCells = if (spec.op == "qr") {
      Math.addExact(Math.addExact(Math.multiplyExact(2L, cells), Math.multiplyExact(rows, rows)),
        Math.addExact(Math.multiplyExact(rows, p), spec.outputCells.toLong))
    } else {
      val sourceAndCommonsInput = Math.multiplyExact(2L, cells)
      // Conservative square-workspace allowance; Commons Math 3.6.1 currently
      // uses compact factors, so this deliberately overstates its live matrices.
      val commonsSquareAllowance = Math.addExact(Math.multiplyExact(rows, rows),
        Math.multiplyExact(cols, cols))
      val tallFactorCells = Math.multiplyExact(tallRows, p)
      val jacobiWorkspace = Math.addExact(Math.multiplyExact(3L, tallFactorCells),
        Math.multiplyExact(2L, Math.multiplyExact(p, p)))
      val compactFactors = Math.multiplyExact(Math.addExact(rows, cols), p)
      Math.addExact(Math.addExact(sourceAndCommonsInput, commonsSquareAllowance),
        Math.addExact(jacobiWorkspace,
          Math.addExact(compactFactors, spec.outputCells.toLong)))
    }
    val boundedCopies = Math.multiplyExact(8L, temporaryCells)
    Math.addExact(structure, Math.addExact(rankWork,
      Math.addExact(gramWork,
        Math.addExact(outputProductWork,
          Math.addExact(sourceRoundWork,
            Math.addExact(decimalWork, Math.addExact(floatingWork, boundedCopies)))))))
  }

  private def bareissUpdates(rows: Long, cols: Long, p: Long): Long = {
    var step = 0L
    var count = 0L
    while (step < p - 1L) {
      count = Math.addExact(count,
        Math.multiplyExact(rows - step - 1L, cols - step - 1L))
      step += 1L
    }
    count
  }

  private def decimalLimbsFor(
    spec: LocalEeMatrixValuesSpec.Value, envelope: Envelope
  ): Long = {
    // Jacobi and SVD validation round operands to 80 digits before each product
    // or sum, so the largest product is at most 160 digits (9 64-bit limbs).
    // QR keeps exact binary64 products under the admitted source-envelope cap.
    val decimalDigits = if (spec.op == "qr") decimalDigitsFor(spec, envelope) else 160L
    ceilDiv(Math.multiplyExact(3322L, decimalDigits), 64000L)
  }

  private def sourceDecimalPrecisionDigits(envelope: Envelope): Long = {
    val significandDigits = ceilDiv(Math.multiplyExact(301L,
      envelope.maxSignificandBits.toLong), 1000L)
    val positiveDigits = ceilDiv(Math.multiplyExact(301L,
      math.max(0L, envelope.maxExponent.toLong) + envelope.maxSignificandBits.toLong), 1000L)
    val negativeDigits = Math.addExact(significandDigits,
      ceilDiv(Math.multiplyExact(699L, math.max(0L, -envelope.minExponent.toLong)), 1000L))
    math.max(positiveDigits, negativeDigits) + 2L
  }

  private def outputSingularDigits(
    spec: LocalEeMatrixValuesSpec.Value, envelope: Envelope
  ): Long = {
    if (!envelope.hasNonzeroInput) return 1L
    val p = math.min(spec.rows, spec.cols).toLong
    val maxBinaryExponent = Math.addExact(envelope.maxExponent.toLong,
      Math.addExact(envelope.maxSignificandBits.toLong,
        Math.addExact(ceilLog2(math.max(spec.rows, spec.cols).toLong), 1L)))
    // For exact rank r, the product of its positive singular values is at least
    // 2^(r*minExponent), from any nonzero integer minor on the common dyadic
    // scale. Bound sigma_min by dividing by sigma_max^(r-1), then clamp to the
    // smallest representable Double because only emitted binary64 factors are
    // multiplied exactly during spectrum validation.
    val lowerBinaryExponent = Math.subtractExact(Math.multiplyExact(p,
      envelope.minExponent.toLong), Math.multiplyExact(p - 1L, maxBinaryExponent))
    val minimumRawExponent = if (lowerBinaryExponent < -1022L) -1074L
      else lowerBinaryExponent - 52L
    val significandDigits = ceilDiv(301L * 53L, 1000L)
    val negativeDigits = Math.addExact(significandDigits,
      Math.addExact(ceilDiv(Math.multiplyExact(699L,
        math.max(0L, -minimumRawExponent)), 1000L), 2L))
    val positiveDigits = Math.addExact(ceilDiv(Math.multiplyExact(301L,
      math.max(0L, maxBinaryExponent + 53L)), 1000L), 2L)
    math.max(negativeDigits, positiveDigits)
  }

  private def decimalDigitsFor(
    spec: LocalEeMatrixValuesSpec.Value, envelope: Envelope
  ): Long = {
    val p = math.min(spec.rows, spec.cols).toLong
    val decimalScale = math.max(0L, -envelope.minExponent.toLong)
    val magnitudeBits = math.max(0L, envelope.maxExponent.toLong) +
      envelope.maxSignificandBits.toLong
    val magnitudeDigits = ceilDiv(Math.multiplyExact(301L, magnitudeBits), 1000L)
    // This input-sensitive precision/scale limit is enforced before exact decimal
    // products, aligned sums, divisions and square roots. It admits source-derived
    // output scale (including p=4 subnormal sigma products); it is a fail-closed
    // resource envelope, not a theorem that every Jacobi intermediate fits.
    // The value-sensitive limb estimate for Jacobi's MC80 operations is separate.
    val sourceSpan = Math.addExact(decimalScale, magnitudeDigits)
    if (spec.op == "qr") {
      // Exact Householder updates multiply three generated binary64 decimals
      // (beta, reflector entry, and dot), whose exact spellings can be wider than
      // the source cells even for ordinary matrices. This is an enforced,
      // input-sensitive resource envelope with per-operation width checks, not a
      // proof that every possible intermediate fits inside it.
      Math.addExact(Math.multiplyExact(4L * p, sourceSpan), 320L)
    } else {
      val sourceDigits = Math.addExact(Math.multiplyExact(2L * p, sourceSpan), 160L)
      val outputProductDigits = Math.multiplyExact(2L * p,
        outputSingularDigits(spec, envelope))
      math.max(sourceDigits, Math.addExact(outputProductDigits, 160L))
    }
  }

  private def structuralWorkPerPixel(spec: LocalEeMatrixValuesSpec.Value): Long = {
    val operands = spec.operands.length.toLong
    val scan = Math.multiplyExact(32L, operands)
    val reads = Math.multiplyExact(8L, operands)
    val copies = Math.multiplyExact(8L, spec.inputBands.toLong)
    val output = Math.addExact(Math.multiplyExact(16L, spec.outputCells.toLong), 64L)
    Math.addExact(Math.addExact(scan, reads), Math.addExact(copies, output))
  }

  private[reduce] def aggregateWork(tileWork: Long, keyCount: Long): Long = {
    require(keyCount > 0L && keyCount <= LocalEeMatrixValuesBudget.MaxTileKeys,
      s"local_ee_matrix_values supports 1 to ${LocalEeMatrixValuesBudget.MaxTileKeys} tile keys")
    val total = Math.multiplyExact(tileWork, keyCount)
    require(total <= LocalEeMatrixValuesBudget.MaxTotalWork,
      s"local_ee_matrix_values exceeds the ${LocalEeMatrixValuesBudget.MaxTotalWork} aggregate work budget")
    total
  }

  private def ceilLog2Factorial(value: Long): Long = {
    var result = 0L
    var factor = 2L
    while (factor <= value) {
      result = Math.addExact(result, ceilLog2(factor))
      factor += 1L
    }
    result
  }

  private def principalMinorTerms(p: Long): Long = {
    var order = 1L
    var total = 0L
    while (order <= p) {
      var choose = 1L
      var item = 1L
      while (item <= order) {
        choose = Math.multiplyExact(choose, p - item + 1L) / item
        item += 1L
      }
      var factorial = 1L
      item = 2L
      while (item <= order) {
        factorial = Math.multiplyExact(factorial, item)
        item += 1L
      }
      total = Math.addExact(total, Math.multiplyExact(choose, factorial))
      order += 1L
    }
    total
  }

  private def ceilLog2(value: Long): Long = {
    if (value <= 1L) 0L else 64L - java.lang.Long.numberOfLeadingZeros(value - 1L)
  }

  private def ceilDiv(value: Long, divisor: Long): Long =
    Math.addExact(value, divisor - 1L) / divisor

  private def emptyEnvelope: Envelope =
    LocalEeMatrixFactorizationBudget.Envelope(false, false, 0, 0, 1)
}
