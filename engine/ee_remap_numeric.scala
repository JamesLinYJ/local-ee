package local.ee.remap

import com.fasterxml.jackson.core.{JsonFactory, JsonParser}
import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}
import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}

import scala.jdk.CollectionConverters._

/** Bounded remap specification and exact binary64-value tile kernel. */
final class LocalEeRemapSpec private[remap] (val from: Vector[Double], val to: Vector[Double],
                                              val defaultValue: Option[Double]) extends Serializable

object LocalEeRemapNumeric {
  private val Fields = Set("version", "from", "to", "default")
  private val MaxSpecBytes = 1000000
  private val MaxValues = 256
  private val MaxExactInteger = BigInt(1) << 53
  private val Factory: JsonFactory = {
    val factory = new JsonFactory()
    factory.enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
    factory
  }
  private val Mapper = new ObjectMapper(Factory)

  /** Independently parse and validate the closed version-1 process specification. */
  def parseSpec(text: String): LocalEeRemapSpec = {
    require(text != null, "remap spec must be a string")
    require(text.length <= MaxSpecBytes, "remap spec exceeds the 1 MB character limit")
    require(text.getBytes(java.nio.charset.StandardCharsets.UTF_8).length <= MaxSpecBytes,
      "remap spec exceeds the 1 MB limit")
    val parser = Factory.createParser(text)
    val root = try {
      try {
        val parsed = Mapper.readTree[JsonNode](parser)
        require(parser.nextToken() == null, "remap spec must contain exactly one JSON value")
        parsed
      } catch {
        case error: IllegalArgumentException => throw error
        case error: java.io.IOException => throw new IllegalArgumentException("remap spec must be valid JSON", error)
      }
    } finally parser.close()
    require(root != null && root.isObject, "remap spec must be a JSON object")
    require(root.fieldNames().asScala.toSet == Fields && root.size() == Fields.size,
      "remap spec must contain exactly version, from, to and default")
    val version = root.get("version")
    require(version.isIntegralNumber && version.canConvertToInt && version.intValue() == 1,
      "remap spec version must be integer 1")
    val from = numberArray(root.get("from"), "from")
    val to = numberArray(root.get("to"), "to")
    require(from.length == to.length, "remap from and to arrays must have equal length")
    val seen = scala.collection.mutable.HashSet.empty[Long]
    from.foreach { value =>
      val bits = if (value == 0.0) 0L else java.lang.Double.doubleToRawLongBits(value)
      require(seen.add(bits), "remap from values must be numerically unique")
    }
    val defaultNode = root.get("default")
    val defaultValue = if (defaultNode.isNull) None else Some(finiteNumber(defaultNode, "default"))
    new LocalEeRemapSpec(from, to, defaultValue)
  }

  /** Remap one input value. NaN is NoData and is never filled by the default. */
  def remapValue(input: Double, spec: LocalEeRemapSpec): Double = {
    require(spec != null, "remap spec must be present")
    if (input.isNaN) return Double.NaN
    require(input.isFinite, "valid remap input pixels must be finite")
    var index = 0
    while (index < spec.from.length) {
      if (input == spec.from(index)) return spec.to(index)
      index += 1
    }
    spec.defaultValue.getOrElse(Double.NaN)
  }

  /** Public pure GeoTrellis tile entry point; converts only after reading source precision. */
  def remapTile(tile: MultibandTile, spec: LocalEeRemapSpec): Tile = {
    require(tile != null && tile.bandCount == 1, "remap tile must contain exactly one band")
    require(spec != null, "remap spec must be present")
    val source = tile.band(0).convert(DoubleConstantNoDataCellType)
    val output = Array.fill(Math.multiplyExact(tile.cols, tile.rows))(Double.NaN)
    var row = 0
    while (row < tile.rows) {
      var col = 0
      while (col < tile.cols) {
        output(row * tile.cols + col) = remapValue(source.getDouble(col, row), spec)
        col += 1
      }
      row += 1
    }
    DoubleArrayTile(output, tile.cols, tile.rows, DoubleConstantNoDataCellType)
  }

  private def numberArray(node: JsonNode, name: String): Vector[Double] = {
    require(node != null && node.isArray && node.size() <= MaxValues,
      s"remap $name must be an array with at most $MaxValues values")
    node.elements().asScala.map(value => finiteNumber(value, s"remap $name entry")).toVector
  }

  private def finiteNumber(node: JsonNode, name: String): Double = {
    require(node != null && node.isNumber, s"$name must be a finite numeric scalar")
    val decimal = try node.decimalValue() catch {
      case error: NumberFormatException => throw new IllegalArgumentException(s"$name is outside the numeric domain", error)
    }
    if (node.isIntegralNumber)
      require(decimal.abs().compareTo(new java.math.BigDecimal(MaxExactInteger.bigInteger)) <= 0,
        s"integer $name exceeds the exact 2^53 limit")
    val value = node.doubleValue()
    require(value.isFinite, s"$name must be finite binary64")
    require(decimal.signum() == 0 || value != 0.0,
      s"nonzero $name underflows the binary64 numeric domain")
    value
  }
}
