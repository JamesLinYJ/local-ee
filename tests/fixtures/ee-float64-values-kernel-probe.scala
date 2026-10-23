package local.ee.reduce

import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType,
  IntArrayTile, IntConstantNoDataCellType, MultibandTile, Tile}

import java.io.File
import scala.jdk.CollectionConverters._

/** Actual GeoTrellis Float64 tile probe. It starts no SparkContext or provider service. */
object EeFloat64ValuesKernelProbe {
  private val Mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one Float64-values fixture")
    val root = Mapper.readTree(new File(args(0)))
    val cases = root.get("cases").elements().asScala.toVector
    var pixels = 0
    var maxObservedUlps = BigInt(0)
    cases.foreach { row =>
      val input = tileFrom(row)
      val spec = LocalEeIntegerValuesSpec.parse(row.get("spec").asText())
      val expected = row.get("expected").elements().asScala.map(parseValue).toArray
      val tolerance = row.get("tolerance_ulps").intValue()
      val directDistance = check(s"${row.get("name").asText()} direct",
        LocalEeFloat64Values.applyTile(input, spec), expected, tolerance)
      val dispatcherDistance = check(s"${row.get("name").asText()} dispatcher",
        LocalEeIntegerValuesNumeric.applyTile(input, spec), expected, tolerance)
      maxObservedUlps = maxObservedUlps.max(directDistance).max(dispatcherDistance)
      pixels += expected.length
    }

    var invalidSpecs = 0
    root.get("invalid_specs").elements().asScala.foreach { node =>
      var rejected = false
      try LocalEeIntegerValuesSpec.parse(node.asText())
      catch { case _: IllegalArgumentException => rejected = true }
      require(rejected, s"Float64 parser accepted malformed/noncanonical wire: ${node.asText()}")
      invalidSpecs += 1
    }

    var invalidTiles = 0
    root.get("invalid_tile_cases").elements().asScala.foreach { row =>
      var rejected = false
      try {
        val spec = LocalEeIntegerValuesSpec.parse(row.get("spec").asText())
        LocalEeIntegerValuesNumeric.applyTile(tileFrom(row), spec)
      } catch { case _: IllegalArgumentException => rejected = true }
      require(rejected, s"Float64 kernel accepted invalid tile ${row.get("name").asText()}")
      invalidTiles += 1
    }

    val operations = root.get("operations").elements().asScala.map(_.asText()).toVector
    require(operations.length == 22 && operations.distinct.length == 22,
      "fixture must declare 22 unique Float64 operations")
    val binaryOperations = Set("add", "subtract", "multiply", "divide", "power", "mod",
      "min2", "max2", "and", "or")
    val highWork = Set("power", "sqrt", "log", "log10", "exp", "sin", "cos", "tan")
    val mediumWork = Set("divide", "mod", "round", "floor", "ceil")
    operations.foreach { operation =>
      val expectedArity = if (binaryOperations(operation)) 2 else 1
      val expectedWeight = if (highWork(operation)) 32L else if (mediumWork(operation)) 4L else 1L
      require(LocalEeFloat64Values.supports(operation), s"native kernel omitted $operation")
      require(LocalEeFloat64Values.arity(operation).contains(expectedArity),
        s"native arity for $operation is not $expectedArity")
      require(LocalEeFloat64Values.workWeight(operation).contains(expectedWeight),
        s"native work weight for $operation is not $expectedWeight")
    }
    require(!LocalEeFloat64Values.supports("unknown") &&
      LocalEeFloat64Values.arity("unknown").isEmpty &&
      LocalEeFloat64Values.workWeight("unknown").isEmpty,
      "native kernel accepted an unsupported operation")

    val composites = root.get("composites")
    val compositePixels = verifyThermal(composites.get("thermal_celsius_to_kelvin")) +
      verifyNdvi(composites.get("ndvi_float64")) +
      verifyQaArithmetic(composites.get("qa_integer_result_arithmetic"))
    val compositeStages = 6
    println(s"FLOAT64_VALUES_KERNEL_OK cases=${cases.length} pixels=$pixels " +
      s"invalid_specs=$invalidSpecs invalid_tiles=$invalidTiles operations=22 " +
      s"max_observed_ulps=$maxObservedUlps " +
      s"composite_stages=$compositeStages composite_pixels=$compositePixels")
  }

  private def verifyThermal(node: JsonNode): Int = {
    val raw = node.get("raw_celsius").elements().asScala.map(parseValue).toArray
    val expected = node.get("expected_kelvin").elements().asScala.map(parseValue).toArray
    val spec = LocalEeIntegerValuesSpec.parse(node.get("spec").asText())
    check("thermal Celsius-to-Kelvin", LocalEeIntegerValuesNumeric.applyTile(single(doubleTile(raw)), spec),
      expected, 0)
    raw.length
  }

  private def verifyNdvi(node: JsonNode): Int = {
    val red = node.get("red").elements().asScala.map(parseValue).toArray
    val nir = node.get("nir").elements().asScala.map(parseValue).toArray
    require(red.length == nir.length, "NDVI input band widths differ")
    val input = ArrayMultibandTile(Array[Tile](doubleTile(red), doubleTile(nir)))
    val specs = node.get("specs")
    val numerator = LocalEeIntegerValuesNumeric.applyTile(input,
      LocalEeIntegerValuesSpec.parse(specs.get("numerator").asText()))
    val denominator = LocalEeIntegerValuesNumeric.applyTile(input,
      LocalEeIntegerValuesSpec.parse(specs.get("denominator").asText()))
    check("NDVI numerator", numerator,
      node.get("expected_numerator").elements().asScala.map(parseValue).toArray, 0)
    check("NDVI denominator", denominator,
      node.get("expected_denominator").elements().asScala.map(parseValue).toArray, 0)
    val ratio = LocalEeIntegerValuesNumeric.applyTile(
      ArrayMultibandTile(Array[Tile](numerator, denominator)),
      LocalEeIntegerValuesSpec.parse(specs.get("divide").asText()))
    check("Float64 NDVI ratio and intersected masks", ratio,
      node.get("expected_ndvi").elements().asScala.map(parseValue).toArray, 0)
    3 * red.length
  }

  private def verifyQaArithmetic(node: JsonNode): Int = {
    val raw = node.get("raw_qa").elements().asScala.map(parseValue).toArray
    val integerResult = LocalEeIntegerValuesNumeric.applyTile(single(doubleTile(raw)),
      LocalEeIntegerValuesSpec.parse(node.get("integer_mask_spec").asText()))
    check("integer QA bit-mask", integerResult,
      node.get("expected_masked").elements().asScala.map(parseValue).toArray, 0)
    val adjusted = LocalEeIntegerValuesNumeric.applyTile(single(integerResult),
      LocalEeIntegerValuesSpec.parse(node.get("float_arithmetic_spec").asText()))
    check("Float64 arithmetic on integer QA result", adjusted,
      node.get("expected_adjusted").elements().asScala.map(parseValue).toArray, 0)
    2 * raw.length
  }

  private def tileFrom(row: JsonNode): MultibandTile = {
    val inputType = row.get("input_type").asText()
    val bands = row.get("bands").elements().asScala.map { band =>
      val values = band.elements().asScala.map(parseValue).toArray
      require(values.nonEmpty, "fixture bands must not be empty")
      val tile: Tile = inputType match {
        case "double" => doubleTile(values)
        case "int-sentinel-0" =>
          val cells = values.map(value => if (value.isNaN) 0 else checkedInteger(value).toInt)
          IntArrayTile(cells, cells.length, 1, 0)
        case "int-constant-nodata" =>
          val cells = values.map(value => if (value.isNaN) Int.MinValue else checkedInteger(value).toInt)
          IntArrayTile(cells, cells.length, 1, IntConstantNoDataCellType)
        case other => throw new IllegalArgumentException(s"unsupported fixture input type: $other")
      }
      var index = 0
      while (index < values.length) {
        require(same(tile.getDouble(index, 0), values(index), 0),
          s"$inputType fixture construction changed source cell $index")
        index += 1
      }
      tile
    }.toArray
    require(bands.nonEmpty && bands.forall(_.cols == bands(0).cols),
      "fixture bands must have matching positive widths")
    ArrayMultibandTile(bands)
  }

  private def checkedInteger(value: Double): Long = {
    require(value.isFinite && value == Math.rint(value) &&
      value >= Int.MinValue.toDouble && value <= Int.MaxValue.toDouble,
      s"typed fixture cell is not an Int: $value")
    value.toLong
  }

  private def single(tile: Tile): MultibandTile = ArrayMultibandTile(Array[Tile](tile))

  private def doubleTile(values: Array[Double]): Tile =
    DoubleArrayTile(values, values.length, 1, DoubleConstantNoDataCellType)

  private def check(label: String, tile: Tile, expected: Array[Double], toleranceUlps: Int): BigInt = {
    require(tile.cellType == DoubleConstantNoDataCellType,
      s"$label output must be Float64 with NaN NoData, got ${tile.cellType}")
    require(tile.cols == expected.length && tile.rows == 1, s"$label changed tile dimensions")
    var index = 0
    var maximumDistance = BigInt(0)
    while (index < expected.length) {
      val actual = tile.getDouble(index, 0)
      val distance = ulpDistance(actual, expected(index))
      require(distance.exists(_ <= BigInt(toleranceUlps)),
        s"$label pixel $index differs: actual=$actual expected=${expected(index)} " +
          s"toleranceUlps=$toleranceUlps")
      maximumDistance = maximumDistance.max(distance.get)
      index += 1
    }
    maximumDistance
  }

  private def same(actual: Double, expected: Double, toleranceUlps: Int): Boolean = {
    ulpDistance(actual, expected).exists(_ <= BigInt(toleranceUlps))
  }

  private def ulpDistance(actual: Double, expected: Double): Option[BigInt] = {
    if (actual.isNaN && expected.isNaN) return Some(BigInt(0))
    val actualBits = java.lang.Double.doubleToRawLongBits(actual)
    val expectedBits = java.lang.Double.doubleToRawLongBits(expected)
    if (actualBits == expectedBits) return Some(BigInt(0))
    if (!actual.isFinite || !expected.isFinite || actual == 0d || expected == 0d) return None
    Some((ordered(actualBits) - ordered(expectedBits)).abs)
  }

  private def ordered(bits: Long): BigInt = {
    val unsigned = if (bits < 0L) BigInt(bits & Long.MaxValue) + (BigInt(1) << 63) else BigInt(bits)
    if (bits < 0L) ((BigInt(1) << 64) - 1) - unsigned else unsigned + (BigInt(1) << 63)
  }

  private def parseValue(node: JsonNode): Double = node.asText() match {
    case "NaN" => Double.NaN
    case "Infinity" => Double.PositiveInfinity
    case "-Infinity" => Double.NegativeInfinity
    case value => java.lang.Double.valueOf(value)
  }
}
