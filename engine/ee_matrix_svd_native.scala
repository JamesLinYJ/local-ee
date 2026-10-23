package local.ee.reduce

import java.math.{BigDecimal, MathContext, RoundingMode}
import org.apache.commons.math3.linear.{Array2DRowRealMatrix, SingularValueDecomposition}

/** Commons Math primary path with exact-rank, orthogonality and residual validation. */
private[reduce] object LocalEeMatrixSvdNative {
  private val Arithmetic = new MathContext(80, RoundingMode.HALF_EVEN)
  private val ResidualTolerance = new BigDecimal("1e-10")
  private val SpectrumTolerance = new BigDecimal("1e-10")

  def evaluate(
    source: Array[Array[Double]], spec: LocalEeMatrixValuesSpec.Value, decimalDigitBound: Int
  ): Array[Double] = {
    val factors = LocalEeMatrixOrthogonalRank.exactRank(source).flatMap { rank =>
      val coefficients = if (rank == 0) Vector.empty
        else LocalEeMatrixOrthogonalRank.gramCoefficients(source, rank)
          .getOrElse(return Array.fill(spec.outputCells)(Double.NaN))
      val expectedSpectrum = coefficients.map(LocalEeMatrixOrthogonalRank.toDecimal)
      val commons = commonsFactors(source).filter(candidate =>
        validFactors(source, candidate, rank, expectedSpectrum, decimalDigitBound))
      // Jacobi uses a separate scale ceiling; the unchanged priced source/output
      // envelope still validates every returned factor below.
      commons.orElse(LocalEeMatrixSvdJacobi.decompose(source, rank,
        LocalEeMatrixOrthogonalBudget.JacobiDecimalScaleLimit)
        .filter(candidate => validFactors(source, candidate, rank, expectedSpectrum, decimalDigitBound)))
    }
    factors.map(factorOutput(_, spec)).getOrElse(Array.fill(spec.outputCells)(Double.NaN))
  }

  private def commonsFactors(source: Array[Array[Double]]): Option[LocalEeMatrixOrthogonalFactors] = {
    try {
      val decomposition = new SingularValueDecomposition(
        new Array2DRowRealMatrix(source.map(_.clone()), false))
      val p = math.min(source.length, source(0).length)
      Some(LocalEeMatrixOrthogonalFactors(
        matrixData(decomposition.getU, source.length, p),
        decomposition.getSingularValues,
        matrixData(decomposition.getV, source(0).length, p)))
    } catch {
      case _: RuntimeException => None
    }
  }

  private def validFactors(
    source: Array[Array[Double]], factors: LocalEeMatrixOrthogonalFactors,
    exactRank: Int, expectedSpectrum: Vector[BigDecimal], decimalDigitBound: Int
  ): Boolean = {
    try validFactorsBounded(source, factors, exactRank, expectedSpectrum, decimalDigitBound)
    catch { case _: LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded => false }
  }

  private def validFactorsBounded(
    source: Array[Array[Double]], factors: LocalEeMatrixOrthogonalFactors,
    exactRank: Int, expectedSpectrum: Vector[BigDecimal], decimalDigitBound: Int
  ): Boolean = {
    val rows = source.length
    val cols = source(0).length
    val p = math.min(rows, cols)
    if (factors.u.length != rows || factors.u.exists(_.length != p) ||
      factors.v.length != cols || factors.v.exists(_.length != p) || factors.singular.length != p) return false
    if (factors.u.exists(_.exists(value => !value.isFinite)) ||
      factors.v.exists(_.exists(value => !value.isFinite)) ||
      factors.singular.exists(value => !value.isFinite || value < 0d)) return false
    if (factors.singular.count(_ > 0d) != exactRank) return false
    var index = 1
    while (index < p) {
      if (factors.singular(index - 1) < factors.singular(index)) return false
      index += 1
    }
    orthonormal(factors.u, p) && orthonormal(factors.v, p) &&
      reconstructs(source, factors, decimalDigitBound) &&
      spectrumMatches(factors, exactRank, expectedSpectrum, decimalDigitBound)
  }

  /** Compare every elementary coefficient of the squared singular spectrum. */
  private def spectrumMatches(
    factors: LocalEeMatrixOrthogonalFactors, exactRank: Int,
    expectedSpectrum: Vector[BigDecimal], decimalDigitBound: Int
  ): Boolean = {
    var order = 1
    while (order <= exactRank) {
      val exact = expectedSpectrum(order - 1)
      if (exact.signum() <= 0) return false
      val active = factors.singular.take(exactRank).map(value => new BigDecimal(value))
      val actual = if (order == exactRank) {
        active.foldLeft(BigDecimal.ONE) { (product, sigma) =>
          exactMultiply(exactMultiply(product, sigma, decimalDigitBound), sigma, decimalDigitBound)
        }
      } else {
        val squares = active.map(value => roundedMultiply(value, value, decimalDigitBound))
        elementaryCoefficient(squares, order, decimalDigitBound)
      }
      val residual = roundedAdd(actual, exact.negate(), decimalDigitBound).abs()
      val relative = bounded(residual.divide(exact, Arithmetic), decimalDigitBound)
      if (relative.compareTo(SpectrumTolerance) > 0) return false
      order += 1
    }
    true
  }

  private def elementaryCoefficient(
    values: Array[BigDecimal], order: Int, bound: Int
  ): BigDecimal = {
    var sum = BigDecimal.ZERO
    val selected = new Array[BigDecimal](order)
    def visit(start: Int, depth: Int): Unit = {
      if (depth == order) {
        var product = BigDecimal.ONE
        var index = 0
        while (index < order) {
          product = roundedMultiply(product, selected(index), bound)
          index += 1
        }
        sum = roundedAdd(sum, product, bound)
      } else {
        var index = start
        while (index <= values.length - (order - depth)) {
          selected(depth) = values(index)
          visit(index + 1, depth + 1)
          index += 1
        }
      }
    }
    visit(0, 0)
    sum
  }

  private def orthonormal(matrix: Array[Array[Double]], columns: Int): Boolean = {
    var left = 0
    while (left < columns) {
      var right = left
      while (right < columns) {
        var dot = 0d
        var row = 0
        while (row < matrix.length) {
          dot += matrix(row)(left) * matrix(row)(right)
          row += 1
        }
        val expected = if (left == right) 1d else 0d
        if (!dot.isFinite || math.abs(dot - expected) > 1e-10) return false
        right += 1
      }
      left += 1
    }
    true
  }

  /** Normwise backward error allows unrepresentable tiny angles beside huge values. */
  private def reconstructs(
    source: Array[Array[Double]], factors: LocalEeMatrixOrthogonalFactors,
    decimalDigitBound: Int
  ): Boolean = {
    var sourceNormSquared = BigDecimal.ZERO
    var errorNormSquared = BigDecimal.ZERO
    var row = 0
    while (row < source.length) {
      var col = 0
      while (col < source(0).length) {
        var reconstructed = BigDecimal.ZERO
        var singular = 0
        while (singular < factors.singular.length) {
          val u = new BigDecimal(factors.u(row)(singular))
          val s = new BigDecimal(factors.singular(singular))
          val v = new BigDecimal(factors.v(col)(singular))
          val first = roundedMultiply(u, s, decimalDigitBound)
          val second = roundedMultiply(first, v, decimalDigitBound)
          reconstructed = roundedAdd(reconstructed, second, decimalDigitBound)
          singular += 1
        }
        val expected = new BigDecimal(source(row)(col))
        val residual = roundedAdd(reconstructed, expected.negate(), decimalDigitBound)
        sourceNormSquared = roundedAdd(sourceNormSquared,
          roundedMultiply(expected, expected, decimalDigitBound), decimalDigitBound)
        errorNormSquared = roundedAdd(errorNormSquared,
          roundedMultiply(residual, residual, decimalDigitBound), decimalDigitBound)
        col += 1
      }
      row += 1
    }
    if (sourceNormSquared.signum() == 0) errorNormSquared.signum() == 0
    else {
      val errorNorm = bounded(errorNormSquared.sqrt(Arithmetic), decimalDigitBound)
      val sourceNorm = bounded(sourceNormSquared.sqrt(Arithmetic), decimalDigitBound)
      val tolerance = bounded(sourceNorm.multiply(ResidualTolerance, Arithmetic), decimalDigitBound)
      errorNorm.compareTo(tolerance) <= 0
    }
  }

  private def exactMultiply(left: BigDecimal, right: BigDecimal, bound: Int): BigDecimal = {
    if (left.precision().toLong + right.precision().toLong > bound.toLong) {
      throw new LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded
    }
    bounded(left.multiply(right), bound)
  }

  private def exactAdd(left: BigDecimal, right: BigDecimal, bound: Int): BigDecimal = {
    val targetScale = math.max(left.scale().toLong, right.scale().toLong)
    val leftDigits = left.precision().toLong + targetScale - left.scale().toLong
    val rightDigits = right.precision().toLong + targetScale - right.scale().toLong
    if (math.max(leftDigits, rightDigits) + 1L > bound.toLong) {
      throw new LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded
    }
    bounded(left.add(right), bound)
  }

  private def roundedMultiply(left: BigDecimal, right: BigDecimal, bound: Int): BigDecimal = {
    val roundedLeft = left.round(Arithmetic)
    val roundedRight = right.round(Arithmetic)
    if (math.abs(roundedLeft.scale().toLong + roundedRight.scale().toLong) > bound.toLong) {
      throw new LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded
    }
    bounded(roundedLeft.multiply(roundedRight, Arithmetic), bound)
  }

  private def roundedAdd(left: BigDecimal, right: BigDecimal, bound: Int): BigDecimal = {
    val roundedLeft = left.round(Arithmetic)
    val roundedRight = right.round(Arithmetic)
    if (roundedLeft.signum() == 0) return bounded(roundedRight, bound)
    if (roundedRight.signum() == 0) return bounded(roundedLeft, bound)
    val leftExponent = roundedLeft.precision().toLong - roundedLeft.scale().toLong
    val rightExponent = roundedRight.precision().toLong - roundedRight.scale().toLong
    if (math.abs(leftExponent - rightExponent) > Arithmetic.getPrecision.toLong + 1L) {
      return if (leftExponent > rightExponent) bounded(roundedLeft, bound)
        else bounded(roundedRight, bound)
    }
    val targetScale = math.max(roundedLeft.scale().toLong, roundedRight.scale().toLong)
    val alignedDigits = math.max(roundedLeft.precision().toLong + targetScale - roundedLeft.scale().toLong,
      roundedRight.precision().toLong + targetScale - roundedRight.scale().toLong) + 1L
    if (targetScale > bound.toLong ||
      alignedDigits > 2L * bound.toLong + Arithmetic.getPrecision.toLong) {
      throw new LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded
    }
    bounded(roundedLeft.add(roundedRight, Arithmetic), bound)
  }

  private def bounded(value: BigDecimal, bound: Int): BigDecimal = {
    LocalEeMatrixOrthogonalBudget.requireDecimalWidth(value, bound)
    value
  }

  private def matrixData(
    matrix: org.apache.commons.math3.linear.RealMatrix, rows: Int, cols: Int
  ): Array[Array[Double]] = Array.tabulate(rows, cols)((row, col) => matrix.getEntry(row, col))

  private def factorOutput(
    factors: LocalEeMatrixOrthogonalFactors, spec: LocalEeMatrixValuesSpec.Value
  ): Array[Double] = {
    val rows = spec.rows
    val cols = spec.cols
    val p = math.min(rows, cols)
    val output = new Array[Double](spec.outputCells)
    var index = 0
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < p) {
        output(index) = factors.u(row)(col)
        index += 1
        col += 1
      }
      row += 1
    }
    row = 0
    while (row < p) {
      var col = 0
      while (col < p) {
        output(index) = if (row == col) factors.singular(row) else 0d
        index += 1
        col += 1
      }
      row += 1
    }
    row = 0
    while (row < cols) {
      var col = 0
      while (col < p) {
        output(index) = factors.v(row)(col)
        index += 1
        col += 1
      }
      row += 1
    }
    require(index == spec.outputCells, "SVD factor output count changed")
    output
  }
}

private[reduce] final case class LocalEeMatrixOrthogonalFactors(
  u: Array[Array[Double]], singular: Array[Double], v: Array[Array[Double]]
)
