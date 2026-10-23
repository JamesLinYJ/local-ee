package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Strict wire contract shared with the Python focal adapter. */
private[reduce] object LocalEeFocalSpec {
  final case class Offset(dx: Int, dy: Int) extends Serializable
  final case class Value(
    operation: String, offsets: Vector[Offset], iterations: Int, skipMasked: Boolean
  ) extends Serializable {
    val radiusX: Int = offsets.iterator.map(offset => math.abs(offset.dx)).max
    val radiusY: Int = offsets.iterator.map(offset => math.abs(offset.dy)).max
  }

  private val MaxBytes = 32768
  private val MaxOffsets = 1089
  private val Fields = Set("v", "operation", "offsets", "iterations", "skip_masked")
  private val Operations = Set("mean", "min", "max", "median", "mode")

  def parse(text: String): Value = {
    require(text != null, "focal spec must be a JSON string")
    require(text.length <= MaxBytes && text.forall(_ <= 0x7f),
      s"focal spec must contain at most $MaxBytes ASCII bytes")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("focal spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT, "focal spec must be a JSON object")
      var version: Option[Int] = None
      var operation: Option[String] = None
      var offsets: Option[Vector[Offset]] = None
      var iterations: Option[Int] = None
      var skipMasked: Option[Boolean] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "focal spec contains an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"focal spec contains unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "v" => version = Some(readInteger(parser, token, "focal spec version", 1, 1))
          case "operation" =>
            require(token == JsonToken.VALUE_STRING, "focal operation must be a string")
            operation = Some(parser.getText)
          case "offsets" => offsets = Some(readOffsets(parser, token))
          case "iterations" => iterations = Some(readInteger(parser, token, "focal iterations", 1, 8))
          case "skip_masked" =>
            require(token == JsonToken.VALUE_TRUE || token == JsonToken.VALUE_FALSE,
              "focal skip_masked must be boolean")
            skipMasked = Some(token == JsonToken.VALUE_TRUE)
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "focal spec must contain exactly one JSON object")
      require(fields == Fields, "focal spec must contain exactly v, operation, offsets, iterations, and skip_masked")
      require(version.contains(1), "unsupported focal spec version")
      val selectedOperation = operation.get
      require(Operations(selectedOperation), s"unsupported focal operation: $selectedOperation")
      val selectedOffsets = offsets.get
      require(selectedOffsets.nonEmpty && selectedOffsets.length <= MaxOffsets,
        s"focal offsets must contain 1 to $MaxOffsets entries")
      require(selectedOffsets == selectedOffsets.sortBy(offset => (offset.dy, offset.dx)),
        "focal offsets must be sorted by (dy, dx)")
      require(selectedOffsets.distinct.length == selectedOffsets.length,
        "focal offsets must be unique")
      val result = Value(selectedOperation, selectedOffsets, iterations.get, skipMasked.get)
      require(text == canonicalJson(result), "focal spec must use canonical compact JSON")
      result
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("focal spec is invalid JSON", error)
    } finally parser.close()
  }

  private def readOffsets(parser: JsonParser, initial: JsonToken): Vector[Offset] = {
    require(initial == JsonToken.START_ARRAY, "focal offsets must be an array")
    val result = Vector.newBuilder[Offset]
    var count = 0
    var token = parser.nextToken()
    while (token != JsonToken.END_ARRAY && token != null) {
      require(token == JsonToken.START_ARRAY, "each focal offset must be a [dx, dy] pair")
      val dxToken = parser.nextToken()
      val dx = readInteger(parser, dxToken, "focal dx", -32, 32)
      val dyToken = parser.nextToken()
      val dy = readInteger(parser, dyToken, "focal dy", -32, 32)
      require(parser.nextToken() == JsonToken.END_ARRAY, "each focal offset must contain exactly two integers")
      count += 1
      require(count <= MaxOffsets, s"focal offsets exceed the $MaxOffsets-entry limit")
      result += Offset(dx, dy)
      token = parser.nextToken()
    }
    require(token == JsonToken.END_ARRAY, "focal offsets are incomplete")
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

  private def canonicalJson(value: Value): String = {
    val offsets = value.offsets.map(offset => s"[${offset.dx},${offset.dy}]").mkString("[", ",", "]")
    s"{\"iterations\":${value.iterations},\"offsets\":$offsets,\"operation\":\"${value.operation}\"," +
      s"\"skip_masked\":${value.skipMasked},\"v\":1}"
  }
}

/** Conservative, Spark-free work accounting shared by the adapter and kernel probe. */
private[reduce] object LocalEeFocalBudget {
  final case class Plan(keyCount: Long) extends Serializable

  val MaxSourceKeys = 100000L
  val MaxDecodedCells = 100000000L
  val MaxTileDecodedCells = 10000000L
  val MaxFocalWork = 1000000000L
  val MaxPerTileWork = 100000000L
  val ExactAccumulatorLimbs = 34L
  private val MeanNeighborLimbWork = ExactAccumulatorLimbs * 2L
  private val MeanRoundingLimbWork = ExactAccumulatorLimbs * 8L
  private val MedianMidpointLimbWork = ExactAccumulatorLimbs * 12L

  def plan(keyCount: Long, cols: Int, rows: Int, spec: LocalEeFocalSpec.Value): Plan = {
    require(keyCount > 0L && keyCount <= MaxSourceKeys,
      s"local_ee_focal supports 1 to $MaxSourceKeys source tile keys")
    require(cols > 0 && rows > 0, "local_ee_focal tile dimensions must be positive")
    val tileCells = Math.multiplyExact(cols.toLong, rows.toLong)
    require(tileCells <= MaxTileDecodedCells,
      s"local_ee_focal tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    require(keyCount <= MaxDecodedCells / tileCells,
      s"local_ee_focal exceeds the $MaxDecodedCells aggregate decoded-cell limit")

    val radius = math.max(spec.radiusX, spec.radiusY)
    require(radius == 0 || radius < math.min(cols, rows),
      "local_ee_focal positive neighborhood radius must be smaller than the smaller tile dimension")
    val bufferCols = Math.addExact(cols.toLong, Math.multiplyExact(2L, radius.toLong))
    val bufferRows = Math.addExact(rows.toLong, Math.multiplyExact(2L, radius.toLong))
    val bufferedCells = Math.multiplyExact(bufferCols, bufferRows)
    require(bufferedCells <= MaxTileDecodedCells,
      s"local_ee_focal buffered tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    val aggregateBufferedCells = Math.multiplyExact(bufferedCells, keyCount)
    val allIterationBufferCells = Math.multiplyExact(aggregateBufferedCells, spec.iterations.toLong)
    require(allIterationBufferCells <= MaxDecodedCells,
      s"local_ee_focal exceeds the $MaxDecodedCells iterative buffered decoded-cell limit")

    val offsets = spec.offsets.length.toLong
    val sortFactor = if (spec.operation == "median" || spec.operation == "mode")
      32 - Integer.numberOfLeadingZeros(spec.offsets.length - 1)
    else 0
    val offsetWork = Math.multiplyExact(offsets, 1L + sortFactor.toLong)
    val exactWork = spec.operation match {
      case "mean" => Math.addExact(Math.multiplyExact(offsets, MeanNeighborLimbWork), MeanRoundingLimbWork)
      case "median" => MedianMidpointLimbWork
      case _ => 0L
    }
    val workPerPixel = Math.addExact(offsetWork, exactWork)
    val neighborAndSortWork = Math.multiplyExact(
      Math.multiplyExact(tileCells, workPerPixel), spec.iterations.toLong)
    val bufferWork = Math.multiplyExact(bufferedCells, spec.iterations.toLong)
    val perTileWork = Math.addExact(neighborAndSortWork, bufferWork)
    require(perTileWork <= MaxPerTileWork,
      s"local_ee_focal exceeds the $MaxPerTileWork per-tile work limit")
    val totalWork = Math.multiplyExact(perTileWork, keyCount)
    require(totalWork <= MaxFocalWork,
      s"local_ee_focal exceeds the $MaxFocalWork total neighbor-work limit")
    Plan(keyCount)
  }
}
