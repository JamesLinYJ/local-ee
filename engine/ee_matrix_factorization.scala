package local.ee.reduce

import java.math.{BigDecimal, BigInteger, MathContext, RoundingMode}
import org.apache.commons.math3.fraction.BigFraction

/** Bounded original-scale Cholesky and partial-pivot LU kernels for matrix-values v1. */
private[reduce] object LocalEeMatrixFactorization {
  private val ArithmeticContext = new MathContext(50, RoundingMode.HALF_EVEN)
  val RationalBitBound = 32768L
  private val MaxFractionBits = RationalBitBound.toInt
  private val Zero = BigDecimal.ZERO
  private val One = BigDecimal.ONE

  def evaluate(values: Array[Double], spec: LocalEeMatrixValuesSpec.Value): Array[Double] = {
    if (spec.op == "lu") return lu(values, spec)
    val size = spec.rows
    val matrix = Array.ofDim[BigDecimal](size, size)
    var row = 0
    while (row < size) {
      var col = 0
      while (col < size) {
        val value = values(row * size + col)
        require(value.isFinite, "matrix values factorization requires finite input cells")
        matrix(row)(col) = new BigDecimal(value)
        col += 1
      }
      row += 1
    }
    cholesky(matrix, spec)
  }

  private def cholesky(
    matrix: Array[Array[BigDecimal]], spec: LocalEeMatrixValuesSpec.Value
  ): Array[Double] = {
    val size = spec.rows
    var row = 0
    while (row < size) {
      var col = row + 1
      while (col < size) {
        if (matrix(row)(col).compareTo(matrix(col)(row)) != 0) return masked(spec)
        col += 1
      }
      row += 1
    }

    val lower = Array.fill(size, size)(Zero)
    var pivot = 0
    while (pivot < size) {
      var residual = matrix(pivot)(pivot)
      var previous = 0
      while (previous < pivot) {
        residual = residual.subtract(lower(pivot)(previous).multiply(lower(pivot)(previous)))
        previous += 1
      }
      if (residual.signum() <= 0) return masked(spec)
      val diagonal = residual.sqrt(ArithmeticContext).doubleValue()
      if (!diagonal.isFinite || diagonal <= 0d) return masked(spec)
      // Subsequent exact residual sums use the binary64 value that will be emitted.
      lower(pivot)(pivot) = new BigDecimal(diagonal)

      row = pivot + 1
      while (row < size) {
        var offDiagonal = matrix(row)(pivot)
        previous = 0
        while (previous < pivot) {
          offDiagonal = offDiagonal.subtract(lower(row)(previous).multiply(lower(pivot)(previous)))
          previous += 1
        }
        val value = offDiagonal.divide(lower(pivot)(pivot), ArithmeticContext).doubleValue()
        if (!value.isFinite) return masked(spec)
        lower(row)(pivot) = new BigDecimal(value)
        row += 1
      }
      pivot += 1
    }
    flatten(lower)
  }

  private def lu(values: Array[Double], spec: LocalEeMatrixValuesSpec.Value): Array[Double] = {
    val size = spec.rows
    val upper = Array.ofDim[BigFraction](size, size)
    var row = 0
    while (row < size) {
      var col = 0
      while (col < size) {
        upper(row)(col) = exactFraction(values(row * size + col))
        col += 1
      }
      row += 1
    }
    val lower = Array.fill(size, size)(BigFraction.ZERO)
    val permutation = Array.tabulate(size)(identity)
    var index = 0
    while (index < size) {
      lower(index)(index) = BigFraction.ONE
      index += 1
    }

    var pivot = 0
    while (pivot < size) {
      var selected = pivot
      var selectedMagnitude = upper(pivot)(pivot).abs()
      var row = pivot + 1
      while (row < size) {
        val magnitude = upper(row)(pivot).abs()
        // Strict comparison keeps the first row when maximum magnitudes tie.
        if (magnitude.compareTo(selectedMagnitude) > 0) {
          selected = row
          selectedMagnitude = magnitude
        }
        row += 1
      }
      if (selectedMagnitude.compareTo(BigFraction.ZERO) == 0) return masked(spec)
      if (selected != pivot) {
        val upperRow = upper(pivot)
        upper(pivot) = upper(selected)
        upper(selected) = upperRow
        val permutationRow = permutation(pivot)
        permutation(pivot) = permutation(selected)
        permutation(selected) = permutationRow
        var previous = 0
        while (previous < pivot) {
          val lowerValue = lower(pivot)(previous)
          lower(pivot)(previous) = lower(selected)(previous)
          lower(selected)(previous) = lowerValue
          previous += 1
        }
      }

      row = pivot + 1
      while (row < size) {
        val factor = requireBounded(upper(row)(pivot).divide(upper(pivot)(pivot)))
        lower(row)(pivot) = factor
        var col = pivot + 1
        while (col < size) {
          val product = requireBounded(factor.multiply(upper(pivot)(col)))
          upper(row)(col) = requireBounded(upper(row)(col).subtract(product))
          col += 1
        }
        upper(row)(pivot) = BigFraction.ZERO
        row += 1
      }
      pivot += 1
    }

    val output = new Array[Double](spec.outputCells)
    appendFractions(output, 0, lower)
    appendFractions(output, size * size, upper)
    var rowIndex = 0
    while (rowIndex < size) {
      var col = 0
      while (col < size) {
        output(2 * size * size + rowIndex * size + col) =
          if (permutation(rowIndex) == col) 1d else 0d
        col += 1
      }
      rowIndex += 1
    }
    output
  }

  /** BigDecimal(double) is the exact terminating decimal expansion of the binary64 input. */
  private def exactFraction(value: Double): BigFraction = {
    if (value == 0d) return BigFraction.ZERO
    val exact = new BigDecimal(value)
    val unscaled = exact.unscaledValue()
    val scale = exact.scale()
    if (scale >= 0) requireBounded(new BigFraction(unscaled, BigInteger.TEN.pow(scale)))
    else requireBounded(new BigFraction(
      unscaled.multiply(BigInteger.TEN.pow(-scale)), BigInteger.ONE))
  }

  private def requireBounded(value: BigFraction): BigFraction = {
    require(value.getNumerator.bitLength <= MaxFractionBits &&
      value.getDenominator.bitLength <= MaxFractionBits,
      s"matrix values LU rational exceeded the $MaxFractionBits-bit bound")
    value
  }

  private def roundedDouble(value: BigFraction): Double =
    if (value.compareTo(BigFraction.ZERO) == 0) 0d
    else try LocalEeNeighborhoodExact.roundedRational(
      value.getNumerator.abs(), value.getDenominator, 0,
      value.getNumerator.signum() < 0, "LU factor")
    catch {
      case _: IllegalArgumentException => Double.NaN
    }

  private def appendFractions(
    output: Array[Double], offset: Int, values: Array[Array[BigFraction]]
  ): Unit = {
    var row = 0
    while (row < values.length) {
      var col = 0
      while (col < values.length) {
        // Convert each exact rational factor once, at the Float64 output boundary.
        output(offset + row * values.length + col) = roundedDouble(values(row)(col))
        col += 1
      }
      row += 1
    }
  }

  private def flatten(values: Array[Array[BigDecimal]]): Array[Double] = {
    val output = new Array[Double](values.length * values.length)
    append(output, 0, values)
    output
  }

  private def append(
    output: Array[Double], offset: Int, values: Array[Array[BigDecimal]]
  ): Unit = {
    var row = 0
    while (row < values.length) {
      var col = 0
      while (col < values.length) {
        output(offset + row * values.length + col) = values(row)(col).doubleValue()
        col += 1
      }
      row += 1
    }
  }

  private def masked(spec: LocalEeMatrixValuesSpec.Value): Array[Double] =
    Array.fill(spec.outputCells)(Double.NaN)
}
