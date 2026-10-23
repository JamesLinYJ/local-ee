package local.ee.reduce

import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType,
  MultibandTile, Tile}

import java.io.File
import scala.jdk.CollectionConverters._

/** Actual GeoTrellis conditional-selection tile probe; no SparkContext or service. */
object EeSelectionKernelProbe {
  private val Mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one selection fixture")
    val root = Mapper.readTree(new File(args(0)))
    val cases = root.get("cases").elements().asScala.toVector
    var pixels = 0
    cases.foreach { row =>
      val input = tileFrom(row)
      val spec = LocalEeIntegerValuesSpec.parse(row.get("spec").asText())
      require(Set("select", "where_select")(spec.op) && spec.operands.length == 3,
        "fixture selection case must parse as a closed ternary selection")
      val expected = row.get("expected").elements().asScala.map(parseValue).toArray
      check(s"${row.get("name").asText()} direct",
        LocalEeFloat64Values.applyTile(input, spec), expected)
      check(s"${row.get("name").asText()} dispatcher",
        LocalEeIntegerValuesNumeric.applyTile(input, spec), expected)
      pixels += expected.length
    }

    var invalidSpecs = 0
    root.get("invalid_specs").elements().asScala.foreach { node =>
      var rejected = false
      try LocalEeIntegerValuesSpec.parse(node.asText())
      catch { case _: IllegalArgumentException => rejected = true }
      require(rejected, s"selection parser accepted malformed wire: ${node.asText()}")
      invalidSpecs += 1
    }

    var invalidTiles = 0
    root.get("invalid_tile_cases").elements().asScala.foreach { row =>
      var rejected = false
      try {
        val spec = LocalEeIntegerValuesSpec.parse(row.get("spec").asText())
        LocalEeIntegerValuesNumeric.applyTile(tileFrom(row), spec)
      } catch { case _: IllegalArgumentException => rejected = true }
      require(rejected, s"selection kernel accepted invalid tile ${row.get("name").asText()}")
      invalidTiles += 1
    }

    val operations = root.get("operations").elements().asScala.map(_.asText()).toVector
    require(operations == Vector("select", "where_select"),
      "fixture must declare select and where_select")
    operations.foreach { operation =>
      require(LocalEeFloat64Values.supports(operation), s"native kernel omitted $operation")
      require(LocalEeFloat64Values.arity(operation).contains(3),
        s"native $operation arity must be three")
      require(LocalEeFloat64Values.workWeight(operation).contains(3L),
        s"native $operation work weight must be three")
    }
    require(!LocalEeFloat64Values.supports("unknown") &&
      LocalEeFloat64Values.arity("unknown").isEmpty &&
      LocalEeFloat64Values.workWeight("unknown").isEmpty,
      "native selection kernel accepted an unknown operation")

    val declaredCases = root.get("case_count").intValue()
    val declaredPixels = root.get("pixel_count").intValue()
    require(cases.length == declaredCases && pixels == declaredPixels,
      "selection fixture summary counts do not match the cases")
    println(s"SELECTION_KERNEL_OK cases=${cases.length} pixels=$pixels " +
      s"invalid_specs=$invalidSpecs invalid_tiles=$invalidTiles operations=${operations.mkString(",")}")
  }

  private def tileFrom(row: JsonNode): MultibandTile = {
    require(row.get("input_type").asText() == "double",
      "selection fixture supports only Float64 source tiles")
    val bands = row.get("bands").elements().asScala.map { band =>
      val values = band.elements().asScala.map(parseValue).toArray
      require(values.nonEmpty, "selection fixture bands must not be empty")
      DoubleArrayTile(values, values.length, 1, DoubleConstantNoDataCellType)
    }.toArray
    require(bands.nonEmpty && bands.forall(_.cols == bands(0).cols),
      "selection fixture bands must have matching positive widths")
    ArrayMultibandTile(bands)
  }

  private def parseValue(node: JsonNode): Double = {
    val text = node.asText()
    text match {
      case "NaN" => Double.NaN
      case "Infinity" => Double.PositiveInfinity
      case "-Infinity" => Double.NegativeInfinity
      case encoded => java.lang.Double.parseDouble(encoded)
    }
  }

  private def check(label: String, tile: Tile, expected: Array[Double]): Unit = {
    require(tile.cellType == DoubleConstantNoDataCellType,
      s"$label output must be Float64 with NaN NoData, got ${tile.cellType}")
    require(tile.cols == expected.length && tile.rows == 1,
      s"$label changed the tile dimensions")
    var index = 0
    while (index < expected.length) {
      val actual = tile.getDouble(index, 0)
      val target = expected(index)
      val equal = if (actual.isNaN || target.isNaN) actual.isNaN && target.isNaN
      else java.lang.Double.doubleToRawLongBits(actual) ==
        java.lang.Double.doubleToRawLongBits(target)
      require(equal, s"$label pixel $index differs: actual=$actual expected=$target")
      index += 1
    }
  }
}
