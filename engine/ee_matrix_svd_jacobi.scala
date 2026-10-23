package local.ee.reduce

import java.math.{BigDecimal, MathContext, RoundingMode}

/** Fixed-sweep one-sided Jacobi fallback for compact matrices of at most eight axes. */
private[reduce] object LocalEeMatrixSvdJacobi {
  private val Arithmetic = new MathContext(80, RoundingMode.HALF_EVEN)
  private val RotationTolerance = new BigDecimal("1e-14")

  def decompose(
    source: Array[Array[Double]], exactRank: Int, decimalScaleLimit: Int
  ): Option[LocalEeMatrixOrthogonalFactors] = {
    try decomposeBounded(source, exactRank, decimalScaleLimit)
    catch { case _: LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded => None }
  }

  private def decomposeBounded(
    source: Array[Array[Double]], exactRank: Int, decimalScaleLimit: Int
  ): Option[LocalEeMatrixOrthogonalFactors] = {
    val wide = source.length < source(0).length
    val tallRows = if (wide) source(0).length else source.length
    val p = math.min(source.length, source(0).length)
    val b = Array.ofDim[BigDecimal](tallRows, p)
    var row = 0
    while (row < tallRows) {
      var col = 0
      while (col < p) {
        val value = if (wide) source(col)(row) else source(row)(col)
        // Round the exact binary64 decimal spelling to MC80 once; 80 decimal
        // digits preserve its binary64 round-trip value while bounding later
        // Jacobi dot/update coefficients. Exact rank and Gram checks still use
        // the original binary64 inputs, not these working copies.
        b(row)(col) = checked(new BigDecimal(value).round(Arithmetic), decimalScaleLimit)
        col += 1
      }
      row += 1
    }
    val v = Array.tabulate(p, p)((r, c) => if (r == c) 1d else 0d)
    var converged = correlationsSmall(b, decimalScaleLimit)
    var sweep = 0
    while (!converged && sweep < 32) {
      var left = 0
      while (left < p) {
        var right = left + 1
        while (right < p) {
          val alpha = columnDot(b, left, left, decimalScaleLimit)
          val beta = columnDot(b, right, right, decimalScaleLimit)
          val gamma = columnDot(b, left, right, decimalScaleLimit)
          if (alpha.signum() != 0 && beta.signum() != 0 && gamma.signum() != 0 &&
            normalizedCorrelation(alpha, beta, gamma, decimalScaleLimit)
              .compareTo(RotationTolerance) > 0) {
            val (cosine, sine) = rotationFor(alpha, beta, gamma, decimalScaleLimit)
            if (sine.signum() == 0 || cosine.signum() == 0) return None
            // Keep the high-precision angle for B: its product with a huge column
            // can preserve a small residual even when the angle is < minSubnormal.
            rotateColumns(b, left, right, cosine, sine, decimalScaleLimit)
            rotateColumns(v, left, right, cosine.doubleValue(), sine.doubleValue())
          }
          right += 1
        }
        left += 1
      }
      sweep += 1
      converged = correlationsSmall(b, decimalScaleLimit)
    }
    // After the fixed sweep cap, test the resulting rank-aware candidate through
    // exact source-spectrum, orthogonality and normwise residual invariants. Null
    // columns can remain mutually correlated after their ghost norms have fallen
    // below the exact-rank active spectrum, so all-column correlation is not the
    // acceptance criterion.
    val norms = Array.tabulate(p)(col => checked(
      columnDot(b, col, col, decimalScaleLimit).sqrt(Arithmetic), decimalScaleLimit))
    val order = (0 until p).sortWith((left, right) => norms(left).compareTo(norms(right)) > 0)
    val sortedB = Array.tabulate(tallRows, p)((r, c) => b(r)(order(c)))
    val sortedV = Array.tabulate(p, p)((r, c) => v(r)(order(c)))
    val singular = Array.fill(p)(0d)
    row = 0
    while (row < exactRank) {
      val value = norms(order(row)).doubleValue()
      if (!value.isFinite || value == 0d) return None
      singular(row) = value
      row += 1
    }

    val uTall = Array.ofDim[Double](tallRows, p)
    var col = 0
    while (col < exactRank) {
      val norm = norms(order(col))
      row = 0
      while (row < tallRows) {
        val value = checked(sortedB(row)(col).divide(norm, Arithmetic), decimalScaleLimit)
          .doubleValue()
        if (!value.isFinite) return None
        uTall(row)(col) = if (value == 0d) 0d else value
        row += 1
      }
      col += 1
    }
    if (!completeZeroColumns(uTall, exactRank)) return None
    val (u, outV) = if (wide) (sortedV, uTall) else (uTall, sortedV)
    Some(LocalEeMatrixOrthogonalFactors(u, singular, outV))
  }

  private def rotationFor(
    alpha: BigDecimal, beta: BigDecimal, gamma: BigDecimal, bound: Int
  ): (BigDecimal, BigDecimal) = {
    val difference = roundedAdd(beta, alpha.negate(), bound)
    val twoGamma = roundedMultiply(gamma, new BigDecimal("2"), bound)
    val tau = roundedDivide(difference, twoGamma, bound)
    val tauSquared = roundedMultiply(tau, tau, bound)
    val root = roundedSqrt(roundedAdd(BigDecimal.ONE, tauSquared, bound), bound)
    val denominator = roundedAdd(tau.abs(), root, bound)
    val magnitude = roundedDivide(BigDecimal.ONE, denominator, bound)
    val t = if (tau.signum() == 0) BigDecimal.ONE
      else if (tau.signum() < 0) magnitude.negate() else magnitude
    val tSquared = roundedMultiply(t, t, bound)
    val rootOnePlusTSquared = roundedSqrt(roundedAdd(BigDecimal.ONE, tSquared, bound), bound)
    val cosine = roundedDivide(BigDecimal.ONE, rootOnePlusTSquared, bound)
    (cosine, roundedMultiply(t, cosine, bound))
  }

  private def rotateColumns(
    matrix: Array[Array[BigDecimal]], left: Int, right: Int,
    cosine: BigDecimal, sine: BigDecimal, bound: Int
  ): Unit = {
    var row = 0
    while (row < matrix.length) {
      val oldLeft = matrix(row)(left)
      val oldRight = matrix(row)(right)
      val leftA = roundedMultiply(oldLeft, cosine, bound)
      val leftB = roundedMultiply(oldRight, sine, bound)
      matrix(row)(left) = roundedAdd(leftA, leftB.negate(), bound)
      val rightA = roundedMultiply(oldLeft, sine, bound)
      val rightB = roundedMultiply(oldRight, cosine, bound)
      matrix(row)(right) = roundedAdd(rightA, rightB, bound)
      row += 1
    }
  }

  private def rotateColumns(
    matrix: Array[Array[Double]], left: Int, right: Int, cosine: Double, sine: Double
  ): Unit = {
    var row = 0
    while (row < matrix.length) {
      val oldLeft = matrix(row)(left)
      val oldRight = matrix(row)(right)
      matrix(row)(left) = cosine * oldLeft - sine * oldRight
      matrix(row)(right) = sine * oldLeft + cosine * oldRight
      row += 1
    }
  }

  private def correlationsSmall(b: Array[Array[BigDecimal]], bound: Int): Boolean = {
    val p = b(0).length
    var left = 0
    while (left < p) {
      var right = left + 1
      while (right < p) {
        val alpha = columnDot(b, left, left, bound)
        val beta = columnDot(b, right, right, bound)
        val gamma = columnDot(b, left, right, bound)
        if (alpha.signum() != 0 && beta.signum() != 0 && gamma.signum() != 0 &&
          normalizedCorrelation(alpha, beta, gamma, bound).compareTo(RotationTolerance) > 0) return false
        right += 1
      }
      left += 1
    }
    true
  }

  private def normalizedCorrelation(
    alpha: BigDecimal, beta: BigDecimal, gamma: BigDecimal, bound: Int
  ): BigDecimal = {
    val denominator = roundedSqrt(roundedMultiply(alpha, beta, bound), bound)
    if (denominator.signum() == 0) BigDecimal.ZERO
    else roundedDivide(gamma.abs(), denominator, bound)
  }

  private def columnDot(
    matrix: Array[Array[BigDecimal]], left: Int, right: Int, bound: Int
  ): BigDecimal = {
    var result = BigDecimal.ZERO
    var row = 0
    while (row < matrix.length) {
      val product = roundedMultiply(matrix(row)(left), matrix(row)(right), bound)
      result = roundedAdd(result, product, bound)
      row += 1
    }
    result
  }

  private def roundedMultiply(left: BigDecimal, right: BigDecimal, bound: Int): BigDecimal = {
    val roundedLeft = left.round(Arithmetic)
    val roundedRight = right.round(Arithmetic)
    val scale = roundedLeft.scale().toLong + roundedRight.scale().toLong
    if (math.abs(scale) > bound.toLong) {
      throw new LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded
    }
    checked(roundedLeft.multiply(roundedRight, Arithmetic), bound)
  }

  private def roundedAdd(left: BigDecimal, right: BigDecimal, bound: Int): BigDecimal = {
    val roundedLeft = left.round(Arithmetic)
    val roundedRight = right.round(Arithmetic)
    if (roundedLeft.signum() == 0) return checked(roundedRight, bound)
    if (roundedRight.signum() == 0) return checked(roundedLeft, bound)
    val leftExponent = roundedLeft.precision().toLong - roundedLeft.scale().toLong
    val rightExponent = roundedRight.precision().toLong - roundedRight.scale().toLong
    if (math.abs(leftExponent - rightExponent) > Arithmetic.getPrecision.toLong + 1L) {
      return if (leftExponent > rightExponent) checked(roundedLeft, bound)
        else checked(roundedRight, bound)
    }
    val targetScale = math.max(roundedLeft.scale().toLong, roundedRight.scale().toLong)
    val alignedDigits = math.max(roundedLeft.precision().toLong + targetScale - roundedLeft.scale().toLong,
      roundedRight.precision().toLong + targetScale - roundedRight.scale().toLong) + 1L
    // Both inputs have at most 80 significant digits and the adjusted-exponent
    // gap is at most 81 here. Scale alignment therefore spans at most 161 digits,
    // plus one carry digit, independent of the enforced scale ceiling.
    if (targetScale > bound.toLong || alignedDigits > 162L) {
      throw new LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded
    }
    checked(roundedLeft.add(roundedRight, Arithmetic), bound)
  }

  private def roundedDivide(left: BigDecimal, right: BigDecimal, bound: Int): BigDecimal = {
    val adjustedExponent = left.precision().toLong - left.scale().toLong -
      right.precision().toLong + right.scale().toLong
    val estimatedScale = Arithmetic.getPrecision.toLong - adjustedExponent - 1L
    if (math.abs(estimatedScale) > bound.toLong) {
      throw new LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded
    }
    checked(left.divide(right, Arithmetic), bound)
  }

  private def roundedSqrt(value: BigDecimal, bound: Int): BigDecimal =
    checked(value.sqrt(Arithmetic), bound)

  private def checked(value: BigDecimal, bound: Int): BigDecimal = {
    LocalEeMatrixOrthogonalBudget.requireJacobiDecimalWidth(value, bound)
    value
  }

  private def completeZeroColumns(matrix: Array[Array[Double]], rank: Int): Boolean = {
    var col = rank
    while (col < matrix(0).length) {
      var best = Array.empty[Double]
      var bestNorm = 0d
      var axis = 0
      while (axis < matrix.length) {
        val candidate = new Array[Double](matrix.length)
        candidate(axis) = 1d
        var pass = 0
        while (pass < 2) {
          var previous = 0
          while (previous < col) {
            var dot = 0d
            var row = 0
            while (row < matrix.length) {
              dot += candidate(row) * matrix(row)(previous)
              row += 1
            }
            row = 0
            while (row < matrix.length) {
              candidate(row) -= dot * matrix(row)(previous)
              row += 1
            }
            previous += 1
          }
          pass += 1
        }
        var norm = 0d
        var row = 0
        while (row < matrix.length) {
          norm = java.lang.Math.hypot(norm, candidate(row))
          row += 1
        }
        if (norm > bestNorm) {
          bestNorm = norm
          best = candidate
        }
        axis += 1
      }
      if (bestNorm == 0d || !bestNorm.isFinite) return false
      var row = 0
      while (row < matrix.length) {
        matrix(row)(col) = best(row) / bestNorm
        row += 1
      }
      col += 1
    }
    true
  }
}
