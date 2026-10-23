package local.ee.reduce

import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}
import geotrellis.raster.{ArrayMultibandTile, ByteArrayTile, ByteCellType, DoubleArrayTile,
  DoubleConstantNoDataCellType, FloatConstantNoDataCellType, IntArrayTile,
  IntConstantNoDataCellType, MultibandTile, ShortArrayTile,
  ShortCellType, Tile, UByteArrayTile, UByteCellType, UShortArrayTile, UShortCellType}
import local.ee.integer.LocalEeCellConversion

import java.io.File
import scala.jdk.CollectionConverters._

/** Standalone trusted actual-tile probe. It creates no SparkContext or service. */
object EeIntegerValuesKernelProbe {
  private val Mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one integer-values fixture")
    val root = Mapper.readTree(new File(args(0)))
    var pixels = 0
    val cases = root.get("cases").elements().asScala.toVector
    cases.foreach { row =>
      val spec = LocalEeIntegerValuesSpec.parse(row.get("spec").asText())
      val input = tileFrom(row)
      val expected = row.get("expected").elements().asScala.map(parseValue).toArray
      val output = LocalEeIntegerValuesNumeric.applyTile(input, spec)
      require(output.cellType == DoubleConstantNoDataCellType,
        s"${row.get("name").asText()} output must be physical Float64 with NaN NoData")
      require(output.cols == expected.length && output.rows == 1,
        s"${row.get("name").asText()} output dimensions changed")
      var index = 0
      while (index < expected.length) {
        val actual = output.getDouble(index, 0)
        require(same(actual, expected(index)),
          s"${row.get("name").asText()} pixel $index differs: $actual != ${expected(index)}")
        index += 1
      }
      pixels += expected.length
    }

    val cellConversionChecks = verifyCellConversionControls()

    var invalidSpecs = 0
    root.get("invalid_specs").elements().asScala.foreach { node =>
      var rejected = false
      try LocalEeIntegerValuesSpec.parse(node.asText())
      catch { case _: IllegalArgumentException => rejected = true }
      require(rejected, s"native parser accepted malformed/noncanonical wire: ${node.asText()}")
      invalidSpecs += 1
    }

    var invalidTiles = 0
    root.get("invalid_tile_cases").elements().asScala.foreach { row =>
      var rejected = false
      try {
        val spec = LocalEeIntegerValuesSpec.parse(row.get("spec").asText())
        LocalEeIntegerValuesNumeric.applyTile(tileFrom(row), spec)
      } catch { case _: IllegalArgumentException => rejected = true }
      require(rejected, s"native kernel accepted invalid tile case ${row.get("name").asText()}")
      invalidTiles += 1
    }

    var maskedConstantRejects = 0
    root.get("masked_constant_cases").elements().asScala.foreach { row =>
      var rejected = false
      try {
        val spec = LocalEeIntegerValuesSpec.parse(row.get("spec").asText())
        LocalEeIntegerValuesNumeric.applyTile(tileFrom(row), spec)
      } catch { case _: IllegalArgumentException => rejected = true }
      require(rejected,
        s"invalid constant was skipped because every input pixel was masked: ${row.get("name").asText()}")
      maskedConstantRejects += 1
    }

    val qa = root.get("qa_composite")
    val qaInputs = qa.get("raw_scl").elements().asScala.map(parseValue).toArray
    val qaExpected = qa.get("expected_clear").elements().asScala.map(parseValue).toArray
    require(qaInputs.length == qaExpected.length, "QA raw-label oracle width mismatch")
    val raw = DoubleArrayTile(qaInputs, qaInputs.length, 1, DoubleConstantNoDataCellType)
    val specs = qa.get("specs")
    def single(tile: Tile): MultibandTile = ArrayMultibandTile(Array[Tile](tile))
    def run(tile: MultibandTile, name: String): Tile =
      LocalEeIntegerValuesNumeric.applyTile(tile,
        LocalEeIntegerValuesSpec.parse(specs.get(name).asText()))
    def check(stage: String, actual: Tile, expected: Array[Double]): Unit = {
      require(actual.cols == expected.length && actual.rows == 1,
        s"QA $stage changed the tile dimensions")
      var index = 0
      while (index < expected.length) {
        require(same(actual.getDouble(index, 0), expected(index)),
          s"QA $stage pixel $index differs from original-SCL reference: " +
            s"${actual.getDouble(index, 0)} != ${expected(index)}")
        index += 1
      }
    }
    def category(categoryValue: Double): Array[Double] = qaInputs.map { value =>
      if (value.isNaN) Double.NaN else if (value == categoryValue) 1.0d else 0.0d
    }
    val eq4 = run(single(raw), "eq4")
    check("eq4", eq4, category(4.0d))
    val shift10 = run(single(eq4), "shift10")
    check("left-shift-10", shift10, category(4.0d).map(_ * (1L << 10).toDouble))
    val eq5 = run(single(raw), "eq5")
    check("eq5", eq5, category(5.0d))
    val shift11 = run(single(eq5), "shift11")
    check("left-shift-11", shift11, category(5.0d).map(_ * (1L << 11).toDouble))
    val or45 = run(ArrayMultibandTile(Array[Tile](shift10, shift11)), "or45")
    check("bit-or-categories-4-5", or45, qaInputs.map { value =>
      if (value.isNaN) Double.NaN
      else ((if (value == 4.0d) 1L << 10 else 0L) |
        (if (value == 5.0d) 1L << 11 else 0L)).toDouble
    })
    val eq6 = run(single(raw), "eq6")
    check("eq6", eq6, category(6.0d))
    val shift40 = run(single(eq6), "shift40")
    check("left-shift-high-bit-40", shift40, category(6.0d).map(_ * (1L << 40).toDouble))
    val orHighbit = run(ArrayMultibandTile(Array[Tile](or45, shift40)), "or_highbit")
    check("bit-or-high-bit-variant", orHighbit, qaInputs.map { value =>
      if (value.isNaN) Double.NaN
      else ((if (value == 4.0d) 1L << 10 else 0L) |
        (if (value == 5.0d) 1L << 11 else 0L) |
        (if (value == 6.0d) 1L << 40 else 0L)).toDouble
    })
    val masked = run(single(orHighbit), "mask_bits")
    val mask = (1L << 40) | (1L << 11) | (1L << 10)
    check("bit-and-QA-mask", masked, qaInputs.map { value =>
      if (value.isNaN) Double.NaN
      else (((if (value == 4.0d) 1L << 10 else 0L) |
        (if (value == 5.0d) 1L << 11 else 0L) |
        (if (value == 6.0d) 1L << 40 else 0L)) & mask).toDouble
    })
    val clear = run(single(masked), "eq_zero")
    check("eq-zero-final-mask", clear, qaExpected)

    val operationCount = root.get("operation_count").intValue()
    require(operationCount == 14, s"expected all 14 declared operations, got $operationCount")
    println(s"INTEGER_VALUES_KERNEL_OK cases=${cases.length} pixels=$pixels " +
      s"invalid_specs=$invalidSpecs invalid_tiles=$invalidTiles " +
      s"masked_constant_rejects=$maskedConstantRejects operations=$operationCount " +
      s"qa_steps=${qa.get("steps").size()} qa_pixels=${qaInputs.length} " +
      s"cell_conversion_checks=$cellConversionChecks")
  }

  private def verifyCellConversionControls(): Int = {
    val userDefined = IntArrayTile(Array(Int.MinValue, 0, 17), 3, 1, 0)
    require(userDefined.getDouble(0, 0) == Int.MinValue.toDouble &&
      userDefined.getDouble(1, 0).isNaN,
      "user-defined Int NoData source fixture must preserve Int.MinValue and mask only 0")
    val userMulti = ArrayMultibandTile(Array[Tile](userDefined))
    val asDouble = LocalEeCellConversion.toDouble(userMulti).band(0)
    checkTile("user-defined-int-to-double", asDouble,
      Array(Int.MinValue.toDouble, Double.NaN, 17.0d))
    val asFloat = LocalEeCellConversion.toFloat(userMulti).band(0)
    require(asFloat.cellType == FloatConstantNoDataCellType,
      "integer-to-Float32 conversion must use NaN NoData")
    checkTile("user-defined-int-to-float", asFloat,
      Array(Int.MinValue.toDouble, Double.NaN, 17.0d))

    val bitNot = LocalEeIntegerValuesSpec.parse(
      "{\"dtype\":null,\"op\":\"bit_not\",\"operands\":[{\"band\":0}],\"v\":1}")
    val userKernel = LocalEeIntegerValuesNumeric.applyTile(userMulti, bitNot)
    checkTile("user-defined-int-through-integer-kernel", userKernel,
      Array(Int.MaxValue.toDouble, Double.NaN, -18.0d))

    val constantNoData = IntArrayTile(Array(Int.MinValue, 17), 2, 1,
      IntConstantNoDataCellType)
    require(constantNoData.getDouble(0, 0).isNaN,
      "constant Int.MinValue NoData source fixture must expose a real mask")
    val constantMulti = ArrayMultibandTile(Array[Tile](constantNoData))
    val trueNoDataDouble = LocalEeCellConversion.toDouble(constantMulti).band(0)
    checkTile("constant-int-nodata-to-double", trueNoDataDouble,
      Array(Double.NaN, 17.0d))
    val noDataKernel = LocalEeIntegerValuesNumeric.applyTile(constantMulti, bitNot)
    checkTile("constant-int-nodata-through-integer-kernel", noDataKernel,
      Array(Double.NaN, -18.0d))
    return 5
  }

  private def checkTile(label: String, tile: Tile, expected: Array[Double]): Unit = {
    require(tile.cols == expected.length && tile.rows == 1,
      s"$label changed tile dimensions")
    var index = 0
    while (index < expected.length) {
      require(same(tile.getDouble(index, 0), expected(index)),
        s"$label pixel $index differs: ${tile.getDouble(index, 0)} != ${expected(index)}")
      index += 1
    }
  }

  private def tileFrom(row: JsonNode): MultibandTile = {
    val inputType = row.get("input_type").asText()
    val bands = row.get("bands").elements().asScala.map { band =>
      val values = band.elements().asScala.map(parseValue).toArray
      require(values.nonEmpty, "fixture bands must not be empty")
      val width = values.length
      val tile: Tile = inputType match {
        case "double" => DoubleArrayTile(values, width, 1, DoubleConstantNoDataCellType)
        case "byte" => ByteArrayTile(values.map(checkedInteger(_, -128, 127).toByte),
          width, 1, ByteCellType)
        case "ubyte" => UByteArrayTile(values.map(checkedInteger(_, 0, 255).toByte),
          width, 1, UByteCellType)
        case "short" => ShortArrayTile(values.map(checkedInteger(_, -32768, 32767).toShort),
          width, 1, ShortCellType)
        case "ushort" => UShortArrayTile(values.map(checkedInteger(_, 0, 65535).toShort),
          width, 1, UShortCellType)
        // Use a distinct user-defined sentinel so Int.MinValue is a valid source value.
        case "int" => IntArrayTile(values.map(checkedInteger(_, Int.MinValue, Int.MaxValue).toInt),
          width, 1, 0)
        case other => throw new IllegalArgumentException(s"unsupported fixture input type: $other")
      }
      var index = 0
      while (index < width) {
        val actual = tile.getDouble(index, 0)
        require(same(actual, values(index)),
          s"$inputType fixture construction lost source cell $index: $actual != ${values(index)}")
        index += 1
      }
      tile
    }.toArray
    require(bands.nonEmpty && bands.forall(_.cols == bands(0).cols),
      "fixture bands must have matching positive widths")
    ArrayMultibandTile(bands)
  }

  private def checkedInteger(value: Double, minimum: Double, maximum: Double): Long = {
    require(value.isFinite && value == Math.rint(value) && value >= minimum && value <= maximum,
      s"typed fixture cell is not an integer in $minimum..$maximum: $value")
    value.toLong
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
