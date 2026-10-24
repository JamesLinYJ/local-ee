package local.ee.reduce

import java.math.BigInteger

/** Exact bounded rank of dyadic binary64 endmember operators. */
private[reduce] object LocalEeSpectralUnmixRank {
  private val MaxIntermediateBits = 32768

  private final case class Dyadic(significand: BigInteger, exponent: Int) {
    def unary_- : Dyadic = Dyadic(significand.negate(), exponent)

    def +(other: Dyadic): Dyadic = {
      if (significand.signum() == 0) return other
      if (other.significand.signum() == 0) return this
      val common = math.min(exponent, other.exponent)
      normalize(significand.shiftLeft(exponent - common)
        .add(other.significand.shiftLeft(other.exponent - common)), common)
    }
  }

  def exactRank(matrix: Array[Array[Double]]): Option[Int] =
    rank(dyadicMatrix(matrix))

  /** Rank of the columns relative to the final component for a sum-to-one face. */
  def exactDifferenceRank(bandsByComponent: Array[Array[Double]]): Option[Int] = {
    val bands = bandsByComponent.length
    if (bands == 0 || bandsByComponent.exists(_.length == 0) ||
        bandsByComponent.exists(_.length != bandsByComponent(0).length)) return None
    val components = bandsByComponent(0).length
    if (components <= 1) return Some(0)
    val differences = Array.tabulate(bands, components - 1) { (band, component) =>
      fromDouble(bandsByComponent(band)(component)) + -fromDouble(bandsByComponent(band)(components - 1))
    }
    rank(differences)
  }

  /** Number of exponent buckets needed to represent every coefficient exactly. */
  def exponentSpan(matrix: Array[Array[Double]]): Long = {
    val values = matrix.iterator.flatMap(_.iterator).filter(_ != 0d).map { value =>
      fromDouble(value).exponent
    }.toVector
    if (values.isEmpty) 1L else values.max.toLong - values.min.toLong + 2L
  }

  /** Rank-work span also includes exact component contrasts used by simplex faces. */
  def operatorExponentSpan(matrix: Array[Array[Double]], sumToOne: Boolean): Long = {
    if (!sumToOne || matrix(0).length <= 1) return exponentSpan(matrix)
    // Matrix is components-by-bands: rank sees component differences within
    // each band, never differences between two band positions in one row.
    val differences = for {
      band <- matrix(0).indices
      left <- matrix.indices
      right <- 0 until left
      value = fromDouble(matrix(left)(band)) + -fromDouble(matrix(right)(band))
      if value.significand.signum() != 0
    } yield value.exponent
    if (differences.isEmpty) 1L else differences.max.toLong - differences.min.toLong + 2L
  }

  private def rank(source: Array[Array[Dyadic]]): Option[Int] = {
    if (source.isEmpty || source(0).isEmpty || source.exists(_.length != source(0).length)) return None
    val rows = source.length
    val cols = source(0).length
    val nonzero = source.iterator.flatMap(_.iterator).filter(_.significand.signum() != 0).toVector
    if (nonzero.isEmpty) return Some(0)
    val minimumExponent = nonzero.map(_.exponent).min
    val matrix = Array.tabulate(rows, cols) { (row, col) =>
      val value = source(row)(col)
      if (value.significand.signum() == 0) BigInteger.ZERO
      else bounded(value.significand.shiftLeft(value.exponent - minimumExponent))
    }
    try {
      val limit = math.min(rows, cols)
      var step = 0
      var previousPivot = BigInteger.ONE
      while (step < limit) {
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
              require(division(1).signum() == 0, "exact unmix rank division failed")
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

  private def dyadicMatrix(matrix: Array[Array[Double]]): Array[Array[Dyadic]] = {
    require(matrix.nonEmpty && matrix(0).nonEmpty && matrix.forall(_.length == matrix(0).length),
      "spectral unmix rank input must be a nonempty rectangular matrix")
    matrix.map(_.map(fromDouble))
  }

  private def fromDouble(value: Double): Dyadic = {
    require(value.isFinite, "spectral unmix rank input must be finite")
    val bits = java.lang.Double.doubleToRawLongBits(value)
    val fraction = bits & 0x000fffffffffffffL
    val exponentBits = ((bits >>> 52) & 0x7ffL).toInt
    val raw = if (exponentBits == 0) -1074 else exponentBits - 1023 - 52
    val significand = if (exponentBits == 0) fraction else (1L << 52) | fraction
    if (significand == 0L) Dyadic(BigInteger.ZERO, 0)
    else {
      val zeros = java.lang.Long.numberOfTrailingZeros(significand)
      val integer = BigInteger.valueOf(significand >>> zeros)
      Dyadic(if (bits < 0L) integer.negate() else integer, raw + zeros)
    }
  }

  private def normalize(value: BigInteger, exponent: Int): Dyadic = {
    if (value.signum() == 0) return Dyadic(BigInteger.ZERO, 0)
    val zeros = value.abs().getLowestSetBit
    Dyadic(value.shiftRight(zeros), Math.addExact(exponent, zeros))
  }

  private def bounded(value: BigInteger): BigInteger = {
    require(value.bitLength() <= MaxIntermediateBits,
      s"spectral unmix exact rank exceeded the $MaxIntermediateBits-bit bound")
    value
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
      val value = matrix(left)
      matrix(left) = matrix(right)
      matrix(right) = value
    }
  }

  private def swapColumns(matrix: Array[Array[BigInteger]], left: Int, right: Int): Unit = {
    if (left != right) {
      var row = 0
      while (row < matrix.length) {
        val value = matrix(row)(left)
        matrix(row)(left) = matrix(row)(right)
        matrix(row)(right) = value
        row += 1
      }
    }
  }
}
