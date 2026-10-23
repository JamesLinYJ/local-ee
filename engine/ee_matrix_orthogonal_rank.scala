package local.ee.reduce

import java.math.{BigDecimal, BigInteger, MathContext, RoundingMode}

/** Exact binary64 rank via Bareiss elimination and Gram spectral invariants on a common dyadic scale. */
private[reduce] object LocalEeMatrixOrthogonalRank {
  private val IntermediateBitBound = LocalEeMatrixFactorization.RationalBitBound.toInt
  private val RootContext = new MathContext(80, RoundingMode.HALF_EVEN)
  private val Two = BigInteger.valueOf(2L)

  final case class Dyadic(value: BigInteger, exponent: Long)
  private final case class Scaled(values: Array[Array[BigInteger]], exponent: Int)

  def exactRank(source: Array[Array[Double]]): Option[Int] = scaled(source).flatMap { input =>
    val matrix = input.values.map(_.clone())
    try {
      val rows = matrix.length
      val cols = matrix(0).length
      val p = math.min(rows, cols)
      var step = 0
      var previousPivot = BigInteger.ONE
      while (step < p) {
        val (pivotRow, pivotCol) = findPivot(matrix, step)
        if (pivotRow < 0) return Some(step)
        swapRows(matrix, step, pivotRow)
        swapColumns(matrix, step, pivotCol)
        val pivot = matrix(step)(step)
        var row = step + 1
        while (row < rows) {
          var col = step + 1
          while (col < cols) {
            val numerator = bounded(matrix(row)(col).multiply(pivot)
              .subtract(matrix(row)(step).multiply(matrix(step)(col))))
            val quotient = if (step == 0) numerator else {
              val division = numerator.divideAndRemainder(previousPivot)
              if (division(1).signum() != 0) return None
              division(0)
            }
            matrix(row)(col) = bounded(quotient)
            col += 1
          }
          matrix(row)(step) = BigInteger.ZERO
          row += 1
        }
        previousPivot = pivot
        step += 1
      }
      Some(step)
    } catch {
      case _: ArithmeticException => None
      case _: IllegalArgumentException => None
    }
  }

  /** Exact e_k(AᵀA), represented as integers times powers of two. */
  def gramCoefficients(source: Array[Array[Double]], maximumOrder: Int): Option[Vector[Dyadic]] = {
    require(maximumOrder > 0 && maximumOrder <= math.min(source.length, source(0).length))
    scaled(source).flatMap { input =>
      try {
        val rows = input.values.length
        val cols = input.values(0).length
        val p = math.min(rows, cols)
        val gram = Array.ofDim[BigInteger](p, p)
        var left = 0
        while (left < p) {
          var right = left
          while (right < p) {
            var dot = BigInteger.ZERO
            var row = 0
            val reduction = math.max(rows, cols)
            while (row < reduction) {
              val leftValue = if (rows >= cols) input.values(row)(left) else input.values(left)(row)
              val rightValue = if (rows >= cols) input.values(row)(right) else input.values(right)(row)
              dot = bounded(dot.add(leftValue.multiply(rightValue)))
              row += 1
            }
            gram(left)(right) = dot
            gram(right)(left) = dot
            right += 1
          }
          left += 1
        }

        val coefficients = Vector.newBuilder[Dyadic]
        var order = 1
        while (order <= maximumOrder) {
          var sum = BigInteger.ZERO
          combinations(p, order).foreach { selected =>
            val minor = Array.tabulate(order, order)((row, col) => gram(selected(row))(selected(col)))
            sum = bounded(sum.add(determinant(minor)))
          }
          val exponent = Math.multiplyExact(Math.multiplyExact(input.exponent.toLong, order.toLong), 2L)
          coefficients += Dyadic(sum, exponent)
          order += 1
        }
        Some(coefficients.result())
      } catch {
        case _: ArithmeticException => None
        case _: IllegalArgumentException => None
      }
    }
  }

  /** Convert an exact dyadic coefficient to a bounded-significand decimal value. */
  def toDecimal(value: Dyadic): BigDecimal = {
    require(value.value.signum() >= 0)
    val integer = new BigDecimal(value.value)
    val scale = value.exponent
    if (scale == 0L) integer
    else if (scale > 0L) {
      require(scale <= 10000L, "matrix SVD Gram exponent exceeds its fixed bound")
      integer.multiply(new BigDecimal(Two.pow(scale.toInt)), RootContext)
    } else {
      val power = Math.negateExact(scale)
      require(power <= 10000L, "matrix SVD Gram exponent exceeds its fixed bound")
      integer.multiply(new BigDecimal(BigInteger.valueOf(5L).pow(power.toInt), power.toInt), RootContext)
    }
  }

  private def scaled(source: Array[Array[Double]]): Option[Scaled] = {
    val rows = source.length
    if (rows == 0 || source(0).isEmpty || source.exists(_.length != source(0).length)) return None
    val cols = source(0).length
    val significands = Array.ofDim[BigInteger](rows, cols)
    val exponents = Array.ofDim[Int](rows, cols)
    var minimumExponent = Int.MaxValue
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        val value = source(row)(col)
        if (!value.isFinite) return None
        val bits = java.lang.Double.doubleToRawLongBits(value)
        val fraction = bits & 0x000fffffffffffffL
        val exponentBits = ((bits >>> 52) & 0x7ffL).toInt
        val significand = if (exponentBits == 0) fraction else (1L << 52) | fraction
        if (significand == 0L) {
          significands(row)(col) = BigInteger.ZERO
          exponents(row)(col) = 0
        } else {
          val rawExponent = if (exponentBits == 0) -1074 else exponentBits - 1023 - 52
          val trailingZeros = java.lang.Long.numberOfTrailingZeros(significand)
          val exponent = rawExponent + trailingZeros
          val reduced = BigInteger.valueOf(significand >>> trailingZeros)
          significands(row)(col) = if (bits < 0L) reduced.negate() else reduced
          exponents(row)(col) = exponent
          minimumExponent = math.min(minimumExponent, exponent)
        }
        col += 1
      }
      row += 1
    }
    if (minimumExponent == Int.MaxValue) {
      Some(Scaled(Array.fill(rows, cols)(BigInteger.ZERO), 0))
    } else {
      val matrix = Array.ofDim[BigInteger](rows, cols)
      row = 0
      while (row < rows) {
        var col = 0
        while (col < cols) {
          val significand = significands(row)(col)
          val shift = if (significand.signum() == 0) 0 else exponents(row)(col) - minimumExponent
          matrix(row)(col) = if (significand.signum() == 0) BigInteger.ZERO
            else bounded(significand.shiftLeft(shift))
          col += 1
        }
        row += 1
      }
      Some(Scaled(matrix, minimumExponent))
    }
  }

  private def determinant(matrix: Array[Array[BigInteger]]): BigInteger = {
    val order = matrix.length
    var result = BigInteger.ZERO
    val permutation = new Array[Int](order)
    val used = Array.fill(order)(false)
    def expand(row: Int, product: BigInteger, inversions: Int): Unit = {
      if (row == order) {
        result = bounded(if ((inversions & 1) == 0) result.add(product) else result.subtract(product))
      } else {
        var col = 0
        while (col < order) {
          if (!used(col)) {
            var prior = 0
            var greater = 0
            while (prior < row) {
              if (permutation(prior) > col) greater += 1
              prior += 1
            }
            used(col) = true
            permutation(row) = col
            expand(row + 1, bounded(product.multiply(matrix(row)(col))), inversions + greater)
            used(col) = false
          }
          col += 1
        }
      }
    }
    expand(0, BigInteger.ONE, 0)
    result
  }

  private def combinations(size: Int, count: Int): Vector[Array[Int]] = {
    val result = Vector.newBuilder[Array[Int]]
    val selected = new Array[Int](count)
    def visit(start: Int, depth: Int): Unit = {
      if (depth == count) result += selected.clone()
      else {
        var value = start
        while (value <= size - (count - depth)) {
          selected(depth) = value
          visit(value + 1, depth + 1)
          value += 1
        }
      }
    }
    visit(0, 0)
    result.result()
  }

  private def findPivot(matrix: Array[Array[BigInteger]], start: Int): (Int, Int) = {
    var row = start
    while (row < matrix.length) {
      var col = start
      while (col < matrix(0).length) {
        if (matrix(row)(col).signum() != 0) return (row, col)
        col += 1
      }
      row += 1
    }
    (-1, -1)
  }

  private def swapRows(matrix: Array[Array[BigInteger]], left: Int, right: Int): Unit = {
    if (left != right) {
      val swap = matrix(left)
      matrix(left) = matrix(right)
      matrix(right) = swap
    }
  }

  private def swapColumns(matrix: Array[Array[BigInteger]], left: Int, right: Int): Unit = {
    if (left != right) {
      var row = 0
      while (row < matrix.length) {
        val swap = matrix(row)(left)
        matrix(row)(left) = matrix(row)(right)
        matrix(row)(right) = swap
        row += 1
      }
    }
  }

  private def bounded(value: BigInteger): BigInteger = {
    require(value.bitLength <= IntermediateBitBound,
      s"matrix SVD exact intermediate exceeded the $IntermediateBitBound-bit bound")
    value
  }
}
