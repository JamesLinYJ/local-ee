package local.ee.smile

import com.fasterxml.jackson.core.{JsonFactory, JsonParser, JsonToken}
import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}

import scala.jdk.CollectionConverters._

private[smile] final case class LocalEeSmileRfSpec(
  schema: Vector[String], classProperty: String, trees: Int, mtry: Int,
  minLeaf: Int, bagFraction: Double, maxNodes: Option[Int], seed: Int
) extends Serializable {
  def effectiveMaxNodes(rows: Int): Int = math.min(rows, maxNodes.getOrElse(rows))
}

private[smile] final case class LocalEeSmileRfRows(x: Array[Array[Double]], y: Array[Int])

/** Independent, bounded parser for the Python-owned canonical training wires. */
private[smile] object LocalEeSmileRfWire {
  private val SpecFields = Set(
    "version", "implementation", "schema", "class_property", "number_of_trees",
    "variables_per_split", "min_leaf_population", "bag_fraction", "max_nodes", "seed"
  )
  private val RowFields = Set("version", "rows")
  private val MaxSpecBytes = 16384
  private val MaxRowsBytes = 1000000
  private val MaxJsonTokens = 50000
  private val MaxNameChars = 256
  private val MaxNumberChars = 128
  private val MaxClasses = 64
  private val MaxRows = 1000
  private val MaxTrainingWork = 1000000000L
  private val MaxWireCells = 50000L
  private val MaxIntFeature = BigInt(1) << 53
  private val MaxTrainMagnitude = Double.MaxValue / 2.0
  private val Factory: JsonFactory = {
    val value = new JsonFactory()
    value.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    value
  }
  private val Mapper = new ObjectMapper(Factory)

  def parseSpec(text: String): LocalEeSmileRfSpec = {
    val root = parseCanonical(text, MaxSpecBytes, "Random forest specification")
    require(root != null && root.isObject && fieldNames(root) == SpecFields,
      "Random forest spec must contain exactly the version1 Smile1.5.3 fields")
    require(integer(root.get("version"), "spec version", 1, 1) == 1,
      "Random forest spec version must be integer 1")
    require(textValue(root.get("implementation"), "implementation") == "smile-1.5.3",
      "Random forest implementation must be smile-1.5.3")

    val schema = nameArray(root.get("schema"), 1, 8, "schema")
    val classProperty = name(root.get("class_property"), "class_property")
    require(!(schema.toSet + classProperty).intersect(Set("system:index", ".geo")).nonEmpty,
      "Random forest schema and class_property must name numeric properties")
    val trees = integer(root.get("number_of_trees"), "number_of_trees", 1, 256)
    val minLeaf = integer(root.get("min_leaf_population"), "min_leaf_population", 1, MaxRows)
    val seed = integer(root.get("seed"), "seed", Int.MinValue, Int.MaxValue)
    val mtryNode = root.get("variables_per_split")
    val mtry = if (mtryNode.isNull) math.floor(math.sqrt(schema.size)).toInt
      else integer(mtryNode, "variables_per_split", 1, schema.size)
    val bagNode = root.get("bag_fraction")
    require(bagNode != null && bagNode.isNumber, "Random forest bag_fraction must be numeric")
    val bag = bagNode.doubleValue()
    require(bag.isFinite && bag > 0.0 && bag <= 1.0,
      "Random forest bag_fraction must be finite and in (0,1]")
    val maxNode = root.get("max_nodes")
    val maxNodes = if (maxNode.isNull) None
      else Some(integer(maxNode, "max_nodes", 2, MaxRows))
    new LocalEeSmileRfSpec(schema, classProperty, trees, mtry, minLeaf, bag, maxNodes, seed)
  }

  def parseRows(text: String, spec: LocalEeSmileRfSpec): LocalEeSmileRfRows = {
    require(spec != null, "Random forest spec must be present")
    val root = parseCanonical(text, MaxRowsBytes, "Random forest rows")
    require(root != null && root.isObject && fieldNames(root) == RowFields,
      "Random forest rows must contain exactly version1 and rows")
    require(integer(root.get("version"), "rows version", 1, 1) == 1,
      "Random forest rows version must be integer 1")
    val rowNodes = root.get("rows")
    require(rowNodes != null && rowNodes.isArray && rowNodes.size() >= 2 && rowNodes.size() <= MaxRows,
      s"Random forest training requires 2..$MaxRows rows")
    val count = rowNodes.size()
    val wireCells = Math.multiplyExact(count.toLong, spec.schema.length.toLong)
    require(wireCells <= MaxWireCells, s"Random forest rows exceed the $MaxWireCells wire-cell budget")
    val leaves = spec.effectiveMaxNodes(count)
    val work = Math.multiplyExact(Math.multiplyExact(Math.multiplyExact(count.toLong, spec.trees.toLong),
      spec.schema.length.toLong), leaves.toLong)
    require(work <= MaxTrainingWork,
      s"Random forest exceeds the $MaxTrainingWork training-work budget")

    val x = new Array[Array[Double]](count)
    val y = new Array[Int](count)
    var rowIndex = 0
    while (rowIndex < count) {
      val row = rowNodes.get(rowIndex)
      require(row.isArray && row.size() == 2 && row.get(1).isArray &&
        row.get(1).size() == spec.schema.size,
        "Each training row must contain a label and schema-ordered feature vector")
      y(rowIndex) = integer(row.get(0), "class label", 0, MaxClasses - 1)
      val vector = row.get(1)
      x(rowIndex) = new Array[Double](spec.schema.size)
      var column = 0
      while (column < spec.schema.size) {
        x(rowIndex)(column) = trainingNumber(vector.get(column), rowIndex, column)
        column += 1
      }
      rowIndex += 1
    }
    val labels = y.distinct.sorted
    require(labels.length >= 2 && labels.length <= MaxClasses && labels.sameElements(labels.indices),
      "Random forest requires 2..64 contiguous class labels starting at 0")
    LocalEeSmileRfRows(x, y)
  }

  private def parseCanonical(text: String, maxBytes: Int, name: String): JsonNode = {
    require(text != null && text.length <= maxBytes,
      s"$name exceeds the $maxBytes character limit")
    require(text.getBytes(java.nio.charset.StandardCharsets.UTF_8).length <= maxBytes,
      s"$name exceeds the $maxBytes UTF-8 byte limit")
    scanBounded(text, name)
    val parser = Factory.createParser(text)
    try {
      val root = Mapper.readTree[JsonNode](parser)
      require(parser.nextToken() == null, s"$name must contain exactly one JSON value")
      require(root != null && canonicalJson(root) == text, s"$name must use canonical JSON")
      root
    } catch {
      case error: IllegalArgumentException => throw error
      case error: java.io.IOException => throw new IllegalArgumentException(s"$name must be valid JSON", error)
    } finally parser.close()
  }

  private def scanBounded(text: String, name: String): Unit = {
    val parser = Factory.createParser(text)
    var depth = 0
    var count = 0
    try {
      var token = parser.nextToken()
      while (token != null) {
        count = Math.addExact(count, 1)
        require(count <= MaxJsonTokens, s"$name exceeds the JSON token budget")
        token match {
          case JsonToken.START_OBJECT | JsonToken.START_ARRAY =>
            depth += 1
            require(depth <= 4, s"$name has excessive JSON nesting")
          case JsonToken.END_OBJECT | JsonToken.END_ARRAY => depth -= 1
          case JsonToken.FIELD_NAME | JsonToken.VALUE_STRING =>
            val value = parser.getText
            require(value.codePointCount(0, value.length) <= MaxNameChars,
              s"$name contains an oversized string")
          case JsonToken.VALUE_NUMBER_INT | JsonToken.VALUE_NUMBER_FLOAT =>
            require(parser.getText.length <= MaxNumberChars, s"$name contains an oversized number")
          case _ => ()
        }
        token = parser.nextToken()
      }
      require(depth == 0, s"$name has unbalanced JSON structure")
    } catch {
      case error: IllegalArgumentException => throw error
      case error: java.io.IOException => throw new IllegalArgumentException(s"$name must be valid JSON", error)
    } finally parser.close()
  }

  private def canonicalJson(node: JsonNode): String = {
    if (node.isObject) {
      val fields = node.fields().asScala.toVector.sortBy(_.getKey)
      fields.iterator.map(entry => quote(entry.getKey) + ":" + canonicalJson(entry.getValue))
        .mkString("{", ",", "}")
    } else if (node.isArray) {
      node.elements().asScala.iterator.map(canonicalJson).mkString("[", ",", "]")
    } else if (node.isTextual) quote(node.textValue())
    else if (node.isIntegralNumber) node.bigIntegerValue().toString
    else if (node.isFloatingPointNumber) pythonFloat(node.doubleValue())
    else if (node.isBoolean) node.booleanValue().toString
    else if (node.isNull) "null"
    else throw new IllegalArgumentException("Random forest JSON contains an unsupported value")
  }

  private def pythonFloat(value: Double): String = {
    require(value.isFinite, "Random forest JSON numbers must be finite")
    val bits = java.lang.Double.doubleToRawLongBits(value)
    if (value == 0.0) return if (bits < 0L) "-0.0" else "0.0"
    val sign = if (bits < 0L) "-" else ""
    val magnitude = math.abs(value)
    // Python and Java choose different shortest spellings for the minimum subnormal.
    if (magnitude == java.lang.Double.MIN_VALUE) return sign + "5e-324"
    val decimal = new java.math.BigDecimal(java.lang.Double.toString(magnitude)).stripTrailingZeros()
    val exponent = decimal.precision() - decimal.scale() - 1
    if (exponent >= -4 && exponent < 16) {
      val plain = decimal.toPlainString
      sign + (if (magnitude == math.rint(magnitude) && !plain.contains(".")) plain + ".0" else plain)
    } else {
      val digits = decimal.unscaledValue().abs().toString
      val coefficient = if (digits.length == 1) digits else digits.head + "." + digits.substring(1)
      val exponentText = if (exponent < 0) {
        val magnitudeText = -exponent
        if (magnitudeText < 10) s"-0$magnitudeText" else s"-$magnitudeText"
      } else if (exponent < 10) s"+0$exponent" else s"+$exponent"
      sign + coefficient + "e" + exponentText
    }
  }

  private def quote(value: String): String = {
    val output = new StringBuilder(value.length + 2).append('"')
    var index = 0
    while (index < value.length) {
      val character = value.charAt(index)
      character match {
        case '"' => output.append("\\\"")
        case '\\' => output.append("\\\\")
        case '\b' => output.append("\\b")
        case '\t' => output.append("\\t")
        case '\n' => output.append("\\n")
        case '\f' => output.append("\\f")
        case '\r' => output.append("\\r")
        case control if control < ' ' =>
          output.append("\\u")
          val hex = Integer.toHexString(control.toInt)
          output.append("0" * (4 - hex.length)).append(hex)
        case printable => output.append(printable)
      }
      index += 1
    }
    output.append('"').toString
  }

  private def fieldNames(node: JsonNode): Set[String] = node.fieldNames().asScala.toSet

  private def nameArray(node: JsonNode, minimum: Int, maximum: Int, label: String): Vector[String] = {
    require(node != null && node.isArray && node.size() >= minimum && node.size() <= maximum,
      s"Random forest $label must contain $minimum..$maximum names")
    val result = node.elements().asScala.map(value => name(value, label)).toVector
    require(result.distinct.size == result.size, s"Random forest $label names must be unique")
    result
  }

  private def name(node: JsonNode, label: String): String = {
    require(node != null && node.isTextual, s"Random forest $label must be a string")
    val value = node.textValue()
    require(value.nonEmpty && value.codePointCount(0, value.length) <= MaxNameChars && !value.contains("."),
      s"Random forest $label must be a flat nonempty name of at most $MaxNameChars characters")
    require(validUnicode(value), s"Random forest $label must contain valid Unicode scalar values")
    value
  }

  private def validUnicode(value: String): Boolean = {
    var index = 0
    while (index < value.length) {
      val current = value.charAt(index)
      if (Character.isHighSurrogate(current)) {
        if (index + 1 >= value.length || !Character.isLowSurrogate(value.charAt(index + 1))) return false
        index += 2
      } else {
        if (Character.isLowSurrogate(current)) return false
        index += 1
      }
    }
    true
  }

  private def textValue(node: JsonNode, label: String): String = {
    require(node != null && node.isTextual, s"Random forest $label must be a string")
    node.textValue()
  }

  private def integer(node: JsonNode, label: String, minimum: Int, maximum: Int): Int = {
    require(node != null && node.isIntegralNumber && node.canConvertToInt,
      s"Random forest $label must be an integer")
    val value = node.intValue()
    require(value >= minimum && value <= maximum,
      s"Random forest $label must be in $minimum..$maximum")
    value
  }

  private def trainingNumber(node: JsonNode, row: Int, column: Int): Double = {
    require(node != null && node.isNumber, s"Random forest row $row feature $column must be numeric")
    if (node.isIntegralNumber) {
      val integer = BigInt(node.bigIntegerValue())
      require(integer.abs <= MaxIntFeature,
        "Random forest integer inputs must lie within the exact 2^53 domain")
    }
    val value = node.doubleValue()
    require(value.isFinite, s"Random forest row $row feature $column must be finite")
    require(math.abs(value) <= MaxTrainMagnitude,
      s"Random forest row $row feature $column exceeds the finite split-threshold domain")
    value
  }
}
