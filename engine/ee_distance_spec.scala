package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Strict canonical wire contract and bounded neighbor plan for Image.distance. */
private[reduce] object LocalEeDistanceSpec {
  final case class Offset(dx: Int, dy: Int, distance: Int) extends Serializable

  final case class Value(metric: String, radiusBits: Long, skipMasked: Boolean) extends Serializable {
    require(Metrics(metric), s"unsupported distance metric: $metric")
    val radius: Double = java.lang.Double.longBitsToDouble(radiusBits)
    require(radiusBits >= 0L && radius.isFinite && radius >= 0.0d && radius <= 16.0d,
      "distance radius must be finite, nonnegative, and at most 16")
    val halo: Int = math.ceil(radius).toInt
    private val exactRadius = positiveBinaryRational(radiusBits)
    private val radiusFloor = floorPowerOfTwo(exactRadius._1, exactRadius._2)
    private val squaredRadiusFloor = floorPowerOfTwo(
      exactRadius._1.multiply(exactRadius._1), Math.multiplyExact(exactRadius._2, 2))
    val offsets: Vector[Offset] = prepareOffsets(metric, halo, radiusFloor, squaredRadiusFloor)
  }

  private val MaxBytes = 1024
  private val Fields = Set("metric", "radius", "skip_masked", "v")
  private val Metrics = Set("euclidean", "manhattan", "chebyshev")
  private val HexDigits = "0123456789abcdef"

  def parse(text: String): Value = {
    require(text != null, "distance spec must be a JSON string")
    require(text.length <= MaxBytes && text.forall(_ <= 0x7f),
      s"distance spec must contain at most $MaxBytes ASCII bytes")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("distance spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT, "distance spec must be a JSON object")
      var metric: Option[String] = None
      var radiusBits: Option[Long] = None
      var skipMasked: Option[Boolean] = None
      var version: Option[Int] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "distance spec contains an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"distance spec contains unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "metric" =>
            require(token == JsonToken.VALUE_STRING, "distance metric must be a string")
            metric = Some(parser.getText)
          case "radius" =>
            require(token == JsonToken.VALUE_STRING, "distance radius must be a binary64 hex string")
            radiusBits = Some(readRadiusBits(parser.getText))
          case "skip_masked" =>
            require(token == JsonToken.VALUE_TRUE || token == JsonToken.VALUE_FALSE,
              "distance skip_masked must be boolean")
            skipMasked = Some(token == JsonToken.VALUE_TRUE)
          case "v" => version = Some(readVersion(parser, token))
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "distance spec must contain exactly one JSON object")
      require(fields == Fields, "distance spec must contain exactly metric, radius, skip_masked, and v")
      require(version.contains(1), "unsupported distance spec version")
      val selectedMetric = metric.get
      require(Metrics(selectedMetric), s"unsupported distance metric: $selectedMetric")
      val result = Value(selectedMetric, radiusBits.get, skipMasked.get)
      require(text == canonicalJson(result), "distance spec must use canonical compact sorted-key JSON")
      result
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("distance spec is invalid JSON", error)
    } finally parser.close()
  }

  private def readRadiusBits(encoded: String): Long = {
    require(encoded.matches("[0-9a-f]{16}"),
      "distance radius must contain 16 lowercase hexadecimal digits")
    val bits = try java.lang.Long.parseUnsignedLong(encoded, 16) catch {
      case error: NumberFormatException => throw new IllegalArgumentException("distance radius is invalid", error)
    }
    val radius = java.lang.Double.longBitsToDouble(bits)
    require(bits >= 0L && radius.isFinite && radius >= 0.0d && radius <= 16.0d,
      "distance radius must be finite, nonnegative, and at most 16")
    bits
  }

  private def readVersion(parser: JsonParser, token: JsonToken): Int = {
    require(token == JsonToken.VALUE_NUMBER_INT, "distance spec version must be an integer")
    require(parser.getBigIntegerValue == java.math.BigInteger.ONE, "unsupported distance spec version")
    1
  }

  /** Generate one immutable order; each cell can stop at its first valid nonzero candidate. */
  private def prepareOffsets(
    metric: String, halo: Int, radiusFloor: Int, squaredRadiusFloor: Int
  ): Vector[Offset] = {
    val result = Vector.newBuilder[Offset]
    var dy = -halo
    while (dy <= halo) {
      var dx = -halo
      while (dx <= halo) {
        val squared = dx * dx + dy * dy
        val distance = metric match {
          case "euclidean" => squared
          case "manhattan" => math.abs(dx) + math.abs(dy)
          case "chebyshev" => math.max(math.abs(dx), math.abs(dy))
        }
        val inside = if (metric == "euclidean") squared <= squaredRadiusFloor else distance <= radiusFloor
        if (inside) result += Offset(dx, dy, distance)
        dx += 1
      }
      dy += 1
    }
    result.result().sortBy(offset => (offset.distance, offset.dy, offset.dx))
  }

  private def positiveBinaryRational(bits: Long): (java.math.BigInteger, Int) = {
    val rawExponent = ((bits >>> 52) & 0x7ffL).toInt
    val fraction = bits & ((1L << 52) - 1L)
    val significand = if (rawExponent == 0) fraction else fraction | (1L << 52)
    (java.math.BigInteger.valueOf(significand), if (rawExponent == 0) -1074 else rawExponent - 1075)
  }

  /** Exact integer floor of a nonnegative binary rational, computed once per radius. */
  private def floorPowerOfTwo(value: java.math.BigInteger, exponent: Int): Int = {
    val integer = if (exponent >= 0) value.shiftLeft(exponent) else value.shiftRight(-exponent)
    integer.intValueExact()
  }

  private def canonicalJson(value: Value): String =
    s"{\"metric\":\"${value.metric}\",\"radius\":\"${hexBits(value.radiusBits)}\"," +
      s"\"skip_masked\":${value.skipMasked},\"v\":1}"

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
