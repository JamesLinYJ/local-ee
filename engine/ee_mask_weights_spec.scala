package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Independent parser for the tiny canonical fractional-mask projection wire. */
private[reduce] object LocalEeMaskWeightsSpec {
  final case class Value(op: String, inputBands: Int) extends Serializable

  private val MaxSpecBytes = 128
  private val Fields = Set("op", "v")
  private val Operations = Set("validity", "update", "apply")

  def parse(text: String): Value = {
    require(text != null, "mask weights spec must be a JSON string")
    require(text.length <= MaxSpecBytes && text.forall(_ <= 0x7f),
      s"mask weights spec must contain at most $MaxSpecBytes ASCII bytes")

    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("mask weights spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT,
        "mask weights spec must be a JSON object")
      var operation: Option[String] = None
      var version: Option[Int] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "mask weights spec contains an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"mask weights spec contains unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "op" =>
            require(token == JsonToken.VALUE_STRING, "mask weights op must be a string")
            operation = Some(parser.getText)
          case "v" =>
            require(token == JsonToken.VALUE_NUMBER_INT, "mask weights spec version must be an integer")
            val value = parser.getBigIntegerValue
            require(value == java.math.BigInteger.ONE, "unsupported mask weights spec version")
            version = Some(1)
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "mask weights spec must contain exactly one JSON object")
      require(fields == Fields, "mask weights spec must contain exactly op and v")
      require(version.contains(1), "unsupported mask weights spec version")
      val op = operation.get
      require(Operations(op), s"unsupported mask weights operation: $op")
      val result = Value(op, if (op == "validity") 1 else 2)
      require(text == canonicalJson(result),
        "mask weights spec must use canonical compact sorted-key JSON")
      result
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("mask weights spec is invalid JSON", error)
    } finally parser.close()
  }

  private def canonicalJson(value: Value): String = s"{\"op\":\"${value.op}\",\"v\":1}"
}
