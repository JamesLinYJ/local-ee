package local.ee.reduce

import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import java.math.{BigDecimal, MathContext, RoundingMode}

/** Actual bounded Float64 per-pixel spectral least-squares evaluation. */
private[reduce] object LocalEeSpectralUnmixNumeric {
  private val Arithmetic = new MathContext(80, RoundingMode.HALF_EVEN)
  private val Epsilon = Math.ulp(1d)
  private val Zero = BigDecimal.ZERO
  private val One = BigDecimal.ONE
  private val DecimalAnchorError = new BigDecimal("1e-75")
  private val MaximumRelativeCoefficientError = new BigDecimal("1e-8")

  private final case class Candidate(
    active: Array[Int], coefficients: Array[BigDecimal], squaredResidual: BigDecimal,
    squaredNorm: BigDecimal, coefficientError: BigDecimal, scoreError: BigDecimal,
    normError: BigDecimal
  )

  def validateTileShape(
    input: MultibandTile, spec: LocalEeSpectralUnmixSpec.Value,
    expectedCols: Int, expectedRows: Int
  ): Unit = {
    require(input != null, "spectral unmix input tile must not be null")
    require(expectedCols > 0 && expectedRows > 0,
      "spectral unmix tile dimensions must be positive")
    require(input.bandCount == spec.inputBands,
      s"local_ee_unmix requires exactly ${spec.inputBands} input bands")
    require(input.cols == expectedCols && input.rows == expectedRows,
      "spectral unmix tile dimensions changed within the input cube")
  }

  def applyTile(
    input: MultibandTile, spec: LocalEeSpectralUnmixSpec.Value,
    plan: LocalEeSpectralUnmixSolver.Plan
  ): MultibandTile = {
    validateTileShape(input, spec, input.cols, input.rows)
    val copied = LocalEeReduceSupport.copyAsDouble(input, spec.inputBands, input.cols, input.rows)
    val pixelCount = Math.multiplyExact(input.cols, input.rows)
    val output = Array.fill(spec.components)(Array.fill(pixelCount)(Double.NaN))
    val spectrum = new Array[Double](spec.inputBands)
    var pixel = 0
    while (pixel < pixelCount) {
      var band = 0
      var missing = false
      while (band < spec.inputBands) {
        val value = copied.band(band).getDouble(pixel % input.cols, pixel / input.cols)
        require(!value.isInfinite, "spectral unmix input contains an infinite Float64 cell")
        spectrum(band) = value
        if (value.isNaN) missing = true
        band += 1
      }
      if (!missing) {
        solvePixel(spectrum, plan).foreach { coefficients =>
          var component = 0
          while (component < coefficients.length) {
            output(component)(pixel) = if (coefficients(component) == 0d) 0d else coefficients(component)
            component += 1
          }
        }
      }
      pixel += 1
    }
    ArrayMultibandTile(output.map(values =>
      DoubleArrayTile(values, input.cols, input.rows, DoubleConstantNoDataCellType): Tile))
  }

  private def solvePixel(
    spectrum: Array[Double], plan: LocalEeSpectralUnmixSolver.Plan
  ): Option[Array[Double]] = {
    val candidates = plan.faces.flatMap(face => candidate(spectrum, face, plan))
    require(candidates.nonEmpty, "spectral unmix solver found no feasible candidate face")
    val minimumResidual = candidates.reduceLeft { (left, right) =>
      if (left.squaredResidual.compareTo(right.squaredResidual) <= 0) left else right
    }
    val tied = candidates.filter { value =>
      value.squaredResidual.subtract(minimumResidual.squaredResidual).abs()
        .compareTo(add(value.scoreError, minimumResidual.scoreError)) <= 0
    }
    val orderedByNorm = tied.sortWith((left, right) =>
      left.squaredNorm.compareTo(right.squaredNorm) < 0)
    val best = orderedByNorm.reduceLeft { (left, right) =>
      compareMinimumNorm(left, right)
    }
    require(validateKkt(spectrum, best.coefficients, plan, best.coefficientError, Array.fill(plan.matrix.length)(Zero)),
      "spectral unmix pre-round candidate failed independent residual/KKT validation")
    val output = best.coefficients.map(_.doubleValue())
    if (output.exists(value => !value.isFinite)) return None
    if (plan.sumToOne) {
      val lastActive = best.active.last
      var prefix = 0d
      var position = 0
      while (position < best.active.length - 1) {
        prefix += output(best.active(position))
        position += 1
      }
      output(lastActive) = 1d - prefix
    }
    if (output.exists(value => !value.isFinite) ||
        (plan.nonNegative && output.exists(_ < 0d))) return None
    val rounded = output.map(exact)
    val roundingDelta = Array.tabulate(output.length)(index =>
      rounded(index).subtract(best.coefficients(index), Arithmetic))
    require(validateKkt(spectrum, rounded, plan, best.coefficientError, roundingDelta),
      "spectral unmix rounded output failed independent residual/KKT validation")
    Some(output)
  }

  /** Do not hide a materially different norm behind an overlapping error interval. */
  private def compareMinimumNorm(left: Candidate, right: Candidate): Candidate = {
    val difference = right.squaredNorm.subtract(left.squaredNorm)
    val uncertainty = add(left.normError, right.normError)
    if (difference.signum() != 0 && difference.abs().compareTo(uncertainty) > 0) {
      if (difference.signum() > 0) left else right
    } else if (coefficientsIndistinguishable(left, right)) {
      lexicographicMinimum(left, right)
    } else {
      throw new IllegalArgumentException(
        "spectral unmix minimum-norm tie is unresolved within the local numerical error bound")
    }
  }

  private def coefficientsIndistinguishable(left: Candidate, right: Candidate): Boolean = {
    val uncertainty = add(left.coefficientError, right.coefficientError)
    left.coefficients.indices.forall(index =>
      left.coefficients(index).subtract(right.coefficients(index), Arithmetic).abs()
        .compareTo(uncertainty) <= 0)
  }

  private def lexicographicMinimum(left: Candidate, right: Candidate): Candidate =
    if (lexicographic(left.coefficients, right.coefficients) <= 0) left else right

  private def candidate(
    spectrum: Array[Double], face: LocalEeSpectralUnmixSolver.Face,
    plan: LocalEeSpectralUnmixSolver.Plan
  ): Option[Candidate] = {
    val active = face.active
    val local = if (face.sumToOne) face.anchor.clone() else Array.fill(active.length)(Zero)
    if (face.sumToOne) {
      var free = 0
      while (free < face.operator.length) {
        var dot = Zero
        var band = 0
        while (band < spectrum.length) {
          val centered = subtract(exact(spectrum(band)), face.offset(band))
          dot = add(dot, multiply(exact(face.operator(free)(band)), centered))
          band += 1
        }
        val coordinate = LocalEeSpectralUnmixSolver.divide(dot, face.scale)
        var component = 0
        while (component < active.length - 1) {
          local(component) = add(local(component),
            multiply(exact(face.basis(component)(free)), coordinate))
          component += 1
        }
        free += 1
      }
      if (local.nonEmpty) {
        var prefix = Zero
        var index = 0
        while (index < local.length - 1) { prefix = add(prefix, local(index)); index += 1 }
        local(local.length - 1) = subtract(One, prefix)
      }
    } else {
      var component = 0
      while (component < active.length) {
        var dot = Zero
        var band = 0
        while (band < spectrum.length) {
          dot = add(dot, multiply(exact(face.operator(component)(band)), exact(spectrum(band))))
          band += 1
        }
        local(component) = LocalEeSpectralUnmixSolver.divide(dot, face.scale)
        component += 1
      }
    }
    val coefficients = Array.fill(plan.matrix.length)(Zero)
    var index = 0
    while (index < active.length) { coefficients(active(index)) = local(index); index += 1 }
    val coefficientError = coefficientErrorBound(spectrum, face, plan)
    val coefficientScale = if (plan.sumToOne && plan.nonNegative) One else
      coefficients.foldLeft(One) { (maximum, value) => maximum.max(value.abs()) }
    require(coefficientError.compareTo(
      multiply(MaximumRelativeCoefficientError, coefficientScale)) <= 0,
      "spectral unmix coefficient uncertainty exceeds the local 1e-8 relative limit")
    if (plan.nonNegative && local.exists(_.signum() < 0)) return None
    val residual = residuals(spectrum, coefficients, plan.matrix)
    var squaredResidual = Zero
    var maxResidual = Zero
    residual.foreach { value =>
      squaredResidual = add(squaredResidual, multiply(value, value))
      if (value.abs().compareTo(maxResidual) > 0) maxResidual = value.abs()
    }
    var squaredNorm = Zero
    var normL1 = Zero
    coefficients.foreach { value =>
      squaredNorm = add(squaredNorm, multiply(value, value))
      normL1 = add(normL1, value.abs())
    }
    val maxResidualError = maximumResidualError(plan, coefficientError)
    val scoreError = multiply(BigDecimal.valueOf(spectrum.length.toLong),
      add(multiply(BigDecimal.valueOf(2L), multiply(maxResidual, maxResidualError)),
        multiply(maxResidualError, maxResidualError)))
    val normError = add(multiply(BigDecimal.valueOf(2L), multiply(normL1, coefficientError)),
      multiply(BigDecimal.valueOf(coefficients.length.toLong), multiply(coefficientError, coefficientError)))
    Some(Candidate(active, coefficients, squaredResidual, squaredNorm,
      coefficientError, scoreError, normError))
  }

  private def coefficientErrorBound(
    spectrum: Array[Double], face: LocalEeSpectralUnmixSolver.Face,
    plan: LocalEeSpectralUnmixSolver.Plan
  ): BigDecimal = {
    if (face.exactRank == 0) return DecimalAnchorError
    var rhsRatio = Zero
    var band = 0
    while (band < spectrum.length) {
      val rhs = if (face.sumToOne) subtract(exact(spectrum(band)), face.offset(band))
        else exact(spectrum(band))
      val ratio = rhs.abs().divide(face.scale, Arithmetic)
      if (ratio.compareTo(rhsRatio) > 0) rhsRatio = ratio
      band += 1
    }
    val coefficientScale = One.max(rhsRatio)
    val factor = 64d * (spectrum.length + plan.matrix.length + 1d) * Epsilon *
      face.conditionFactor
    val numerical = new BigDecimal(factor, Arithmetic).multiply(coefficientScale, Arithmetic)
    // A free-coordinate error affects at most eight output coefficients.
    numerical.multiply(BigDecimal.valueOf(plan.matrix.length.toLong), Arithmetic)
  }

  private def maximumResidualError(
    plan: LocalEeSpectralUnmixSolver.Plan, coefficientError: BigDecimal
  ): BigDecimal = {
    var maximum = Zero
    var band = 0
    while (band < plan.matrix(0).length) {
      var total = Zero
      var component = 0
      while (component < plan.matrix.length) {
        val coefficient = operatorCoefficient(plan.matrix, component, band, plan.sumToOne)
        total = add(total, multiply(coefficient.abs(), coefficientError))
        component += 1
      }
      if (total.compareTo(maximum) > 0) maximum = total
      band += 1
    }
    maximum
  }

  /** Independent KKT check, with an SVD forward-error bound and measured output rounding. */
  private def validateKkt(
    spectrum: Array[Double], coefficients: Array[BigDecimal],
    plan: LocalEeSpectralUnmixSolver.Plan, coefficientError: BigDecimal,
    roundingDelta: Array[BigDecimal]
  ): Boolean = {
    if (plan.sumToOne) {
      var sum = Zero
      coefficients.foreach(value => sum = add(sum, value))
      val sumError = new BigDecimal(2d * Epsilon * plan.matrix.length.toDouble, Arithmetic)
      if (subtract(sum, One).abs().compareTo(sumError) > 0) return false
    }
    val residual = residuals(spectrum, coefficients, plan.matrix)
    val gradients = Array.fill(plan.matrix.length)(Zero)
    var component = 0
    while (component < gradients.length) {
      var gradient = Zero
      var band = 0
      while (band < spectrum.length) {
        gradient = add(gradient, multiply(
          operatorCoefficient(plan.matrix, component, band, plan.sumToOne), residual(band)))
        band += 1
      }
      gradients(component) = gradient
      component += 1
    }
    val solverTolerance = gradientPerturbationBound(plan.matrix, plan.sumToOne, coefficientError)
    val roundingTolerance = outputRoundingBound(plan.matrix, plan.sumToOne, roundingDelta)
    val tolerance = add(solverTolerance, roundingTolerance)
    val active = if (plan.nonNegative) {
      coefficients.indices.filter(index => coefficients(index).signum() > 0).toArray
    } else coefficients.indices.toArray
    if (plan.sumToOne) {
      if (active.isEmpty) return false
      var mean = Zero
      active.foreach(index => mean = add(mean, gradients(index)))
      val lambda = mean.divide(BigDecimal.valueOf(active.length.toLong), Arithmetic)
      if (active.exists(index => subtract(gradients(index), lambda).abs().compareTo(tolerance) > 0)) return false
      if (plan.nonNegative) {
        val activeSet = active.toSet
        if (gradients.indices.exists(index => !activeSet(index) &&
            subtract(gradients(index), lambda).compareTo(tolerance.negate()) < 0)) return false
      }
      true
    } else if (plan.nonNegative) {
      val activeSet = active.toSet
      active.forall(index => gradients(index).abs().compareTo(tolerance) <= 0) &&
        gradients.indices.forall(index => activeSet(index) ||
          gradients(index).compareTo(tolerance.negate()) >= 0)
    } else gradients.forall(_.abs().compareTo(tolerance) <= 0)
  }

  private def gradientPerturbationBound(
    matrix: Array[Array[Double]], sumToOne: Boolean, coefficientError: BigDecimal
  ): BigDecimal = {
    var maximum = Zero
    var component = 0
    while (component < matrix.length) {
      var total = Zero
      var band = 0
      while (band < matrix(0).length) {
        var rowNorm = Zero
        var row = 0
        while (row < matrix.length) {
          rowNorm = add(rowNorm, operatorCoefficient(matrix, row, band, sumToOne).abs())
          row += 1
        }
        total = add(total, multiply(operatorCoefficient(matrix, component, band, sumToOne).abs(), rowNorm))
        band += 1
      }
      total = multiply(total, coefficientError)
      if (total.compareTo(maximum) > 0) maximum = total
      component += 1
    }
    maximum
  }

  private def outputRoundingBound(
    matrix: Array[Array[Double]], sumToOne: Boolean, delta: Array[BigDecimal]
  ): BigDecimal = {
    var maximum = Zero
    var component = 0
    while (component < matrix.length) {
      var total = Zero
      var band = 0
      while (band < matrix(0).length) {
        var residualError = Zero
        var row = 0
        while (row < matrix.length) {
          residualError = add(residualError,
            multiply(exact(matrix(row)(band)).abs(), delta(row).abs()))
          row += 1
        }
        total = add(total, multiply(
          operatorCoefficient(matrix, component, band, sumToOne).abs(), residualError))
        band += 1
      }
      if (total.compareTo(maximum) > 0) maximum = total
      component += 1
    }
    maximum
  }

  private def operatorCoefficient(
    matrix: Array[Array[Double]], component: Int, band: Int, sumToOne: Boolean
  ): BigDecimal = {
    val value = exact(matrix(component)(band))
    if (sumToOne) subtract(value, exact(matrix(0)(band))) else value
  }

  private def residuals(
    spectrum: Array[Double], coefficients: Array[BigDecimal], matrix: Array[Array[Double]]
  ): Array[BigDecimal] = Array.tabulate(spectrum.length) { band =>
    var coefficientSum = Zero
    coefficients.foreach(value => coefficientSum = add(coefficientSum, value))
    val reference = exact(matrix(0)(band))
    var predicted = multiply(reference, coefficientSum)
    var component = 1
    while (component < coefficients.length) {
      val contrast = subtract(exact(matrix(component)(band)), reference)
      predicted = add(predicted, multiply(contrast, coefficients(component)))
      component += 1
    }
    subtract(predicted, exact(spectrum(band)))
  }

  private def lexicographic(left: Array[BigDecimal], right: Array[BigDecimal]): Int = {
    var index = 0
    while (index < left.length) {
      val item = left(index).compareTo(right(index))
      if (item != 0) return item
      index += 1
    }
    0
  }

  private def add(left: BigDecimal, right: BigDecimal): BigDecimal =
    left.add(right, Arithmetic)
  private def subtract(left: BigDecimal, right: BigDecimal): BigDecimal =
    left.subtract(right, Arithmetic)
  private def multiply(left: BigDecimal, right: BigDecimal): BigDecimal =
    left.multiply(right, Arithmetic)
  private def exact(value: Double): BigDecimal = new BigDecimal(value, Arithmetic)
}
