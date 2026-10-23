package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.raster.ArrayMultibandTile
import geotrellis.raster.DoubleArrayTile
import geotrellis.raster.DoubleConstantNoDataCellType
import geotrellis.raster.MultibandTile
import geotrellis.raster.Tile
import java.io.File
import scala.jdk.CollectionConverters._

/** Trusted standalone actual-Float64 tile probe; it creates no SparkContext or service. */
object EeReduceStatisticsKernelProbe {
  private val Mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one reducer-statistics fixture")
    val root = Mapper.readTree(new File(args(0)))
    val cases = root.get("cases").elements().asScala.toVector
    val reducers = cases.map(_.get("reducer").asText()).distinct
    var pixels = 0
    cases.foreach { row => pixels += checkCase(row) }

    val rejects = root.get("rejects").elements().asScala.toVector
    rejects.foreach(checkRejected)
    requireRejected("null reducer") {
      LocalEeReduceNumeric.reduceTile(tile(Array(Array(1d))), 1, 1, 1, null)
    }

    println(
      s"EE_REDUCE_STATISTICS_KERNEL_OK reducers=${reducers.size} cases=${cases.size} " +
        s"pixels=$pixels rejects=${rejects.size + 1} Float64=true noData=NaN"
    )
  }

  private def checkCase(row: JsonNode): Int = {
    val name = row.get("name").asText()
    val reducer = row.get("reducer").asText()
    val inputs = row.get("inputs").elements().asScala.map { band =>
      band.elements().asScala.map(parseValue).toArray
    }.toVector
    val expected = row.get("expected").elements().asScala.map(parseValue).toArray
    require(inputs.nonEmpty && inputs.forall(_.length == expected.length), s"$name fixture shape")
    val output = LocalEeReduceNumeric.reduceTile(tile(inputs.toArray), inputs.length, expected.length, 1, reducer)
    require(output.cellType == DoubleConstantNoDataCellType, s"$name must produce Float64 with NaN NoData")
    require(output.cols == expected.length && output.rows == 1, s"$name output dimensions changed")
    val maxUlps = row.get("max_ulps").intValue()
    val checkZeroSign = row.get("check_zero_sign").booleanValue()
    var index = 0
    while (index < expected.length) {
      val actual = output.getDouble(index, 0)
      val reference = expected(index)
      if (reference.isNaN) {
        require(actual.isNaN, s"$name pixel $index expected NoData, got $actual")
      } else {
        require(actual.isFinite, s"$name pixel $index expected finite $reference, got $actual")
        if (reference == 0d && checkZeroSign) {
          val actualBits = java.lang.Double.doubleToRawLongBits(actual)
          val expectedBits = java.lang.Double.doubleToRawLongBits(reference)
          require(actualBits == expectedBits,
            s"$name pixel $index changed signed zero: $actual != $reference")
        } else {
          val distance = (ordered(java.lang.Double.doubleToRawLongBits(actual)) -
            ordered(java.lang.Double.doubleToRawLongBits(reference))).abs
          require(distance <= maxUlps,
            s"$name pixel $index differs by $distance Float64 ULPs: $actual vs $reference")
        }
      }
      index += 1
    }
    expected.length
  }

  private def checkRejected(row: JsonNode): Unit = {
    val name = row.get("name").asText()
    val reducer = row.get("reducer").asText()
    val inputs = row.get("inputs").elements().asScala.map { band =>
      band.elements().asScala.map(parseValue).toArray
    }.toVector
    val columns = inputs.head.length
    require(inputs.forall(_.length == columns), s"$name reject fixture shape")
    requireRejected(name) {
      LocalEeReduceNumeric.reduceTile(tile(inputs.toArray), inputs.length, columns, 1, reducer)
    }
  }

  private def tile(bands: Array[Array[Double]]): MultibandTile = {
    ArrayMultibandTile(bands.map { values =>
      DoubleArrayTile(values, values.length, 1, DoubleConstantNoDataCellType).asInstanceOf[Tile]
    })
  }

  private def requireRejected(label: String)(body: => Any): Unit = {
    var rejected = false
    try body
    catch { case _: IllegalArgumentException => rejected = true }
    require(rejected, s"$label must reject")
  }

  private def parseValue(node: JsonNode): Double = node.asText() match {
    case "NaN" => Double.NaN
    case "Infinity" => Double.PositiveInfinity
    case "-Infinity" => Double.NegativeInfinity
    case value => java.lang.Double.parseDouble(value)
  }

  private def ordered(bits: Long): BigInt = {
    val sign = BigInt(1) << 63
    val magnitude = BigInt(bits & Long.MaxValue)
    if (bits < 0L) sign - magnitude else sign + magnitude
  }
}
