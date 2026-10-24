package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}
import scala.collection.mutable

/** Independent validator for the bounded geodesic clip-coverage wire. */
private[reduce] object LocalEeClipCoverageSpec {
  final case class Position(lon: Double, lat: Double) extends Serializable
  final case class Value(polygons: Vector[Vector[Vector[Position]]], positions: Int) extends Serializable

  val MaxBytes = 1000000
  val MaxPolygons = 1000
  val MaxRings = 1000
  val MaxPositions = 10000
  private final class Counts(var rings: Int = 0, var positions: Int = 0)

  def parse(text: String): Value = {
    require(text != null, "clip coverage spec must be a JSON string")
    val bytes = text.getBytes(java.nio.charset.StandardCharsets.UTF_8).length
    require(bytes <= MaxBytes && text.forall(_ <= 0x7f),
      s"clip coverage spec must contain at most $MaxBytes ASCII bytes")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("clip coverage spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT, "clip coverage spec must be an object")
      val fields = Vector.newBuilder[String]
      var model: Option[String] = None
      var polygons: Option[Vector[Vector[Vector[Position]]]] = None
      var version: Option[Int] = None
      val counts = new Counts()
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "clip coverage spec contains an invalid field")
        val field = parser.getCurrentName
        require(Set("model", "polygons", "version")(field),
          s"clip coverage spec contains unknown field: $field")
        fields += field
        token = parser.nextToken()
        field match {
          case "model" =>
            require(token == JsonToken.VALUE_STRING, "clip coverage model must be a string")
            model = Some(parser.getText)
          case "polygons" => polygons = Some(readPolygons(parser, token, counts))
          case "version" =>
            require(token == JsonToken.VALUE_NUMBER_INT, "clip coverage version must be an integer")
            require(parser.getBigIntegerValue == java.math.BigInteger.ONE,
              "unsupported clip coverage spec version")
            version = Some(1)
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "clip coverage spec must contain exactly one JSON object")
      require(fields.result() == Vector("model", "polygons", "version"),
        "clip coverage spec fields must be sorted and contain exactly model, polygons, and version")
      require(model.contains("great-circle"), "clip coverage model must be great-circle")
      require(version.contains(1), "unsupported clip coverage spec version")
      val rings = polygons.get
      val all = rings.iterator.flatMap(_.iterator).flatten.toVector
      validatePositions(rings, all)
      val result = Value(rings, all.length)
      // Python owns float token spelling; validate compact sorted structure without JVM reserialization.
      require(!text.exists(_.isWhitespace) && text.startsWith("{\"model\":\"great-circle\",\"polygons\":[") &&
        text.endsWith("],\"version\":1}"),
        "clip coverage spec must use compact JSON with sorted keys and canonical model/version fields")
      result
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("clip coverage spec is invalid JSON", error)
    } finally parser.close()
  }

  private def readPolygons(
    parser: JsonParser, initial: JsonToken, counts: Counts
  ): Vector[Vector[Vector[Position]]] = {
    require(initial == JsonToken.START_ARRAY, "clip coverage polygons must be an array")
    val polygons = Vector.newBuilder[Vector[Vector[Position]]]
    var count = 0
    var token = parser.nextToken()
    while (token != JsonToken.END_ARRAY && token != null) {
      require(token == JsonToken.START_ARRAY, "each clip coverage polygon must contain rings")
      count += 1
      require(count <= MaxPolygons, s"clip coverage exceeds $MaxPolygons polygons")
      polygons += readRings(parser, counts)
      token = parser.nextToken()
    }
    require(token == JsonToken.END_ARRAY, "clip coverage polygon array is incomplete")
    val result = polygons.result()
    require(result.nonEmpty, "clip coverage requires at least one polygon")
    result
  }

  private def readRings(parser: JsonParser, counts: Counts): Vector[Vector[Position]] = {
    val rings = Vector.newBuilder[Vector[Position]]
    var count = 0
    var token = parser.nextToken()
    while (token != JsonToken.END_ARRAY && token != null) {
      require(token == JsonToken.START_ARRAY, "each clip coverage ring must be an array")
      count += 1
      require(count <= MaxRings, s"clip coverage polygon exceeds $MaxRings rings")
      counts.rings += 1
      require(counts.rings <= MaxRings, s"clip coverage exceeds $MaxRings rings")
      rings += readRing(parser, counts)
      token = parser.nextToken()
    }
    require(token == JsonToken.END_ARRAY, "clip coverage rings are incomplete")
    val result = rings.result()
    require(result.nonEmpty, "each clip coverage polygon requires an exterior ring")
    result
  }

  private def readRing(parser: JsonParser, counts: Counts): Vector[Position] = {
    val positions = Vector.newBuilder[Position]
    var token = parser.nextToken()
    while (token != JsonToken.END_ARRAY && token != null) {
      require(token == JsonToken.START_ARRAY, "each clip coverage position must be [longitude, latitude]")
      val lon = readNumber(parser, "longitude")
      val lat = readNumber(parser, "latitude")
      require(parser.nextToken() == JsonToken.END_ARRAY,
        "each clip coverage position must contain exactly two coordinates")
      counts.positions += 1
      require(counts.positions <= MaxPositions,
        s"clip coverage exceeds the $MaxPositions-coordinate limit")
      positions += Position(lon, lat)
      token = parser.nextToken()
    }
    require(token == JsonToken.END_ARRAY, "clip coverage ring is incomplete")
    positions.result()
  }

  private def readNumber(parser: JsonParser, label: String): Double = {
    val token = parser.nextToken()
    require(token == JsonToken.VALUE_NUMBER_FLOAT,
      s"clip coverage $label must be a canonical Float64 JSON number")
    val value = parser.getDoubleValue
    require(value.isFinite, s"clip coverage $label must be finite")
    value
  }

  private def validatePositions(
    polygons: Vector[Vector[Vector[Position]]], all: Vector[Position]
  ): Unit = {
    val ringCount = polygons.foldLeft(0)(_ + _.length)
    require(ringCount <= MaxRings, s"clip coverage exceeds $MaxRings rings")
    require(all.nonEmpty && all.length <= MaxPositions,
      s"clip coverage requires at most $MaxPositions coordinate positions")
    all.foreach { point =>
      require(point.lon >= -180.0 && point.lon <= 180.0 && point.lat > -90.0 && point.lat < 90.0,
        "clip coverage coordinates must be finite WGS84 longitude/latitude")
    }
    val minimumLongitude = all.iterator.map(_.lon).min
    val maximumLongitude = all.iterator.map(_.lon).max
    require(maximumLongitude - minimumLongitude < 180.0,
      "clip coverage global longitude span must be less than 180 degrees")
    polygons.foreach(_.foreach { ring =>
      require(ring.length >= 4, "clip coverage rings must contain at least four closed positions")
      require(ring.head == ring.last, "clip coverage rings must be closed")
      var index = 1
      val unique = mutable.HashSet.empty[Position]
      while (index < ring.length) {
        require(ring(index - 1) != ring(index), "clip coverage rings cannot contain consecutive duplicate positions")
        unique += ring(index - 1)
        index += 1
      }
      require(unique.size >= 3, "clip coverage rings must contain three distinct vertices")
    })
  }

}
