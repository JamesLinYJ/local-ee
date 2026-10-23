package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Strict canonical operation and angle contract for the native terrain family. */
private[reduce] object LocalEeTerrainSpec {
  final case class Value(
    operation: String, azimuthBits: Long, elevationBits: Long
  ) extends Serializable {
    val azimuth: Double = java.lang.Double.longBitsToDouble(azimuthBits)
    val elevation: Double = java.lang.Double.longBitsToDouble(elevationBits)
  }

  private val MaxBytes = 1024
  private val Fields = Set("azimuth", "elevation", "operation", "v")
  private val Operations = Set("slope", "aspect", "hillshade")
  private val DefaultAzimuthBits = java.lang.Double.doubleToRawLongBits(270.0d)
  private val DefaultElevationBits = java.lang.Double.doubleToRawLongBits(45.0d)

  def parse(text: String): Value = {
    require(text != null, "terrain spec must be a JSON string")
    require(text.length <= MaxBytes && text.forall(_ <= 0x7f),
      s"terrain spec must contain at most $MaxBytes ASCII bytes")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("terrain spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT, "terrain spec must be a JSON object")
      var azimuth: Option[Long] = None
      var elevation: Option[Long] = None
      var operation: Option[String] = None
      var version: Option[Int] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "terrain spec contains an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"terrain spec contains unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "azimuth" => azimuth = Some(readAngle(parser, token, "azimuth"))
          case "elevation" => elevation = Some(readAngle(parser, token, "elevation"))
          case "operation" =>
            require(token == JsonToken.VALUE_STRING, "terrain operation must be a string")
            operation = Some(parser.getText)
          case "v" => version = Some(readVersion(parser, token))
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "terrain spec must contain exactly one JSON object")
      require(fields == Fields, "terrain spec must contain exactly azimuth, elevation, operation, and v")
      require(version.contains(1), "unsupported terrain spec version")
      val selectedOperation = operation.get
      require(Operations(selectedOperation), s"unsupported terrain operation: $selectedOperation")
      val selectedAzimuth = azimuth.get
      val selectedElevation = elevation.get
      if (selectedOperation == "slope" || selectedOperation == "aspect") {
        require(selectedAzimuth == DefaultAzimuthBits && selectedElevation == DefaultElevationBits,
          s"$selectedOperation requires canonical 270/45 degree angle defaults")
      }
      val result = Value(selectedOperation, selectedAzimuth, selectedElevation)
      require(text == canonicalJson(result), "terrain spec must use canonical compact JSON")
      result
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("terrain spec is invalid JSON", error)
    } finally parser.close()
  }

  private def readAngle(parser: JsonParser, token: JsonToken, label: String): Long = {
    require(token == JsonToken.VALUE_STRING, s"terrain $label must be a binary64 bit string")
    val encoded = parser.getText
    require(encoded.matches("[0-9a-f]{16}"),
      s"terrain $label must contain 16 lowercase hexadecimal digits")
    val bits = java.lang.Long.parseUnsignedLong(encoded, 16)
    val value = java.lang.Double.longBitsToDouble(bits)
    require(value.isFinite && value >= 0.0d && value < 360.0d,
      s"terrain $label must be a normalized finite angle in [0, 360)")
    require(bits != Long.MinValue, s"terrain $label must use positive zero")
    bits
  }

  private def readVersion(parser: JsonParser, token: JsonToken): Int = {
    require(token == JsonToken.VALUE_NUMBER_INT, "terrain spec version must be an integer")
    require(parser.getBigIntegerValue == java.math.BigInteger.ONE,
      "unsupported terrain spec version")
    1
  }

  private def canonicalJson(value: Value): String =
    s"{\"azimuth\":\"${hexBits(value.azimuthBits)}\",\"elevation\":\"${hexBits(value.elevationBits)}\"," +
      s"\"operation\":\"${value.operation}\",\"v\":1}"

  private def hexBits(value: Long): String = {
    val digits = "0123456789abcdef"
    val chars = new Array[Char](16)
    var bits = value
    var index = chars.length - 1
    while (index >= 0) {
      chars(index) = digits.charAt((bits & 0xfL).toInt)
      bits = bits >>> 4
      index -= 1
    }
    new String(chars)
  }
}
