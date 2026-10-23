package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Strict local wire contract for Image.fastDistanceTransform. */
private[reduce] object LocalEeFastDistanceSpec {
  final case class Value(metric: String, neighborhood: Int) extends Serializable {
    require(Metrics(metric), s"unsupported fast distance metric: $metric")
    require(neighborhood >= 1 && neighborhood <= MaxNeighborhood,
      s"fast distance neighborhood must be in 1..$MaxNeighborhood")

    val cap: Int = if (metric == "squared_euclidean")
      Math.multiplyExact(neighborhood, neighborhood)
    else neighborhood
  }

  val MaxNeighborhood = 4096
  private val MaxBytes = 1024
  private val Fields = Set("metric", "neighborhood", "v")
  private val Metrics = Set("squared_euclidean", "manhattan", "chebyshev")

  def parse(text: String): Value = {
    require(text != null, "fast distance spec must be a JSON string")
    require(text.length <= MaxBytes && text.forall(_ <= 0x7f),
      s"fast distance spec must contain at most $MaxBytes ASCII bytes")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("fast distance spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT,
        "fast distance spec must be a JSON object")
      var metric: Option[String] = None
      var neighborhood: Option[Int] = None
      var version: Option[Int] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "fast distance spec contains an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"fast distance spec contains unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "metric" =>
            require(token == JsonToken.VALUE_STRING, "fast distance metric must be a string")
            metric = Some(parser.getText)
          case "neighborhood" =>
            neighborhood = Some(readInteger(parser, token, "fast distance neighborhood", 1, MaxNeighborhood))
          case "v" =>
            version = Some(readInteger(parser, token, "fast distance spec version", 1, 1))
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "fast distance spec must contain exactly one JSON object")
      require(fields == Fields,
        "fast distance spec must contain exactly metric, neighborhood, and v")
      require(version.contains(1), "unsupported fast distance spec version")
      val selectedMetric = metric.get
      require(Metrics(selectedMetric), s"unsupported fast distance metric: $selectedMetric")
      val result = Value(selectedMetric, neighborhood.get)
      require(text == canonicalJson(result),
        "fast distance spec must use canonical compact sorted-key JSON")
      result
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("fast distance spec is invalid JSON", error)
    } finally parser.close()
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

  private def canonicalJson(value: Value): String =
    s"{\"metric\":\"${value.metric}\",\"neighborhood\":${value.neighborhood},\"v\":1}"
}
