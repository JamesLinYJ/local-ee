package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Strict v1 wire contract for fixed per-pixel matrix operations. */
private[reduce] object LocalEeMatrixValuesSpec {
  sealed trait Operand extends Serializable
  final case class Band(index: Int) extends Operand
  final case class Constant(bits: Long) extends Operand {
    def value: Double = java.lang.Double.longBitsToDouble(bits)
  }

  final case class Value(
    op: String, rows: Int, cols: Int, rhsCols: Int, operands: Vector[Operand]
  ) extends Serializable {
    val inputBands: Int = operands.collect { case Band(index) => index }.distinct.size
    val outputRows: Int = cols
    val outputCols: Int = if (op == "solve") rhsCols else rows
    val outputCells: Int = op match {
      case "qr" => Math.addExact(
        Math.multiplyExact(rows, math.min(rows, cols)),
        Math.multiplyExact(math.min(rows, cols), cols))
      case "svd" =>
        val p = math.min(rows, cols)
        Math.addExact(Math.multiplyExact(rows, p),
          Math.addExact(Math.multiplyExact(p, p), Math.multiplyExact(cols, p)))
      case "lu" => Math.multiplyExact(Math.multiplyExact(rows, cols), 3)
      case _ => Math.multiplyExact(outputRows, outputCols)
    }
  }

  private val MaxBytes = 8192
  private val Fields = Set("cols", "op", "operands", "rhs_cols", "rows", "v")
  private val Operations = Set("solve", "inverse", "pinverse", "cholesky", "lu", "qr", "svd")
  private val HexDigits = "0123456789abcdef"

  def parse(text: String): Value = {
    require(text != null, "matrix values spec must be a JSON string")
    require(text.length <= MaxBytes && text.forall(_ <= 0x7f),
      s"matrix values spec must contain at most $MaxBytes ASCII bytes")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("matrix values spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT,
        "matrix values spec must be a JSON object")
      var version: Option[Int] = None
      var operation: Option[String] = None
      var rows: Option[Int] = None
      var cols: Option[Int] = None
      var rhsCols: Option[Int] = None
      var operands: Option[Vector[Operand]] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "matrix values spec contains an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"matrix values spec contains unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "v" => version = Some(readInteger(parser, token, "matrix values spec version", 1, 1))
          case "op" =>
            require(token == JsonToken.VALUE_STRING, "matrix values op must be a string")
            operation = Some(parser.getText)
          case "rows" => rows = Some(readInteger(parser, token, "matrix values rows", 1, 8))
          case "cols" => cols = Some(readInteger(parser, token, "matrix values cols", 1, 8))
          case "rhs_cols" => rhsCols = Some(readInteger(parser, token, "matrix values rhs_cols", 0, 8))
          case "operands" => operands = Some(readOperands(parser, token))
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "matrix values spec must contain exactly one JSON object")
      require(fields == Fields,
        "matrix values spec must contain exactly cols, op, operands, rhs_cols, rows, and v")
      require(version.contains(1), "unsupported matrix values spec version")

      val selectedOperation = operation.get
      require(Operations(selectedOperation), s"unsupported matrix values operation: $selectedOperation")
      val selectedRows = rows.get
      val selectedCols = cols.get
      val selectedRhsCols = rhsCols.get
      if (selectedOperation == "solve") {
        require(selectedRhsCols >= 1 && selectedRhsCols <= 8,
          "matrix values solve rhs_cols must be in 1..8")
      } else {
        require(selectedRhsCols == 0,
          s"matrix values $selectedOperation rhs_cols must be zero")
      }
      if (Set("inverse", "cholesky", "lu")(selectedOperation)) {
        require(selectedRows == selectedCols,
          s"matrix values $selectedOperation requires a square matrix")
      }

      val inputCells = Math.addExact(
        Math.multiplyExact(selectedRows, selectedCols),
        if (selectedOperation == "solve") Math.multiplyExact(selectedRows, selectedRhsCols) else 0)
      require(inputCells <= 64, "matrix values input cell count exceeds 64")
      val p = math.min(selectedRows, selectedCols)
      val outputCells = selectedOperation match {
        case "qr" => Math.addExact(Math.multiplyExact(selectedRows, p),
          Math.multiplyExact(p, selectedCols))
        case "svd" => Math.addExact(Math.multiplyExact(selectedRows, p),
          Math.addExact(Math.multiplyExact(p, p), Math.multiplyExact(selectedCols, p)))
        case "lu" => Math.multiplyExact(Math.multiplyExact(selectedRows, selectedCols), 3)
        case _ =>
          val outputCols = if (selectedOperation == "solve") selectedRhsCols else selectedRows
          val outputRows = if (selectedOperation == "solve") selectedCols else selectedRows
          Math.multiplyExact(outputRows, outputCols)
      }
      require(outputCells <= 64, "matrix values output cell count exceeds 64")

      val selectedOperands = operands.get
      require(selectedOperands.length == inputCells,
        s"matrix values $selectedOperation requires exactly $inputCells operands")
      val bandIndices = selectedOperands.collect { case Band(index) => index }.distinct.sorted
      require(bandIndices.nonEmpty, "matrix values spec requires at least one band reference")
      require(bandIndices.forall(_ <= 63), "matrix values band indices must be in 0..63")
      require(bandIndices.zipWithIndex.forall { case (index, expected) => index == expected },
        "matrix values band references must be contiguous from band 0")

      val result = Value(selectedOperation, selectedRows, selectedCols, selectedRhsCols, selectedOperands)
      require(text == canonicalJson(result),
        "matrix values spec must use canonical compact sorted-key JSON")
      result
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("matrix values spec is invalid JSON", error)
    } finally parser.close()
  }

  private def readOperands(parser: JsonParser, initial: JsonToken): Vector[Operand] = {
    require(initial == JsonToken.START_ARRAY, "matrix values operands must be an array")
    val result = Vector.newBuilder[Operand]
    var count = 0
    var token = parser.nextToken()
    while (token != JsonToken.END_ARRAY && token != null) {
      require(count < 64, "matrix values operands may contain at most 64 entries")
      require(token == JsonToken.START_OBJECT, "each matrix values operand must be an object")
      result += readOperand(parser)
      count += 1
      token = parser.nextToken()
    }
    require(token == JsonToken.END_ARRAY, "matrix values operands are incomplete")
    result.result()
  }

  private def readOperand(parser: JsonParser): Operand = {
    var band: Option[Int] = None
    var constant: Option[Long] = None
    var fields = Set.empty[String]
    var token = parser.nextToken()
    while (token != JsonToken.END_OBJECT && token != null) {
      require(token == JsonToken.FIELD_NAME, "matrix values operand contains an invalid field")
      val name = parser.getCurrentName
      require(name == "band" || name == "constant",
        s"unknown matrix values operand field: $name")
      fields += name
      token = parser.nextToken()
      name match {
        case "band" => band = Some(readInteger(parser, token, "matrix values band index", 0, 63))
        case "constant" =>
          require(token == JsonToken.VALUE_STRING,
            "matrix values constant must be a binary64 bit string")
          val encoded = parser.getText
          require(encoded.matches("[0-9a-f]{16}"),
            "matrix values constant must be 16 lowercase hexadecimal digits")
          val bits = java.lang.Long.parseUnsignedLong(encoded, 16)
          require(java.lang.Double.longBitsToDouble(bits).isFinite,
            "matrix values constant must encode a finite binary64 value")
          constant = Some(bits)
      }
      token = parser.nextToken()
    }
    require(token == JsonToken.END_OBJECT, "matrix values operand is incomplete")
    require(fields.size == 1, "matrix values operand must contain exactly one band or constant field")
    band.map(Band).orElse(constant.map(Constant)).get
  }

  private def readInteger(
    parser: JsonParser, token: JsonToken, label: String, minimum: Int, maximum: Int
  ): Int = {
    require(token == JsonToken.VALUE_NUMBER_INT, s"$label must be an integer")
    val value = parser.getBigIntegerValue
    require(value.compareTo(java.math.BigInteger.valueOf(minimum.toLong)) >= 0 &&
      value.compareTo(java.math.BigInteger.valueOf(maximum.toLong)) <= 0,
      s"$label must be in $minimum..$maximum")
    value.intValueExact()
  }

  private def canonicalJson(value: Value): String = {
    val operands = value.operands.map {
      case Band(index) => s"{\"band\":$index}"
      case Constant(bits) => s"{\"constant\":\"${hexBits(bits)}\"}"
    }.mkString("[", ",", "]")
    s"{\"cols\":${value.cols},\"op\":\"${value.op}\",\"operands\":$operands," +
      s"\"rhs_cols\":${value.rhsCols},\"rows\":${value.rows},\"v\":1}"
  }

  private def hexBits(value: Long): String = {
    val chars = new Array[Char](16)
    var bits = value
    var index = chars.length - 1
    while (index >= 0) {
      chars(index) = HexDigits.charAt((bits & 0xfL).toInt)
      bits = bits >>> 4
      index -= 1
    }
    new String(chars)
  }
}
