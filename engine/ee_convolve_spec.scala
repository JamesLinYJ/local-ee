package local.ee.reduce

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}

/** Strict canonical wire contract for the native Float64 convolution adapter. */
private[reduce] object LocalEeConvolveSpec {
  final case class Coefficient(
    dx: Int, dy: Int, weightBits: Long, significand: Long, exponent: Int, negative: Boolean
  ) extends Serializable {
    val isZero: Boolean = significand == 0L
  }

  final case class Value(coefficients: Vector[Coefficient]) extends Serializable {
    val active: Vector[Coefficient] = coefficients.filterNot(_.isZero)
    val radiusX: Int = if (active.isEmpty) 0 else active.iterator.map(value => math.abs(value.dx)).max
    val radiusY: Int = if (active.isEmpty) 0 else active.iterator.map(value => math.abs(value.dy)).max
    val radius: Int = math.max(radiusX, radiusY)
    val unitExponent: Int = if (active.isEmpty) 0 else 1074 - active.iterator.map(_.exponent).min
    val exactAccumulatorLimbs: Int = accumulatorLimbs(active, unitExponent)
  }

  private val MaxBytes = 32768
  private val MaxCoefficients = 1089
  private val Fields = Set("coefficients", "v")
  private val HexDigits = "0123456789abcdef"

  def parse(text: String): Value = {
    require(text != null, "convolve spec must be a JSON string")
    require(text.length <= MaxBytes && text.forall(_ <= 0x7f),
      s"convolve spec must contain at most $MaxBytes ASCII bytes")
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    val parser = try factory.createParser(text) catch {
      case error: Exception => throw new IllegalArgumentException("convolve spec is invalid JSON", error)
    }
    try {
      require(parser.nextToken() == JsonToken.START_OBJECT, "convolve spec must be a JSON object")
      var version: Option[Int] = None
      var coefficients: Option[Vector[Coefficient]] = None
      var fields = Set.empty[String]
      var token = parser.nextToken()
      while (token != JsonToken.END_OBJECT && token != null) {
        require(token == JsonToken.FIELD_NAME, "convolve spec contains an invalid field")
        val name = parser.getCurrentName
        require(Fields(name), s"convolve spec contains unknown field: $name")
        fields += name
        token = parser.nextToken()
        name match {
          case "coefficients" => coefficients = Some(readCoefficients(parser, token))
          case "v" => version = Some(readInteger(parser, token, "convolve spec version", 1, 1))
        }
        token = parser.nextToken()
      }
      require(token == JsonToken.END_OBJECT && parser.nextToken() == null,
        "convolve spec must contain exactly one JSON object")
      require(fields == Fields, "convolve spec must contain exactly coefficients and v")
      require(version.contains(1), "unsupported convolve spec version")
      val selected = coefficients.get
      require(selected == selected.sortBy(value => (value.dy, value.dx)),
        "convolve coefficients must be sorted by (dy, dx)")
      require(selected.map(value => (value.dx, value.dy)).distinct.length == selected.length,
        "convolve offsets must be unique")
      if (selected.forall(_.isZero)) {
        require(selected.length == 1 && selected.head.dx == 0 && selected.head.dy == 0 &&
          selected.head.weightBits == 0L,
          "an all-zero convolve kernel must contain only a positive-zero center coefficient")
      }
      val result = Value(selected)
      require(text == canonicalJson(result), "convolve spec must use canonical compact JSON")
      result
    } catch {
      case error: com.fasterxml.jackson.core.JsonProcessingException =>
        throw new IllegalArgumentException("convolve spec is invalid JSON", error)
    } finally parser.close()
  }

  private def readCoefficients(parser: JsonParser, initial: JsonToken): Vector[Coefficient] = {
    require(initial == JsonToken.START_ARRAY, "convolve coefficients must be an array")
    val result = Vector.newBuilder[Coefficient]
    var count = 0
    var token = parser.nextToken()
    while (token != JsonToken.END_ARRAY && token != null) {
      require(token == JsonToken.START_ARRAY, "each convolve coefficient must be [dx, dy, weightBits]")
      val dx = readInteger(parser, parser.nextToken(), "convolve dx", -32, 32)
      val dy = readInteger(parser, parser.nextToken(), "convolve dy", -32, 32)
      val weightToken = parser.nextToken()
      require(weightToken == JsonToken.VALUE_STRING, "convolve weightBits must be a string")
      val encoded = parser.getText
      require(encoded.matches("[0-9a-f]{16}"), "convolve weightBits must be 16 lowercase hexadecimal digits")
      val bits = java.lang.Long.parseUnsignedLong(encoded, 16)
      val weight = java.lang.Double.longBitsToDouble(bits)
      require(weight.isFinite, "convolve weights must be finite binary64 values")
      require(bits != Long.MinValue, "convolve weightBits must use canonical positive zero")
      require(parser.nextToken() == JsonToken.END_ARRAY,
        "each convolve coefficient must contain exactly three values")
      count += 1
      require(count <= MaxCoefficients, s"convolve coefficients exceed the $MaxCoefficients-entry limit")
      result += coefficient(dx, dy, bits)
      token = parser.nextToken()
    }
    require(token == JsonToken.END_ARRAY, "convolve coefficients are incomplete")
    val values = result.result()
    require(values.nonEmpty && values.length <= MaxCoefficients,
      s"convolve coefficients must contain 1 to $MaxCoefficients entries")
    values.foreach(value => require(math.abs(value.dx) <= 32 && math.abs(value.dy) <= 32,
      "convolve offsets must be within -32..32"))
    values
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
    if (rawSignificand == 0L) Coefficient(dx, dy, bits, 0L, 0, negative = false)
    else {
      val trailingZeros = java.lang.Long.numberOfTrailingZeros(rawSignificand)
      val baseExponent = if (exponentBits == 0) -1074 else exponentBits - 1075
      Coefficient(dx, dy, bits, rawSignificand >>> trailingZeros,
        baseExponent + trailingZeros, bits < 0L)
    }
  }

  private def accumulatorLimbs(active: Vector[Coefficient], unitExponent: Int): Int = {
    if (active.isEmpty) return 1
    val maximumWeightLog2 = active.iterator.map { coefficient =>
      63 - java.lang.Long.numberOfLeadingZeros(coefficient.significand) + coefficient.exponent
    }.max
    val termCount = active.length
    val sumBits = if (termCount <= 1) 0 else 32 - Integer.numberOfLeadingZeros(termCount - 1)
    // |pixel| < 2^1024 and |weight| < 2^(maximumWeightLog2 + 1).
    val maximumBits = Math.addExact(unitExponent,
      Math.addExact(Math.addExact(1025, maximumWeightLog2), sumBits))
    Math.toIntExact((maximumBits.toLong + 63L) / 64L)
  }

  private def canonicalJson(value: Value): String = {
    val coefficients = value.coefficients.map { coefficient =>
      s"[${coefficient.dx},${coefficient.dy},\"${hexBits(coefficient.weightBits)}\"]"
    }.mkString("[", ",", "]")
    s"{\"coefficients\":$coefficients,\"v\":1}"
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

/** Conservative work accounting for exact product shifts, accumulator adds, and final rounding. */
private[reduce] object LocalEeConvolveBudget {
  final case class Plan(
    keyCount: Long, radius: Int, bufferedCells: Long, unitExponent: Int,
    exactAccumulatorLimbs: Int, perTileWork: Long
  ) extends Serializable

  val MaxSourceKeys = 100000L
  val MaxDecodedCells = 100000000L
  val MaxTileDecodedCells = 10000000L
  val MaxConvolveWork = 1000000000L
  val MaxPerTileWork = 100000000L

  private val SignificandMultiplyLimbs = 2L

  def plan(keyCount: Long, cols: Int, rows: Int, spec: LocalEeConvolveSpec.Value): Plan = {
    val result = estimate(keyCount, cols, rows, spec)
    require(result.perTileWork <= MaxPerTileWork,
      s"local_ee_convolve exceeds the $MaxPerTileWork per-tile work limit (${result.perTileWork})")
    require(Math.multiplyExact(result.perTileWork, keyCount) <= MaxConvolveWork,
      s"local_ee_convolve exceeds the $MaxConvolveWork total work limit")
    result
  }

  /** Compute the same bounded plan without authorizing work beyond the work caps. */
  def estimate(keyCount: Long, cols: Int, rows: Int, spec: LocalEeConvolveSpec.Value): Plan = {
    require(keyCount > 0L && keyCount <= MaxSourceKeys,
      s"local_ee_convolve supports 1 to $MaxSourceKeys source tile keys")
    require(cols > 0 && rows > 0, "local_ee_convolve tile dimensions must be positive")
    val tileCells = Math.multiplyExact(cols.toLong, rows.toLong)
    require(tileCells <= MaxTileDecodedCells,
      s"local_ee_convolve tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    require(keyCount <= MaxDecodedCells / tileCells,
      s"local_ee_convolve exceeds the $MaxDecodedCells aggregate decoded-cell limit")

    val radius = spec.radius
    require(radius == 0 || radius < math.min(cols, rows),
      "local_ee_convolve positive neighborhood radius must be smaller than the smaller tile dimension")
    val bufferCols = Math.addExact(cols.toLong, Math.multiplyExact(2L, radius.toLong))
    val bufferRows = Math.addExact(rows.toLong, Math.multiplyExact(2L, radius.toLong))
    val bufferedCells = Math.multiplyExact(bufferCols, bufferRows)
    require(bufferedCells <= MaxTileDecodedCells,
      s"local_ee_convolve buffered tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    require(bufferedCells <= MaxDecodedCells / keyCount,
      s"local_ee_convolve exceeds the $MaxDecodedCells aggregate buffered-cell limit")

    val active = spec.active.length.toLong
    val limbs = spec.exactAccumulatorLimbs.toLong
    val perProductWork = Math.addExact(SignificandMultiplyLimbs, Math.multiplyExact(2L, limbs))
    // Each term allocates its shifted exact product, then scans the common-unit accumulator to add it.
    val productWork = Math.multiplyExact(active, perProductWork)
    val roundWork = if (active == 0L) 1L else Math.multiplyExact(limbs, 8L)
    val workPerPixel = Math.addExact(active, Math.addExact(productWork, roundWork))
    val perTileWork = Math.addExact(Math.multiplyExact(tileCells, workPerPixel), bufferedCells)
    Plan(keyCount, radius, bufferedCells, spec.unitExponent, spec.exactAccumulatorLimbs, perTileWork)
  }
}
