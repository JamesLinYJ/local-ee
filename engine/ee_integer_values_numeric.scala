package local.ee.reduce

import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}

/** Pixel kernels for integer-value operations and comparisons over physical Float64 cells. */
private[reduce] object LocalEeIntegerValuesNumeric {
  private val MaxSafeInteger = 9007199254740992L // 2^53
  private val MaxSafeIntegerDouble = MaxSafeInteger.toDouble
  private val MaxSafeIntegerBig = BigInt(1) << 53

  /** Validate/copy source cells to Float64 first, then evaluate only mask-valid operand tuples. */
  def applyTile(input: MultibandTile, spec: LocalEeIntegerValuesSpec.Value): Tile = {
    require(input != null, "integer values input tile must not be null")
    require(input.cols > 0 && input.rows > 0, "integer values tile dimensions must be positive")
    require(input.bandCount == spec.inputBands,
      s"integer values ${spec.op} requires exactly ${spec.inputBands} input band(s)")
    val cols = input.cols
    val rows = input.rows
    // The shared copy preserves the source mask as NaN while avoiding sentinel collisions
    // such as valid -128, -32768, and Int.MinValue cells.
    val copied = LocalEeReduceSupport.copyAsDouble(input, spec.inputBands, cols, rows)
    val sources = Array.tabulate(spec.inputBands) { index =>
      val band = copied.band(index)
      require(band.cellType == DoubleConstantNoDataCellType,
        "integer values working bands must use Float64 with NaN NoData")
      band
    }
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
        output(row * cols + col) = if (!valid) Double.NaN else applyValue(values, spec)
        col += 1
      }
      row += 1
    }
    DoubleArrayTile(output, cols, rows, DoubleConstantNoDataCellType)
  }

  private def applyValue(values: Array[Double], spec: LocalEeIntegerValuesSpec.Value): Double = {
    val left = values(0)
    if (LocalEeIntegerValuesSpec.ComparisonOperations(spec.op)) {
      val right = values(1)
      val matched = spec.op match {
        case "eq" => left == right
        case "neq" => left != right
        case "lt" => left < right
        case "lte" => left <= right
        case "gt" => left > right
        case "gte" => left >= right
      }
      if (matched) 1d else 0d
    } else spec.op match {
      case "bit_and" => exactBitResult(asLong(left) & asLong(values(1)), spec.op)
      case "bit_or" => exactBitResult(asLong(left) | asLong(values(1)), spec.op)
      case "bit_xor" => exactBitResult(asLong(left) ^ asLong(values(1)), spec.op)
      case "bit_not" => exactBitResult(~asLong(left), spec.op)
      case "left_shift" =>
        val value = asLong(left)
        val shift = shiftCount(values(1))
        val shifted = BigInt(value) << shift
        require(shifted >= -MaxSafeIntegerBig && shifted <= MaxSafeIntegerBig,
          "integer values left_shift result exceeds the exact Float64 integer range")
        shifted.toDouble
      case "right_shift" => (asLong(left) >> shiftCount(values(1))).toDouble
      case "bit_count" => java.lang.Long.bitCount(asLong(left)).toDouble
      case "cast" => castValue(left, spec.dtype.get)
    }
  }

  private def asLong(value: Double): Long = {
    require(value.isFinite && value == java.lang.Math.rint(value) &&
      value >= -MaxSafeIntegerDouble && value <= MaxSafeIntegerDouble,
      "integer values bit operations require finite integral inputs within +/-2^53")
    value.toLong
  }

  private def shiftCount(value: Double): Int = {
    val count = asLong(value)
    require(count >= 0L && count <= 63L, "integer values shift count must be an integer in 0..63")
    count.toInt
  }

  private def exactBitResult(value: Long, operation: String): Double = {
    require(value >= -MaxSafeInteger && value <= MaxSafeInteger,
      s"integer values $operation result exceeds the exact Float64 integer range")
    value.toDouble
  }

  private def castValue(value: Double, dtype: String): Double = {
    require(value.isFinite, "integer values cast input must be finite")
    if (dtype == "int64") {
      val truncated = truncateTowardZero(value)
      require(truncated >= -MaxSafeIntegerDouble && truncated <= MaxSafeIntegerDouble,
        "integer values int64 cast result exceeds the exact Float64 integer range")
      truncated
    } else {
      val (minimum, maximum) = dtype match {
        case "int8" => (-128d, 127d)
        case "uint8" => (0d, 255d)
        case "int16" => (-32768d, 32767d)
        case "uint16" => (0d, 65535d)
        case "int32" => (-2147483648d, 2147483647d)
        case "uint32" => (0d, 4294967295d)
      }
      val clamped = if (value < minimum) minimum else if (value > maximum) maximum else value
      truncateTowardZero(clamped)
    }
  }

  private def truncateTowardZero(value: Double): Double =
    if (value < 0d) java.lang.Math.ceil(value) else java.lang.Math.floor(value)
}
