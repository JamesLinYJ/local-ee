package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Strict v1 wire contract for native pixel bitwise, cast and Float64 comparison operations. */
private[reduce] object LocalEeIntegerValuesSpec {
  sealed trait Operand extends Serializable
  final case class Band(index: Int) extends Operand
  final case class Constant(bits: Long) extends Operand {
    def value: Double = java.lang.Double.longBitsToDouble(bits)
  }

  final case class Value(dtype: Option[String], op: String, operands: Vector[Operand]) extends Serializable {
    val inputBands: Int = operands.collect { case Band(index) => index }.distinct.size
    val integerOnly: Boolean = !ComparisonOperations(op) && !LocalEeFloat64Values.supports(op)
  }

  private val MaxBytes = 1024
  private val Fields = Set("dtype", "op", "operands", "v")
  private val IntegerOperations = Set(
    "bit_and", "bit_or", "bit_xor", "bit_not", "left_shift", "right_shift", "bit_count",
    "cast", "eq", "neq", "lt", "lte", "gt", "gte")
  private val Operations = IntegerOperations ++ LocalEeFloat64Values.OperationArities.keySet
  private val UnaryOperations = Set("bit_not", "bit_count", "cast") ++
    LocalEeFloat64Values.OperationArities.collect { case (name, 1) => name }.toSet
  private[reduce] val ComparisonOperations = Set("eq", "neq", "lt", "lte", "gt", "gte")
  private val CastTypes = Set("int8", "uint8", "int16", "uint16", "int32", "uint32", "int64")
  private val HexDigits = "0123456789abcdef"

  def parse(text: String): Value = {
    require(text != null, "integer values spec must be a JSON string")
    require(text.length <= MaxBytes && text.forall(_ <= 0x7f),
      s"integer values spec must contain at most $MaxBytes ASCII bytes")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("integer values spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT,
        "integer values spec must be a JSON object")
      var dtype: Option[Option[String]] = None
      var operation: Option[String] = None
      var operands: Option[Vector[Operand]] = None
      var version: Option[Int] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "integer values spec contains an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"integer values spec contains unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "dtype" =>
            if (token == JsonToken.VALUE_NULL) dtype = Some(None)
            else {
              require(token == JsonToken.VALUE_STRING, "integer values dtype must be null or a string")
              dtype = Some(Some(parser.getText))
            }
          case "op" =>
            require(token == JsonToken.VALUE_STRING, "integer values op must be a string")
            operation = Some(parser.getText)
          case "operands" => operands = Some(readOperands(parser, token))
          case "v" => version = Some(readInteger(parser, token, "integer values spec version", 1, 1))
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "integer values spec must contain exactly one JSON object")
      require(fields == Fields,
        "integer values spec must contain exactly dtype, op, operands, and v")
      require(version.contains(1), "unsupported integer values spec version")

      val selectedOperation = operation.get
      require(Operations(selectedOperation), s"unsupported integer values operation: $selectedOperation")
      val selectedOperands = operands.get
      val expectedArity = if (UnaryOperations(selectedOperation)) 1 else 2
      require(selectedOperands.length == expectedArity,
        s"integer values $selectedOperation requires exactly $expectedArity operand(s)")
      val bandIndices = selectedOperands.collect { case Band(index) => index }.distinct.sorted
      require(bandIndices.nonEmpty, "integer values spec requires at least one band reference")
      require(bandIndices.zipWithIndex.forall { case (index, expected) => index == expected },
        "integer values band references must be contiguous from band 0")
      require(bandIndices.length <= 2, "integer values spec supports at most two distinct input bands")
      selectedOperands.zipWithIndex.foreach {
        case (Constant(bits), index) =>
          validateConstant(selectedOperation, index, java.lang.Double.longBitsToDouble(bits))
        case _ => ()
      }

      val selectedDtype = dtype.get
      if (selectedOperation == "cast") {
        require(selectedDtype.exists(CastTypes),
          "integer values cast dtype must be int8, uint8, int16, uint16, int32, uint32, or int64")
      } else {
        require(selectedDtype.isEmpty, "integer values dtype must be null except for cast")
      }

      val result = Value(selectedDtype, selectedOperation, selectedOperands)
      require(text == canonicalJson(result),
        "integer values spec must use canonical compact sorted-key JSON")
      result
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("integer values spec is invalid JSON", error)
    } finally parser.close()
  }

  private def readOperands(parser: JsonParser, initial: JsonToken): Vector[Operand] = {
    require(initial == JsonToken.START_ARRAY, "integer values operands must be an array")
    val result = Vector.newBuilder[Operand]
    var count = 0
    var token = parser.nextToken()
    while (token != JsonToken.END_ARRAY && token != null) {
      require(count < 2, "integer values operands may contain at most two entries")
      require(token == JsonToken.START_OBJECT, "each integer values operand must be an object")
      result += readOperand(parser)
      count += 1
      token = parser.nextToken()
    }
    require(token == JsonToken.END_ARRAY, "integer values operands are incomplete")
    result.result()
  }

  private def readOperand(parser: JsonParser): Operand = {
    var band: Option[Int] = None
    var constant: Option[Long] = None
    var fields = Set.empty[String]
    var token = parser.nextToken()
    while (token != JsonToken.END_OBJECT && token != null) {
      require(token == JsonToken.FIELD_NAME, "integer values operand contains an invalid field")
      val name = parser.getCurrentName
      require(name == "band" || name == "constant", s"unknown integer values operand field: $name")
      fields += name
      token = parser.nextToken()
      name match {
        case "band" => band = Some(readInteger(parser, token, "integer values band index", 0, 1))
        case "constant" =>
          require(token == JsonToken.VALUE_STRING, "integer values constant must be a binary64 bit string")
          val encoded = parser.getText
          require(encoded.matches("[0-9a-f]{16}"),
            "integer values constant must be 16 lowercase hexadecimal digits")
          val bits = java.lang.Long.parseUnsignedLong(encoded, 16)
          require(java.lang.Double.longBitsToDouble(bits).isFinite,
            "integer values constant must encode a finite binary64 value")
          constant = Some(bits)
      }
      token = parser.nextToken()
    }
    require(token == JsonToken.END_OBJECT, "integer values operand is incomplete")
    require(fields.size == 1, "integer values operand must contain exactly one band or constant field")
    band.map(Band).orElse(constant.map(Constant)).get
  }

  private def readInteger(parser: JsonParser, token: JsonToken, label: String, minimum: Int, maximum: Int): Int = {
    require(token == JsonToken.VALUE_NUMBER_INT, s"$label must be an integer")
    val value = parser.getBigIntegerValue
    require(value.compareTo(java.math.BigInteger.valueOf(minimum.toLong)) >= 0 &&
      value.compareTo(java.math.BigInteger.valueOf(maximum.toLong)) <= 0,
      s"$label must be in $minimum..$maximum")
    value.intValueExact()
  }

  /** Check fixed numeric values at parse time, independent of whether a raster has valid cells. */
  private def validateConstant(operation: String, index: Int, value: Double): Unit = {
    require(value.isFinite, "integer values constants must be finite")
    if (ComparisonOperations(operation) || operation == "cast" ||
      LocalEeFloat64Values.supports(operation)) return
    require(value == java.lang.Math.rint(value) && value >= -9007199254740992d &&
      value <= 9007199254740992d,
      "integer values bit constants must be integral within +/-2^53")
    if ((operation == "left_shift" || operation == "right_shift") && index == 1) {
      require(value >= 0d && value <= 63d,
        "integer values shift count constant must be an integer in 0..63")
    }
  }

  private def canonicalJson(value: Value): String = {
    val dtype = value.dtype.map(selected => s"\"$selected\"").getOrElse("null")
    val operands = value.operands.map {
      case Band(index) => s"{\"band\":$index}"
      case Constant(bits) => s"{\"constant\":\"${hexBits(bits)}\"}"
    }.mkString("[", ",", "]")
    s"{\"dtype\":$dtype,\"op\":\"${value.op}\",\"operands\":$operands,\"v\":1}"
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
