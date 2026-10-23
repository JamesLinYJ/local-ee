package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Strict canonical wire contract for the one-band native neighborhood reducer. */
private[reduce] object LocalEeNeighborhoodSpec {
  final case class Coefficient(
    dx: Int, dy: Int, weightBits: Long, significand: Long, exponent: Int
  ) extends Serializable

  final case class Value(
    coefficients: Vector[Coefficient], operation: String, skipMasked: Boolean
  ) extends Serializable {
    val radiusX: Int = coefficients.iterator.map(value => math.abs(value.dx)).max
    val radiusY: Int = coefficients.iterator.map(value => math.abs(value.dy)).max
    val radius: Int = math.max(radiusX, radiusY)
    val weightUnitExponent: Int = coefficients.iterator.map(_.exponent).min
    val weightUnitBits: Int = coefficients.iterator.map(value =>
      64 - java.lang.Long.numberOfLeadingZeros(value.significand) + value.exponent - weightUnitExponent).max
  }

  private val MaxBytes = 32768
  private val MaxCoefficients = 1089
  private val Fields = Set("coefficients", "operation", "skip_masked", "v")
  private val Operations = Set("sum", "mean", "count", "min", "max", "variance", "stdDev",
    "sampleVariance", "sampleStdDev", "product", "median", "mode")
  private val HexDigits = "0123456789abcdef"
  private val OneBits = java.lang.Double.doubleToRawLongBits(1.0d)

  def parse(text: String): Value = {
    require(text != null, "neighborhood spec must be a JSON string")
    require(text.length <= MaxBytes && text.forall(_ <= 0x7f),
      s"neighborhood spec must contain at most $MaxBytes ASCII bytes")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("neighborhood spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT, "neighborhood spec must be a JSON object")
      var coefficients: Option[Vector[Coefficient]] = None
      var operation: Option[String] = None
      var skipMasked: Option[Boolean] = None
      var version: Option[Int] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "neighborhood spec contains an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"neighborhood spec contains unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "coefficients" => coefficients = Some(readCoefficients(parser, token))
          case "operation" =>
            require(token == JsonToken.VALUE_STRING, "neighborhood operation must be a string")
            operation = Some(parser.getText)
          case "skip_masked" =>
            require(token == JsonToken.VALUE_TRUE || token == JsonToken.VALUE_FALSE,
              "neighborhood skip_masked must be boolean")
            skipMasked = Some(token == JsonToken.VALUE_TRUE)
          case "v" => version = Some(readInteger(parser, token, "neighborhood spec version", 1, 1))
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "neighborhood spec must contain exactly one JSON object")
      require(fields == Fields, "neighborhood spec must contain exactly coefficients, operation, skip_masked, and v")
      require(version.contains(1), "unsupported neighborhood spec version")
      val selectedOperation = operation.get
      require(Operations(selectedOperation), s"unsupported neighborhood operation: $selectedOperation")
      val selected = coefficients.get
      require(selected.nonEmpty && selected.length <= MaxCoefficients,
        s"neighborhood coefficients must contain 1 to $MaxCoefficients entries")
      require(selected == selected.sortBy(value => (value.dy, value.dx)),
        "neighborhood coefficients must be sorted by (dy, dx)")
      require(selected.map(value => (value.dx, value.dy)).distinct.length == selected.length,
        "neighborhood coefficient offsets must be unique")
      if (!Set("sum", "mean", "count", "min", "max", "variance", "stdDev")(selectedOperation))
        require(selected.forall(_.weightBits == OneBits),
          s"neighborhood $selectedOperation requires every coefficient to equal 1")
      val result = Value(selected, selectedOperation, skipMasked.get)
      require(text == canonicalJson(result), "neighborhood spec must use canonical compact sorted-key JSON")
      result
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("neighborhood spec is invalid JSON", error)
    } finally parser.close()
  }

  private def readCoefficients(parser: JsonParser, initial: JsonToken): Vector[Coefficient] = {
    require(initial == JsonToken.START_ARRAY, "neighborhood coefficients must be an array")
    val result = Vector.newBuilder[Coefficient]
    var count = 0
    var token = parser.nextToken()
    while (token != JsonToken.END_ARRAY && token != null) {
      require(token == JsonToken.START_ARRAY, "each neighborhood coefficient must be [dx, dy, weightBits]")
      val dx = readInteger(parser, parser.nextToken(), "neighborhood dx", -32, 32)
      val dy = readInteger(parser, parser.nextToken(), "neighborhood dy", -32, 32)
      val weightToken = parser.nextToken()
      require(weightToken == JsonToken.VALUE_STRING, "neighborhood weightBits must be a string")
      val encoded = parser.getText
      require(encoded.matches("[0-9a-f]{16}"), "neighborhood weightBits must be 16 lowercase hexadecimal digits")
      val bits = java.lang.Long.parseUnsignedLong(encoded, 16)
      require(bits > 0L && java.lang.Double.longBitsToDouble(bits).isFinite,
        "neighborhood weights must be strictly positive finite binary64 values")
      require(parser.nextToken() == JsonToken.END_ARRAY,
        "each neighborhood coefficient must contain exactly three values")
      count += 1
      require(count <= MaxCoefficients, s"neighborhood coefficients exceed the $MaxCoefficients-entry limit")
      result += coefficient(dx, dy, bits)
      token = parser.nextToken()
    }
    require(token == JsonToken.END_ARRAY, "neighborhood coefficients are incomplete")
    result.result()
  }

  private def readInteger(
    parser: JsonParser, token: JsonToken, label: String, minimum: Int, maximum: Int
  ): Int = {
    require(token == JsonToken.VALUE_NUMBER_INT, s"$label must be an integer")
    val value = parser.getBigIntegerValue
    require(value.compareTo(java.math.BigInteger.valueOf(minimum.toLong)) >= 0 &&
      value.compareTo(java.math.BigInteger.valueOf(maximum.toLong)) <= 0,
      s"$label must be in $minimum..$maximum")
    value.intValue
  }

  private def coefficient(dx: Int, dy: Int, bits: Long): Coefficient = {
    val exponentBits = ((bits >>> 52) & 0x7ffL).toInt
    val fraction = bits & ((1L << 52) - 1L)
    val rawSignificand = if (exponentBits == 0) fraction else fraction | (1L << 52)
    val trailingZeros = java.lang.Long.numberOfTrailingZeros(rawSignificand)
    val baseExponent = if (exponentBits == 0) -1074 else exponentBits - 1075
    Coefficient(dx, dy, bits, rawSignificand >>> trailingZeros, baseExponent + trailingZeros)
  }

  private def canonicalJson(value: Value): String = {
    val entries = value.coefficients.map(coefficient =>
      s"[${coefficient.dx},${coefficient.dy},\"${hexBits(coefficient.weightBits)}\"]").mkString("[", ",", "]")
    s"{\"coefficients\":$entries,\"operation\":\"${value.operation}\"," +
      s"\"skip_masked\":${value.skipMasked},\"v\":1}"
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
