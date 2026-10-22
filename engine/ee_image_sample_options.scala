package local.ee.image.sample

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Strict, dependency-locked wire options for the internal Image.sample SPI. */
object LocalEeImageSampleOptions {
  final case class Value(
    factor: Option[Double], numPixels: Option[Int], seed: Int, dropNulls: Boolean
  ) extends Serializable

  private val MaxBytes = 1000000
  private val Fields = Set("algorithm", "factor", "num_pixels", "seed", "drop_nulls")

  def parse(text: String): Value = {
    require(text != null, "image sample options must be a JSON string")
    require(text.getBytes(java.nio.charset.StandardCharsets.UTF_8).length <= MaxBytes,
      "image sample options exceed 1 MB")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("image sample options are invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT,
        "image sample options must be an object")
      var algorithm: Option[String] = None
      var factor: Option[Double] = None
      var numPixels: Option[Int] = None
      var seed: Option[Int] = None
      var dropNulls: Option[Boolean] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "image sample options contain an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"image sample options contain unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "algorithm" =>
            require(token == JsonToken.VALUE_STRING, "image sample algorithm must be a string")
            algorithm = Some(parser.getText)
          case "factor" =>
            factor = if (token == JsonToken.VALUE_NULL) None else {
              require(token == JsonToken.VALUE_NUMBER_INT || token == JsonToken.VALUE_NUMBER_FLOAT,
                "image sample factor must be a finite number or null")
              val value = parser.getDecimalValue.doubleValue()
              require(value.isFinite && value > 0.0 && value <= 1.0,
                "image sample factor must be finite and in (0, 1]")
              Some(value)
            }
          case "num_pixels" =>
            numPixels = if (token == JsonToken.VALUE_NULL) None else {
              require(token == JsonToken.VALUE_NUMBER_INT,
                "image sample num_pixels must be an integer or null")
              val value = parser.getBigIntegerValue
              require(value.signum >= 0 && value.compareTo(java.math.BigInteger.valueOf(1000L)) <= 0,
                "image sample num_pixels must be an integer in 0..1000")
              Some(value.intValue)
            }
          case "seed" =>
            require(token == JsonToken.VALUE_NUMBER_INT, "image sample seed must be a signed 32-bit integer")
            val value = parser.getBigIntegerValue
            require(value.compareTo(java.math.BigInteger.valueOf(Int.MinValue.toLong)) >= 0 &&
              value.compareTo(java.math.BigInteger.valueOf(Int.MaxValue.toLong)) <= 0,
              "image sample seed must be a signed 32-bit integer")
            seed = Some(value.intValue)
          case "drop_nulls" =>
            require(token == JsonToken.VALUE_TRUE || token == JsonToken.VALUE_FALSE,
              "image sample drop_nulls must be boolean")
            dropNulls = Some(token == JsonToken.VALUE_TRUE)
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "image sample options must contain exactly one JSON object")
      require(fields == Fields, "image sample options must contain exactly the declared fields")
      require(algorithm.contains("splitmix64-grid-v1"), "unsupported image sample algorithm")
      require(!(factor.nonEmpty && numPixels.nonEmpty),
        "image sample factor and num_pixels cannot both be set")
      Value(factor, numPixels, seed.get, dropNulls.get)
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("image sample options are invalid JSON", error)
    } finally parser.close()
  }
}
