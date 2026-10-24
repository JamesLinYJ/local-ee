package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Independent strict parser for the bounded Image.unmix native wire. */
private[reduce] object LocalEeSpectralUnmixSpec {
  final case class Value(
    endmembers: Vector[Vector[Long]], sumToOne: Boolean, nonNegative: Boolean
  ) extends Serializable {
    val components: Int = endmembers.length
    val inputBands: Int = endmembers.head.length
    def matrix: Array[Array[Double]] = endmembers.map(_.map(java.lang.Double.longBitsToDouble).toArray).toArray
  }

  private val MaxBytes = 8192
  private val Fields = Set("endmembers", "nonNegative", "sumToOne", "v")
  private val HexDigits = "0123456789abcdef"

  def parse(text: String): Value = {
    require(text != null, "spectral unmix spec must be a JSON string")
    require(text.length <= MaxBytes && text.forall(_ <= 0x7f),
      s"spectral unmix spec must contain at most $MaxBytes ASCII bytes")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("spectral unmix spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT,
        "spectral unmix spec must be a JSON object")
      var version: Option[Int] = None
      var endmembers: Option[Vector[Vector[Long]]] = None
      var sumToOne: Option[Boolean] = None
      var nonNegative: Option[Boolean] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "spectral unmix spec contains an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"spectral unmix spec contains unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "v" => version = Some(readInteger(parser, token))
          case "sumToOne" => sumToOne = Some(readBoolean(token, "sumToOne"))
          case "nonNegative" => nonNegative = Some(readBoolean(token, "nonNegative"))
          case "endmembers" => endmembers = Some(readEndmembers(parser, token))
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "spectral unmix spec must contain exactly one JSON object")
      require(fields == Fields,
        "spectral unmix spec must contain exactly endmembers, nonNegative, sumToOne, and v")
      require(version.contains(1), "unsupported spectral unmix spec version")

      val rows = endmembers.get
      require(rows.nonEmpty && rows.length <= 8,
        "spectral unmix endmembers must contain 1..8 components")
      val columns = rows.head.length
      require(columns >= 1 && columns <= 8 && rows.forall(_.length == columns),
        "spectral unmix endmembers must be a rectangular 1..8 by 1..8 matrix")
      val value = Value(rows, sumToOne.get, nonNegative.get)
      require(text == canonicalJson(value),
        "spectral unmix spec must use canonical compact sorted-key JSON")
      value
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("spectral unmix spec is invalid JSON", error)
    } finally parser.close()
  }

  private def readEndmembers(parser: JsonParser, initial: JsonToken): Vector[Vector[Long]] = {
    require(initial == JsonToken.START_ARRAY, "spectral unmix endmembers must be an array")
    val result = Vector.newBuilder[Vector[Long]]
    var components = 0
    var token = parser.nextToken()
    while (token != JsonToken.END_ARRAY && token != null) {
      require(components < 8, "spectral unmix supports at most 8 endmembers")
      require(token == JsonToken.START_ARRAY, "each spectral unmix endmember must be an array")
      val row = Vector.newBuilder[Long]
      var bands = 0
      token = parser.nextToken()
      while (token != JsonToken.END_ARRAY && token != null) {
        require(bands < 8, "spectral unmix supports at most 8 input bands")
        require(token == JsonToken.VALUE_STRING,
          "spectral unmix coefficients must be binary64 bit strings")
        val encoded = parser.getText
        require(encoded.matches("[0-9a-f]{16}"),
          "spectral unmix coefficients must be 16 lowercase hexadecimal digits")
        val bits = java.lang.Long.parseUnsignedLong(encoded, 16)
        require(java.lang.Double.longBitsToDouble(bits).isFinite,
          "spectral unmix coefficients must encode finite binary64 values")
        row += bits
        bands += 1
        token = parser.nextToken()
      }
      require(token == JsonToken.END_ARRAY && bands > 0,
        "spectral unmix endmember rows must contain 1..8 coefficients")
      result += row.result()
      components += 1
      token = parser.nextToken()
    }
    require(token == JsonToken.END_ARRAY && components > 0,
      "spectral unmix endmembers must contain 1..8 components")
    result.result()
  }

  private def readBoolean(token: JsonToken, field: String): Boolean = {
    require(token == JsonToken.VALUE_TRUE || token == JsonToken.VALUE_FALSE,
      s"spectral unmix $field must be a boolean")
    token == JsonToken.VALUE_TRUE
  }

  private def readInteger(parser: JsonParser, token: JsonToken): Int = {
    require(token == JsonToken.VALUE_NUMBER_INT, "spectral unmix spec version must be an integer")
    val value = parser.getBigIntegerValue
    require(value == java.math.BigInteger.ONE, "unsupported spectral unmix spec version")
    1
  }

  private def canonicalJson(value: Value): String = {
    val rows = value.endmembers.map(_.map(hexBits).mkString("[\"", "\",\"", "\"]"))
      .mkString("[", ",", "]")
    s"{\"endmembers\":$rows,\"nonNegative\":${value.nonNegative}," +
      s"\"sumToOne\":${value.sumToOne},\"v\":1}"
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
