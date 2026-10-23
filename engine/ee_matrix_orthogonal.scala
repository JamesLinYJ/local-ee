package local.ee.reduce

import java.math.BigDecimal

/** Compact per-pixel QR and SVD factors, emitted by the shared matrix-values producer. */
private[reduce] object LocalEeMatrixOrthogonal {
  def evaluate(values: Array[Double], spec: LocalEeMatrixValuesSpec.Value): Array[Double] = {
    require(values != null && values.length == Math.multiplyExact(spec.rows, spec.cols),
      "orthogonal matrix values have an invalid input shape")
    val matrix = Array.ofDim[Double](spec.rows, spec.cols)
    var index = 0
    while (index < values.length) {
      matrix(index / spec.cols)(index % spec.cols) = values(index)
      index += 1
    }
    val envelope = LocalEeMatrixOrthogonalBudget.envelopeForValues(values)
    val decimalDigits = LocalEeMatrixOrthogonalBudget.decimalDigitLimit(spec, envelope)
    if (spec.op == "qr") qr(matrix, spec, decimalDigits)
    else LocalEeMatrixSvdNative.evaluate(matrix, spec, decimalDigits)
  }

  private def qr(
    source: Array[Array[Double]], spec: LocalEeMatrixValuesSpec.Value, decimalDigitBound: Int
  ): Array[Double] = {
    try qrBounded(source, spec, decimalDigitBound)
    catch { case _: LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded => noData(spec) }
  }

  private def qrBounded(
    source: Array[Array[Double]], spec: LocalEeMatrixValuesSpec.Value, decimalDigitBound: Int
  ): Array[Double] = {
    val rows = spec.rows
    val cols = spec.cols
    val p = math.min(rows, cols)
    val r = source.map(_.clone())
    val reflectors = Vector.newBuilder[(Int, Array[Double], Double)]
    var pivot = 0
    while (pivot < p) {
      var norm = 0d
      var row = pivot
      while (row < rows) {
        norm = java.lang.Math.hypot(norm, r(row)(pivot))
        row += 1
      }
      if (!norm.isFinite) return noData(spec)
      if (norm != 0d) {
        val vector = new Array[Double](rows - pivot)
        row = pivot
        while (row < rows) {
          vector(row - pivot) = r(row)(pivot) / norm
          row += 1
        }
        vector(0) += java.lang.Math.copySign(1d, r(pivot)(pivot))
        var vectorNormSquared = 0d
        var item = 0
        while (item < vector.length) {
          vectorNormSquared += vector(item) * vector(item)
          item += 1
        }
        val beta = 2d / vectorNormSquared
        if (!beta.isFinite || beta <= 0d) return noData(spec)
        reflectors += ((pivot, vector, beta))
        var col = pivot + 1
        while (col < cols) {
          val dot = exactDot(vector, r, pivot, col, decimalDigitBound)
          row = pivot
          while (row < rows) {
            val current = new BigDecimal(r(row)(col))
            val update = exactMultiply(exactMultiply(new BigDecimal(beta),
              new BigDecimal(vector(row - pivot)), decimalDigitBound), dot, decimalDigitBound)
            val next = exactAdd(current, update.negate(), decimalDigitBound).doubleValue()
            if (!next.isFinite) return noData(spec)
            r(row)(col) = if (next == 0d) 0d else next
            row += 1
          }
          col += 1
        }
        r(pivot)(pivot) = -java.lang.Math.copySign(norm, r(pivot)(pivot))
        row = pivot + 1
        while (row < rows) {
          r(row)(pivot) = 0d
          row += 1
        }
      }
      pivot += 1
    }

    // Commons Math's QR stores full square Q and squares raw column entries. This
    // reflector path uses hypot norms and exact-decimal dot/update accumulation.
    val q = Array.tabulate(rows, rows)((row, col) => if (row == col) 1d else 0d)
    reflectors.result().foreach { case (start, vector, beta) =>
      var row = 0
      while (row < rows) {
        val dot = exactRowDot(q(row), start, vector, decimalDigitBound)
        var item = 0
        while (item < vector.length) {
          val current = new BigDecimal(q(row)(start + item))
          val update = exactMultiply(exactMultiply(new BigDecimal(beta), dot, decimalDigitBound),
            new BigDecimal(vector(item)), decimalDigitBound)
          val next = exactAdd(current, update.negate(), decimalDigitBound).doubleValue()
          if (!next.isFinite) return noData(spec)
          q(row)(start + item) = if (next == 0d) 0d else next
          item += 1
        }
        row += 1
      }
    }

    val output = new Array[Double](spec.outputCells)
    var outputIndex = 0
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < p) {
        output(outputIndex) = q(row)(col)
        outputIndex += 1
        col += 1
      }
      row += 1
    }
    row = 0
    while (row < p) {
      var col = 0
      while (col < cols) {
        output(outputIndex) = r(row)(col)
        outputIndex += 1
        col += 1
      }
      row += 1
    }
    require(outputIndex == spec.outputCells, "QR factor output count changed")
    output
  }

  private def exactDot(
    vector: Array[Double], matrix: Array[Array[Double]], start: Int, col: Int, bound: Int
  ): BigDecimal = {
    var dot = BigDecimal.ZERO
    var index = 0
    while (index < vector.length) {
      val product = exactMultiply(new BigDecimal(vector(index)),
        new BigDecimal(matrix(start + index)(col)), bound)
      dot = exactAdd(dot, product, bound)
      index += 1
    }
    dot
  }

  private def exactRowDot(
    row: Array[Double], start: Int, vector: Array[Double], bound: Int
  ): BigDecimal = {
    var dot = BigDecimal.ZERO
    var index = 0
    while (index < vector.length) {
      val product = exactMultiply(new BigDecimal(row(start + index)),
        new BigDecimal(vector(index)), bound)
      dot = exactAdd(dot, product, bound)
      index += 1
    }
    dot
  }

  private def exactMultiply(left: BigDecimal, right: BigDecimal, bound: Int): BigDecimal = {
    val scale = left.scale().toLong + right.scale().toLong
    if (left.precision().toLong + right.precision().toLong > bound.toLong ||
      math.abs(scale) > bound.toLong) {
      throw new LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded
    }
    val result = left.multiply(right)
    LocalEeMatrixOrthogonalBudget.requireDecimalWidth(result, bound)
    result
  }

  private def exactAdd(left: BigDecimal, right: BigDecimal, bound: Int): BigDecimal = {
    val targetScale = math.max(left.scale().toLong, right.scale().toLong)
    val alignedDigits = math.max(left.precision().toLong + targetScale - left.scale().toLong,
      right.precision().toLong + targetScale - right.scale().toLong) + 1L
    if (targetScale > bound.toLong || alignedDigits > bound.toLong) {
      throw new LocalEeMatrixOrthogonalBudget.DecimalEnvelopeExceeded
    }
    val result = left.add(right)
    LocalEeMatrixOrthogonalBudget.requireDecimalWidth(result, bound)
    result
  }

  private def noData(spec: LocalEeMatrixValuesSpec.Value): Array[Double] =
    Array.fill(spec.outputCells)(Double.NaN)
}
