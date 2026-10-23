package local.ee.reduce

import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import org.apache.commons.math3.linear.{Array2DRowRealMatrix, SingularValueDecomposition}
import java.math.{BigDecimal, MathContext, RoundingMode}

/** Actual per-pixel fixed-shape matrix solve, inverse and Moore-Penrose pseudoinverse. */
private[reduce] object LocalEeMatrixValuesNumeric {
  private val DivideContext = new MathContext(50, RoundingMode.HALF_EVEN)

  def applyTile(input: MultibandTile, spec: LocalEeMatrixValuesSpec.Value): MultibandTile = {
    require(input != null, "matrix values input tile must not be null")
    validateTileShape(input, spec, input.cols, input.rows)
    val cols = input.cols
    val rows = input.rows
    val copied = LocalEeReduceSupport.copyAsDouble(input, spec.inputBands, cols, rows)
    val sources = Array.tabulate(spec.inputBands) { index =>
      val band = copied.band(index)
      require(band.cellType == DoubleConstantNoDataCellType,
        "matrix values working bands must use Float64 with NaN NoData")
      band
    }
    val pixelCount = Math.multiplyExact(cols, rows)
    val output = Array.tabulate(spec.outputCells)(_ => Array.fill(pixelCount)(Double.NaN))
    val values = new Array[Double](spec.operands.length)
    var pixel = 0
    while (pixel < pixelCount) {
      val col = pixel % cols
      val row = pixel / cols
      var missing = false
      var operandIndex = 0
      while (operandIndex < spec.operands.length) {
        spec.operands(operandIndex) match {
          case LocalEeMatrixValuesSpec.Band(index) =>
            val value = sources(index).getDouble(col, row)
            values(operandIndex) = value
            require(!value.isInfinite, "matrix values input contains an infinite Float64 cell")
            if (value.isNaN) missing = true
          case LocalEeMatrixValuesSpec.Constant(bits) =>
            values(operandIndex) = java.lang.Double.longBitsToDouble(bits)
        }
        operandIndex += 1
      }
      if (!missing) {
        val result = evaluate(values, spec)
        if (result.forall(_.isFinite)) {
          var cell = 0
          while (cell < result.length) {
            output(cell)(pixel) = if (result(cell) == 0d) 0d else result(cell)
            cell += 1
          }
        }
      }
      pixel += 1
    }
    ArrayMultibandTile(output.map(values =>
      DoubleArrayTile(values, cols, rows, DoubleConstantNoDataCellType): Tile))
  }

  def validateTileShape(
    input: MultibandTile, spec: LocalEeMatrixValuesSpec.Value, expectedCols: Int, expectedRows: Int
  ): Unit = {
    require(input != null, "matrix values input tile must not be null")
    require(expectedCols > 0 && expectedRows > 0,
      "matrix values tile dimensions must be positive")
    require(input.bandCount == spec.inputBands,
      s"matrix values ${spec.op} requires exactly ${spec.inputBands} input band(s)")
    require(input.cols == expectedCols && input.rows == expectedRows,
      "matrix values tile dimensions changed within the input cube")
  }

  private def evaluate(values: Array[Double], spec: LocalEeMatrixValuesSpec.Value): Array[Double] = {
    if (spec.op == "cholesky" || spec.op == "lu") {
      LocalEeMatrixFactorization.evaluate(values, spec)
    } else {
      evaluateSvd(values, spec)
    }
  }

  private def evaluateSvd(values: Array[Double], spec: LocalEeMatrixValuesSpec.Value): Array[Double] = {
    val matrixCells = Math.multiplyExact(spec.rows, spec.cols)
    val matrix = new Array[Double](matrixCells)
    var matrixScale = 0d
    var index = 0
    while (index < matrixCells) {
      val value = values(index)
      matrix(index) = value
      matrixScale = math.max(matrixScale, math.abs(value))
      index += 1
    }
    if (matrixScale == 0d) {
      return if (spec.op == "inverse") Array.fill(spec.outputCells)(Double.NaN)
        else new Array[Double](spec.outputCells)
    }

    val scaled = Array.ofDim[Double](spec.rows, spec.cols)
    var row = 0
    while (row < spec.rows) {
      var col = 0
      while (col < spec.cols) {
        // Entries lost during this normalization are far below the explicit
        // relative numerical-rank cutoff applied to the scaled matrix.
        scaled(row)(col) = matrix(row * spec.cols + col) / matrixScale
        col += 1
      }
      row += 1
    }
    val decomposition = new SingularValueDecomposition(new Array2DRowRealMatrix(scaled, false))
    val singularValues = decomposition.getSingularValues
    // Use Commons Math 3.6.1's documented numerical-rank threshold and operation order.
    // This is a local stability policy, not a claim of Google numerical parity.
    val rank = decomposition.getRank
    if (spec.op == "inverse" && rank < spec.cols) return Array.fill(spec.outputCells)(Double.NaN)
    if (rank == 0) return new Array[Double](spec.outputCells)

    val normalizedPseudo = normalizedPseudoinverse(spec, decomposition, singularValues, rank)
    if (spec.op == "solve") solve(values, matrix, spec, normalizedPseudo, matrixScale, rank)
    else rescalePseudoinverse(normalizedPseudo, spec, matrixScale)
  }

  private def solve(
    values: Array[Double], matrix: Array[Double], spec: LocalEeMatrixValuesSpec.Value,
    normalizedPseudo: Array[Double], matrixScale: Double, rank: Int
  ): Array[Double] = {
    val rhsOffset = Math.multiplyExact(spec.rows, spec.cols)
    val matrixScaleDecimal = new BigDecimal(matrixScale)
    val anchor = if (spec.rows >= spec.cols && rank == spec.cols) constantColumn(matrix, spec) else None
    val output = new Array[Double](spec.outputCells)
    var outputRow = 0
    while (outputRow < spec.cols) {
      var rhs = 0
      while (rhs < spec.rhsCols) {
        // Exact binary64 BigDecimal inputs retain subnormal RHS cells even when a
        // different RHS cell is near Double.MaxValue. Full-rank exact constant columns
        // also center each RHS before the dot, then restore the anchor in one division.
        var dot = BigDecimal.ZERO
        val anchorValue = anchor.map(_ => new BigDecimal(values(rhsOffset + rhs)))
        var inputRow = 0
        while (inputRow < spec.rows) {
          val coefficient = normalizedPseudo(outputRow * spec.rows + inputRow)
          val rhsValue = values(rhsOffset + inputRow * spec.rhsCols + rhs)
          val rhsDecimal = new BigDecimal(rhsValue)
          val centered = anchorValue match {
            case Some(base) => rhsDecimal.subtract(base)
            case None => rhsDecimal
          }
          dot = dot.add(new BigDecimal(coefficient).multiply(centered))
          inputRow += 1
        }
        val restored = anchor match {
          case Some((column, constant)) if outputRow == column =>
            val constantDecimal = new BigDecimal(constant)
            val numerator = dot.multiply(constantDecimal)
              .add(anchorValue.get.multiply(matrixScaleDecimal))
            val denominator = matrixScaleDecimal.multiply(constantDecimal)
            numerator.divide(denominator, DivideContext)
          case _ => dot.divide(matrixScaleDecimal, DivideContext)
        }
        output(outputRow * spec.rhsCols + rhs) = restored.doubleValue()
        rhs += 1
      }
      outputRow += 1
    }
    output
  }

  private def constantColumn(
    matrix: Array[Double], spec: LocalEeMatrixValuesSpec.Value
  ): Option[(Int, Double)] = {
    var col = 0
    while (col < spec.cols) {
      val value = matrix(col)
      if (value != 0d) {
        var row = 1
        var constant = true
        while (row < spec.rows && constant) {
          constant = matrix(row * spec.cols + col) == value
          row += 1
        }
        if (constant) return Some((col, value))
      }
      col += 1
    }
    None
  }

  private def normalizedPseudoinverse(
    spec: LocalEeMatrixValuesSpec.Value, decomposition: SingularValueDecomposition,
    singular: Array[Double], rank: Int
  ): Array[Double] = {
    val u = decomposition.getU
    val v = decomposition.getV
    val output = new Array[Double](Math.multiplyExact(spec.cols, spec.rows))
    val compensation = new Array[Double](output.length)
    var singularIndex = 0
    while (singularIndex < rank) {
      var row = 0
      while (row < spec.cols) {
        var col = 0
        while (col < spec.rows) {
          val outputIndex = row * spec.rows + col
          // Divide before multiplying: the singular cutoff bounds 1/sigma, while
          // V*U can underflow even when (V/sigma)*U is representable.
          val term = (v.getEntry(row, singularIndex) / singular(singularIndex)) *
            u.getEntry(col, singularIndex)
          val adjusted = term - compensation(outputIndex)
          val next = output(outputIndex) + adjusted
          compensation(outputIndex) = (next - output(outputIndex)) - adjusted
          output(outputIndex) = next
          col += 1
        }
        row += 1
      }
      singularIndex += 1
    }
    output
  }

  private def rescalePseudoinverse(
    normalizedPseudo: Array[Double], spec: LocalEeMatrixValuesSpec.Value, matrixScale: Double
  ): Array[Double] = {
    val output = new Array[Double](spec.outputCells)
    var index = 0
    while (index < output.length) {
      output(index) = scaleByRatio(normalizedPseudo(index), 1d, matrixScale)
      index += 1
    }
    output
  }

  /** Compute value * numerator / denominator without forming an overflowing ratio. */
  private def scaleByRatio(value: Double, numerator: Double, denominator: Double): Double = {
    if (value == 0d) return 0d
    if (!value.isFinite) return value
    val (valueMantissa, valueExponent) = normalizedParts(math.abs(value))
    val (numeratorMantissa, numeratorExponent) = normalizedParts(numerator)
    val (denominatorMantissa, denominatorExponent) = normalizedParts(denominator)
    var mantissa = valueMantissa * numeratorMantissa / denominatorMantissa
    var exponent = valueExponent + numeratorExponent - denominatorExponent
    while (mantissa >= 2d) {
      mantissa *= 0.5d
      exponent += 1
    }
    while (mantissa < 1d) {
      mantissa *= 2d
      exponent -= 1
    }
    val result = Math.scalb(mantissa, exponent)
    if (result == 0d) 0d else if (value < 0d) -result else result
  }

  private def normalizedParts(value: Double): (Double, Int) = {
    require(value > 0d && value.isFinite, "matrix values scale factors must be positive and finite")
    var exponent = Math.getExponent(value)
    var mantissa = Math.scalb(value, -exponent)
    if (mantissa < 1d) {
      val adjustment = Math.getExponent(mantissa)
      exponent += adjustment
      mantissa = Math.scalb(mantissa, -adjustment)
    }
    (mantissa, exponent)
  }
}
