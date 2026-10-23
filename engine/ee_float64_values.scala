package local.ee.reduce

import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}

/** Closed Float64 raster-value operations added to the historical integer-values v1 SPI. */
private[reduce] object LocalEeFloat64Values {
  private[reduce] val OperationArities: Map[String, Int] = Map(
    "add" -> 2,
    "subtract" -> 2,
    "multiply" -> 2,
    "divide" -> 2,
    "power" -> 2,
    "mod" -> 2,
    "min2" -> 2,
    "max2" -> 2,
    "and" -> 2,
    "or" -> 2,
    "absolute" -> 1,
    "sqrt" -> 1,
    "log" -> 1,
    "log10" -> 1,
    "exp" -> 1,
    "round" -> 1,
    "floor" -> 1,
    "ceil" -> 1,
    "sin" -> 1,
    "cos" -> 1,
    "tan" -> 1,
    "not" -> 1
  )

  private val TranscendentalWork = 32L
  private val OperationWorkWeights: Map[String, Long] = Map(
    "add" -> 1L,
    "subtract" -> 1L,
    "multiply" -> 1L,
    "divide" -> 4L,
    "power" -> TranscendentalWork,
    "mod" -> 4L,
    "min2" -> 1L,
    "max2" -> 1L,
    "and" -> 1L,
    "or" -> 1L,
    "absolute" -> 1L,
    "sqrt" -> TranscendentalWork,
    "log" -> TranscendentalWork,
    "log10" -> TranscendentalWork,
    "exp" -> TranscendentalWork,
    "round" -> 4L,
    "floor" -> 4L,
    "ceil" -> 4L,
    "sin" -> TranscendentalWork,
    "cos" -> TranscendentalWork,
    "tan" -> TranscendentalWork,
    "not" -> 1L
  )

  def supports(operation: String): Boolean = OperationArities.contains(operation)

  def arity(operation: String): Option[Int] = OperationArities.get(operation)

  def workWeight(operation: String): Option[Long] = OperationArities.get(operation).map { _ =>
    OperationWorkWeights.getOrElse(operation,
      throw new IllegalStateException(s"Float64 value operation has no work weight: $operation"))
  }

  /** Read real cells as Float64, intersect masks, and map nonfinite results to NaN NoData. */
  def applyTile(input: MultibandTile, spec: LocalEeIntegerValuesSpec.Value): Tile = {
    val requiredBands = OperationArities.getOrElse(spec.op,
      throw new IllegalArgumentException(s"unsupported Float64 value operation: ${spec.op}"))
    require(input != null && input.cols > 0 && input.rows > 0,
      "Float64 value input tile dimensions must be positive")
    require(input.bandCount == spec.inputBands && spec.operands.length == requiredBands,
      s"Float64 value ${spec.op} requires exactly $requiredBands operands and ${spec.inputBands} band(s)")
    val cols = input.cols
    val rows = input.rows
    // The shared conversion reads each original cell type's getDouble mask directly, so
    // valid sentinel-like minima remain values and only actual NoData becomes NaN.
    val copied = LocalEeReduceSupport.copyAsDouble(input, spec.inputBands, cols, rows)
    val sources = Array.tabulate(spec.inputBands)(index => copied.band(index))
    val output = new Array[Double](Math.multiplyExact(cols, rows))
    val values = new Array[Double](2)
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        var valid = true
        var operandIndex = 0
        while (operandIndex < spec.operands.length) {
          spec.operands(operandIndex) match {
            case LocalEeIntegerValuesSpec.Band(index) =>
              val value = sources(index).getDouble(col, row)
              values(operandIndex) = value
              if (value.isNaN) valid = false
            case LocalEeIntegerValuesSpec.Constant(bits) =>
              values(operandIndex) = java.lang.Double.longBitsToDouble(bits)
          }
          operandIndex += 1
        }
        val index = row * cols + col
        if (!valid) output(index) = Double.NaN
        else {
          val result = applyValue(spec.op, values)
          output(index) = if (result.isFinite) result else Double.NaN
        }
        col += 1
      }
      row += 1
    }
    DoubleArrayTile(output, cols, rows, DoubleConstantNoDataCellType)
  }

  private def applyValue(operation: String, values: Array[Double]): Double = {
    val left = values(0)
    operation match {
      case "add" => left + values(1)
      case "subtract" => left - values(1)
      case "multiply" => left * values(1)
      case "divide" => if (values(1) == 0d) 0d else left / values(1)
      case "power" => java.lang.StrictMath.pow(left, values(1))
      case "mod" => left % values(1)
      case "min2" => java.lang.StrictMath.min(left, values(1))
      case "max2" => java.lang.StrictMath.max(left, values(1))
      case "and" => boolValue(isTrue(left) && isTrue(values(1)))
      case "or" => boolValue(isTrue(left) || isTrue(values(1)))
      case "absolute" => java.lang.StrictMath.abs(left)
      case "sqrt" => java.lang.StrictMath.sqrt(left)
      case "log" => java.lang.StrictMath.log(left)
      case "log10" => java.lang.StrictMath.log10(left)
      case "exp" => java.lang.StrictMath.exp(left)
      case "round" => roundTiesTowardPositiveInfinity(left)
      case "floor" => java.lang.StrictMath.floor(left)
      case "ceil" => java.lang.StrictMath.ceil(left)
      case "sin" => java.lang.StrictMath.sin(left)
      case "cos" => java.lang.StrictMath.cos(left)
      case "tan" => java.lang.StrictMath.tan(left)
      case "not" => boolValue(!isTrue(left))
      case unsupported => throw new IllegalArgumentException(s"unsupported Float64 value operation: $unsupported")
    }
  }

  private def isTrue(value: Double): Boolean = value != 0d

  private def boolValue(value: Boolean): Double = if (value) 1d else 0d

  /** Local ties-to-positive-infinity policy; Google half-value parity is unverified. */
  private def roundTiesTowardPositiveInfinity(value: Double): Double = {
    val integralThreshold = 4503599627370496d // 2^52: every finite binary64 here is integral.
    if (java.lang.StrictMath.abs(value) >= integralThreshold) value
    else {
      val lower = java.lang.StrictMath.floor(value)
      if (value - lower >= 0.5d) lower + 1d else lower
    }
  }
}
