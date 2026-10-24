package local.ee.reduce

import org.apache.commons.math3.linear.{Array2DRowRealMatrix, SingularValueDecomposition}
import java.math.{BigDecimal, MathContext, RoundingMode}

/** Bounded support-face operators for one fixed endmember matrix. */
private[reduce] object LocalEeSpectralUnmixSolver {
  private val Arithmetic = new MathContext(80, RoundingMode.HALF_EVEN)
  private val MinimumRelativeSingular = java.lang.Math.scalb(1d, -48)
  private val Zero = BigDecimal.ZERO
  private val One = BigDecimal.ONE

  final case class Face(
    active: Array[Int], basis: Array[Array[Double]], operator: Array[Array[Double]],
    scale: BigDecimal, offset: Array[BigDecimal], anchor: Array[BigDecimal],
    sumToOne: Boolean, exactRank: Int, conditionFactor: Double
  ) extends Serializable

  final case class Plan(
    matrix: Array[Array[Double]], faces: Vector[Face], sumToOne: Boolean,
    nonNegative: Boolean
  ) extends Serializable

  /** Construct all at-most-256 faces once, after the adapter has charged the plan. */
  def build(spec: LocalEeSpectralUnmixSpec.Value): Plan = {
    val matrix = spec.matrix
    val faces = supports(spec).map(active => buildFace(matrix, active, spec.sumToOne))
    Plan(matrix, faces, spec.sumToOne, spec.nonNegative)
  }

  private def supports(spec: LocalEeSpectralUnmixSpec.Value): Vector[Array[Int]] = {
    if (!spec.nonNegative) return Vector((0 until spec.components).toArray)
    val first = if (spec.sumToOne) 1 else 0
    (first until (1 << spec.components)).map { mask =>
      (0 until spec.components).filter(index => (mask & (1 << index)) != 0).toArray
    }.toVector
  }

  private def buildFace(
    matrix: Array[Array[Double]], active: Array[Int], sumToOne: Boolean
  ): Face = {
    val bands = matrix(0).length
    val count = active.length
    val basis = if (sumToOne) simplexNullspace(count) else identity(count)
    val free = if (count == 0) 0 else basis(0).length
    val source = Array.tabulate(bands, count)((band, column) => matrix(active(column))(band))
    val exactRank = if (count == 0) Some(0) else if (sumToOne) {
      LocalEeSpectralUnmixRank.exactDifferenceRank(source)
    } else LocalEeSpectralUnmixRank.exactRank(source)
    val rank = exactRank.getOrElse(throw new IllegalArgumentException(
      "spectral unmix exact rank exceeded its bounded dyadic envelope"))
    val anchor = if (sumToOne && count > 0) simplexAnchor(count) else Array.empty[BigDecimal]
    val offset = Array.fill(bands)(Zero)
    if (sumToOne && count > 0) {
      var band = 0
      while (band < bands) {
        // Start at one component and accumulate only exact contrasts. Shared
        // offsets therefore cancel before finite-precision anchor arithmetic.
        var total = exact(matrix(active.last)(band))
        var component = 0
        while (component < count - 1) {
          val contrast = subtract(exact(matrix(active(component))(band)),
            exact(matrix(active.last)(band)))
          total = add(total, multiply(contrast, anchor(component)))
          component += 1
        }
        offset(band) = total
        band += 1
      }
    }
    val scale = faceScale(matrix, active, sumToOne)
    val design = Array.ofDim[Double](bands, free)
    var band = 0
    while (band < bands) {
      var coordinate = 0
      while (coordinate < free) {
        var total = 0d
        var compensation = 0d
        val basisComponents = if (sumToOne) count - 1 else count
        var component = 0
        while (component < basisComponents) {
          val sourceValue = if (sumToOne) {
            exact(matrix(active(component))(band))
              .subtract(exact(matrix(active.last)(band)), Arithmetic)
          } else exact(matrix(active(component))(band))
          val normalized = sourceValue.divide(scale, Arithmetic).doubleValue()
          val term = normalized * basis(component)(coordinate)
          val adjusted = term - compensation
          val next = total + adjusted
          compensation = (next - total) - adjusted
          total = next
          component += 1
        }
        design(band)(coordinate) = total
        coordinate += 1
      }
      band += 1
    }
    val (operator, condition) = pseudoinverse(design, free, bands, rank)
    Face(active, basis, operator, scale, offset, anchor, sumToOne, rank, condition)
  }

  /** Simplex arithmetic removes the shared offset before normalizing or rotating. */
  private def faceScale(
    matrix: Array[Array[Double]], active: Array[Int], sumToOne: Boolean
  ): BigDecimal = {
    var maximum = Zero
    var band = 0
    while (band < matrix(0).length) {
      if (sumToOne) {
        var component = 0
        while (component < active.length - 1) {
          val difference = exact(matrix(active(component))(band))
            .subtract(exact(matrix(active.last)(band)), Arithmetic).abs()
          if (difference.compareTo(maximum) > 0) maximum = difference
          component += 1
        }
      } else {
        var component = 0
        while (component < active.length) {
          val value = exact(matrix(active(component))(band)).abs()
          if (value.compareTo(maximum) > 0) maximum = value
          component += 1
        }
      }
      band += 1
    }
    if (maximum.signum() == 0) One else maximum
  }

  private def simplexAnchor(size: Int): Array[BigDecimal] = {
    if (size == 1) return Array(One)
    val unit = One.divide(BigDecimal.valueOf(size.toLong), Arithmetic)
    val result = Array.fill(size)(unit)
    var prefix = Zero
    var index = 0
    while (index < size - 1) {
      prefix = add(prefix, result(index))
      index += 1
    }
    result(size - 1) = One.subtract(prefix, Arithmetic)
    result
  }

  private def pseudoinverse(
    design: Array[Array[Double]], columns: Int, rows: Int, exactRank: Int
  ): (Array[Array[Double]], Double) = {
    val result = Array.ofDim[Double](columns, rows)
    if (columns == 0 || exactRank == 0) return (result, 1d)
    val compensation = Array.ofDim[Double](columns, rows)
    val decomposition = new SingularValueDecomposition(new Array2DRowRealMatrix(design, false))
    val singular = decomposition.getSingularValues
    require(exactRank <= singular.length,
      "spectral unmix exact rank exceeds the fixed-face SVD dimensions")
    val smallest = singular(exactRank - 1)
    require(smallest.isFinite && smallest > 0d && singular(0).isFinite && singular(0) > 0d,
      "spectral unmix fixed-face rank is not representable by binary64 SVD")
    val condition = singular(0) / smallest
    require(condition.isFinite && smallest / singular(0) >= MinimumRelativeSingular,
      "spectral unmix fixed-face condition exceeds the local 2^48 limit")
    val u = decomposition.getU
    val v = decomposition.getV
    var component = 0
    while (component < exactRank) {
      var output = 0
      while (output < columns) {
        var input = 0
        while (input < rows) {
          val term = (v.getEntry(output, component) / singular(component)) *
            u.getEntry(input, component)
          val adjusted = term - compensation(output)(input)
          val next = result(output)(input) + adjusted
          compensation(output)(input) = (next - result(output)(input)) - adjusted
          result(output)(input) = next
          input += 1
        }
        output += 1
      }
      component += 1
    }
    (result, condition)
  }

  /** Helmert coordinates; candidate construction closes the final coefficient exactly. */
  private def simplexNullspace(size: Int): Array[Array[Double]] = {
    val result = Array.ofDim[Double](size, math.max(0, size - 1))
    var column = 0
    while (column < size - 1) {
      val positive = 1d / math.sqrt((column + 1d) * (column + 2d))
      var total = 0d
      var row = 0
      while (row <= column) {
        result(row)(column) = positive
        total += positive
        row += 1
      }
      result(column + 1)(column) = -total
      column += 1
    }
    result
  }

  private def identity(size: Int): Array[Array[Double]] = {
    val result = Array.ofDim[Double](size, size)
    var index = 0
    while (index < size) { result(index)(index) = 1d; index += 1 }
    result
  }

  private[reduce] def divide(value: BigDecimal, divisor: BigDecimal): BigDecimal =
    value.divide(divisor, Arithmetic)

  private[reduce] def add(left: BigDecimal, right: BigDecimal): BigDecimal =
    left.add(right, Arithmetic)

  private[reduce] def subtract(left: BigDecimal, right: BigDecimal): BigDecimal =
    left.subtract(right, Arithmetic)

  private[reduce] def multiply(left: BigDecimal, right: BigDecimal): BigDecimal =
    left.multiply(right, Arithmetic)

  private[reduce] def exact(value: Double): BigDecimal = new BigDecimal(value, Arithmetic)
}
