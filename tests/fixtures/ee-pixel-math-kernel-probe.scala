import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.raster.ArrayMultibandTile
import geotrellis.raster.DoubleArrayTile
import geotrellis.raster.DoubleConstantNoDataCellType
import geotrellis.raster.FloatArrayTile
import geotrellis.raster.FloatConstantNoDataCellType
import geotrellis.raster.MultibandTile
import geotrellis.raster.Tile
import java.io.File
import local.ee.math.LocalEePixelMathNumeric
import scala.jdk.CollectionConverters._

/** Trusted standalone actual-tile probe; it creates no SparkContext or service. */
object EePixelMathKernelProbe {
  private val Mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one pixel-math fixture")
    val root = Mapper.readTree(new File(args(0)))
    val operations = root.get("operations").fields().asScala.toVector
    operations.foreach { field =>
      val operation = field.getKey
      val expectedArity = field.getValue.intValue()
      val actualArity = LocalEePixelMathNumeric.arity(operation)
      require(actualArity == expectedArity,
        s"$operation arity mismatch: $actualArity != $expectedArity")
    }

    val cases = root.get("cases").elements().asScala.toVector
    var pixels = 0
    cases.foreach { row =>
      val operation = row.get("operation").asText()
      val bands = row.get("inputs").elements().asScala.map { band =>
        band.elements().asScala.map(parseValue).toArray
      }.toVector
      val expected = row.get("expected").elements().asScala.map(parseValue).toArray
      require(bands.length == LocalEePixelMathNumeric.arity(operation),
        s"$operation fixture band count")
      require(bands.forall(_.length == expected.length), s"$operation fixture dimensions")
      val input = ArrayMultibandTile(bands.map { values =>
        FloatArrayTile(values.map(_.toFloat), values.length, 1, FloatConstantNoDataCellType)
          .asInstanceOf[Tile]
      }.toArray)
      val output = LocalEePixelMathNumeric.applyTile(input, operation)
      require(output.cellType == FloatConstantNoDataCellType,
        s"$operation output must remain Float32 with NaN NoData")
      require(output.cols == expected.length && output.rows == 1,
        s"$operation output dimensions changed")

      val maxUlps = row.get("max_ulps").intValue()
      var index = 0
      while (index < expected.length) {
        val actual = output.getDouble(index, 0)
        val reference = expected(index)
        if (reference.isNaN) {
          require(actual.isNaN, s"$operation pixel $index expected NoData, got $actual")
        } else {
          require(java.lang.Double.isFinite(actual),
            s"$operation pixel $index expected finite $reference, got $actual")
          val actualBits = java.lang.Float.floatToRawIntBits(actual.toFloat)
          val referenceBits = java.lang.Float.floatToRawIntBits(reference.toFloat)
          // Commons Math Erf.erf(-0.0) yields +0.0; this contract checks zero signs for atan2 and signum.
          if (reference == 0.0 && (operation == "atan2" || operation == "signum")) {
            require(actualBits == referenceBits,
              s"$operation pixel $index changed signed zero: $actual != $reference")
          } else {
            val distance = Math.abs(ordered(actualBits) - ordered(referenceBits))
            require(distance <= maxUlps,
              s"$operation pixel $index differs by $distance Float32 ULPs: $actual vs $reference")
          }
        }
        index += 1
      }
      pixels += expected.length
    }

    var invalidChecks = 0
    val oneBand = floatBands(1, 1)
    val twoBands = floatBands(2, 1)
    requireRejected("unknown arity") { LocalEePixelMathNumeric.arity("notAnOperation") }
    invalidChecks += 1
    requireRejected("unknown tile operation") {
      LocalEePixelMathNumeric.applyTile(oneBand, "notAnOperation")
    }
    invalidChecks += 1
    requireRejected("unary operation with two bands") {
      LocalEePixelMathNumeric.applyTile(twoBands, "asin")
    }
    invalidChecks += 1
    requireRejected("binary operation with one band") {
      LocalEePixelMathNumeric.applyTile(oneBand, "atan2")
    }
    invalidChecks += 1

    val doubleInput: MultibandTile = ArrayMultibandTile(Array[Tile](
      DoubleArrayTile(Array(0.25), 1, 1, DoubleConstantNoDataCellType)
    ))
    requireRejected("non-Float32 input") {
      LocalEePixelMathNumeric.applyTile(doubleInput, "asin")
    }
    invalidChecks += 1

    val infiniteInput: MultibandTile = ArrayMultibandTile(Array[Tile](
      FloatArrayTile(Array(Float.PositiveInfinity), 1, 1, FloatConstantNoDataCellType)
    ))
    val infiniteOutput = LocalEePixelMathNumeric.applyTile(infiniteInput, "atan")
    require(infiniteOutput.getDouble(0, 0).isNaN,
      "nonfinite input value must become masked output")

    val operationCount = operations.length
    val caseCount = cases.length
    println(
      s"PIXEL_MATH_KERNEL_OK operations=$operationCount cases=$caseCount " +
        s"pixels=$pixels invalid_checks=$invalidChecks"
    )
  }

  private def floatBands(count: Int, cols: Int): MultibandTile = {
    ArrayMultibandTile(Array.fill(count) {
      FloatArrayTile(Array.fill(cols)(0.25f), cols, 1, FloatConstantNoDataCellType)
        .asInstanceOf[Tile]
    })
  }

  private def requireRejected(label: String)(body: => Any): Unit = {
    var rejected = false
    try body
    catch { case _: IllegalArgumentException => rejected = true }
    require(rejected, s"$label must reject")
  }

  private def parseValue(node: JsonNode): Double = {
    val text = node.asText()
    text match {
      case "NaN" => Double.NaN
      case "Infinity" => Double.PositiveInfinity
      case "-Infinity" => Double.NegativeInfinity
      case value => java.lang.Double.parseDouble(value)
    }
  }

  private def ordered(bits: Int): Long = {
    val unsigned = bits.toLong & 0xffffffffL
    if ((unsigned & 0x80000000L) != 0L)
      0x80000000L - (unsigned & 0x7fffffffL)
    else
      0x80000000L + unsigned
  }
}
