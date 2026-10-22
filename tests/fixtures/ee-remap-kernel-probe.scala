import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType,
  FloatArrayTile, FloatConstantNoDataCellType, MultibandTile, Tile}
import local.ee.remap.LocalEeRemapNumeric

import java.io.File
import scala.jdk.CollectionConverters._

/** Trusted standalone actual-GeoTrellis kernel probe; creates no SparkContext. */
object EeRemapKernelProbe {
  private val Mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one remap case file")
    val root = Mapper.readTree(new File(args(0)))
    var checked = 0
    root.get("cases").elements().asScala.foreach { row =>
      val spec = LocalEeRemapNumeric.parseSpec(row.get("spec").asText())
      val inputType = row.get("input_type").asText()
      val inputs = row.get("input").elements().asScala.map(parseValue).toArray
      val expected = row.get("expected").elements().asScala.map(parseValue).toArray
      val source: Tile = inputType match {
        case "float64" => DoubleArrayTile(inputs, inputs.length, 1, DoubleConstantNoDataCellType)
        case "float32" => FloatArrayTile(inputs.map(_.toFloat), inputs.length, 1, FloatConstantNoDataCellType)
        case other => throw new IllegalArgumentException(s"unsupported probe input type: $other")
      }
      val input: MultibandTile = ArrayMultibandTile(Array[Tile](source))
      val output = LocalEeRemapNumeric.remapTile(input, spec)
      require(output.cellType == DoubleConstantNoDataCellType, "remap output must be physical Float64 NoData")
      require(output.cols == inputs.length && output.rows == 1, "remap changed tile dimensions")
      var index = 0
      while (index < expected.length) {
        val actual = output.getDouble(index, 0)
        require(same(actual, expected(index)),
          s"case ${row.get("name").asText()} index $index mismatch: $actual != ${expected(index)}")
        index += 1
      }
      checked += 1
    }

    var invalidSpecs = 0
    root.get("invalid_specs").elements().asScala.foreach { node =>
      var rejected = false
      try LocalEeRemapNumeric.parseSpec(node.asText())
      catch { case _: IllegalArgumentException => rejected = true }
      require(rejected, s"native parser accepted invalid remap spec: ${node.asText()}")
      invalidSpecs += 1
    }

    var invalidPixels = 0
    val valid = LocalEeRemapNumeric.parseSpec("{\"version\":1,\"from\":[],\"to\":[],\"default\":null}")
    Seq(Double.PositiveInfinity, Double.NegativeInfinity).foreach { value =>
      var rejected = false
      try LocalEeRemapNumeric.remapValue(value, valid)
      catch { case _: IllegalArgumentException => rejected = true }
      require(rejected, "native kernel accepted a valid infinite input pixel")
      invalidPixels += 1
    }
    val infiniteTile = ArrayMultibandTile(Array[Tile](
      DoubleArrayTile(Array(Double.PositiveInfinity), 1, 1, DoubleConstantNoDataCellType)))
    var tileRejected = false
    try LocalEeRemapNumeric.remapTile(infiniteTile, valid)
    catch { case _: IllegalArgumentException => tileRejected = true }
    require(tileRejected, "native tile kernel accepted a valid infinite input pixel")
    invalidPixels += 1
    println(s"REMAP_KERNEL_OK cases=$checked invalid_specs=$invalidSpecs invalid_pixels=$invalidPixels")
  }

  private def parseValue(node: JsonNode): Double = {
    val text = node.asText()
    text match {
      case "NaN" => Double.NaN
      case "Infinity" => Double.PositiveInfinity
      case "-Infinity" => Double.NegativeInfinity
      case value => java.lang.Double.valueOf(value)
    }
  }

  private def same(left: Double, right: Double): Boolean =
    if (left.isNaN && right.isNaN) true
    else java.lang.Double.doubleToRawLongBits(left) == java.lang.Double.doubleToRawLongBits(right)
}
