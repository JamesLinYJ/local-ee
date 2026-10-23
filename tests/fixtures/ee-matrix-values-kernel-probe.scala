package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import java.nio.file.{Files, Paths}
import scala.collection.JavaConverters._

/** Standalone trusted GeoTrellis tile controls; deliberately no SparkContext or SPI loading. */
object EeMatrixValuesKernelProbe {
  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one matrix fixture path")
    val fixture = new ObjectMapper().readTree(Files.readAllBytes(Paths.get(args(0))))
    require(fixture.get("schema").asText() == "local-ee-matrix-values-synthetic/v1",
      "unexpected matrix values fixture schema")
    val cases = fixture.get("cases").elements().asScala.toVector
    var checkedPixels = 0
    var nonzeroChecks = 0
    cases.foreach { row =>
      val spec = LocalEeMatrixValuesSpec.parse(row.get("spec").asText())
      val input = tileFrom(row.get("input_bands"))
      val result = LocalEeMatrixValuesNumeric.applyTile(input, spec)
      val expected = row.get("expected").elements().asScala.toVector
      require(result.bandCount == expected.length,
        s"${row.get("label").asText()} returned ${result.bandCount} bands, expected ${expected.length}")
      require(result.cols == input.cols && result.rows == input.rows,
        s"${row.get("label").asText()} changed the tile dimensions")
      val absoluteTolerance = row.get("absolute_tolerance").asDouble()
      val relativeTolerance = row.get("relative_tolerance").asDouble()
      val requiredNonzero = row.path("require_nonzero").elements().asScala.map { coordinate =>
        require(coordinate.isArray && coordinate.size() == 2,
          s"${row.get("label").asText()} has an invalid required-nonzero coordinate")
        (coordinate.get(0).asInt(), coordinate.get(1).asInt())
      }.toVector
      var band = 0
      while (band < expected.length) {
        val expectedPixels = expected(band).elements().asScala.toVector
        var pixel = 0
        while (pixel < expectedPixels.length) {
          val actual = result.band(band).getDouble(pixel, 0)
          val expectedValue = parseValue(expectedPixels(pixel))
          checkClose(row.get("label").asText(), band, pixel, actual, expectedValue,
            absoluteTolerance, relativeTolerance)
          pixel += 1
          checkedPixels += 1
        }
        band += 1
      }
      requiredNonzero.foreach { case (requiredBand, requiredPixel) =>
        require(requiredBand >= 0 && requiredBand < result.bandCount &&
          requiredPixel >= 0 && requiredPixel < result.cols * result.rows,
          s"${row.get("label").asText()} required-nonzero coordinate is outside output")
        val actual = result.band(requiredBand).getDouble(requiredPixel % result.cols,
          requiredPixel / result.cols)
        require(actual.isFinite && actual != 0d,
          s"${row.get("label").asText()} output $requiredBand pixel $requiredPixel must be nonzero")
        nonzeroChecks += 1
      }
    }

    val invalidSpecs = fixture.get("invalid_specs").elements().asScala.toVector
    invalidSpecs.foreach { row => mustReject("invalid wire") {
      LocalEeMatrixValuesSpec.parse(row.asText())
    }}
    checkTileValidation()
    val budgetSummary = checkBudgets(cases)
    println(s"MATRIX_VALUES_KERNEL_OK cases=${cases.length} output_cells=$checkedPixels " +
      s"invalid_specs=${invalidSpecs.length} rank_policy=commons-math-3.6.1 " +
      s"required_nonzero=$nonzeroChecks tile_checks=4 all_nan_output_cells=4 $budgetSummary")
  }

  private def checkTileValidation(): Unit = {
    val scalarSolve = LocalEeMatrixValuesSpec.parse(
      "{\"cols\":1,\"op\":\"solve\",\"operands\":[{\"band\":0},{\"band\":1}]," +
        "\"rhs_cols\":1,\"rows\":1,\"v\":1}")
    val oneBand = ArrayMultibandTile(Array(
      DoubleArrayTile(Array(1d), 1, 1, DoubleConstantNoDataCellType): Tile))
    mustReject("wrong tile band count") {
      LocalEeMatrixValuesNumeric.applyTile(oneBand, scalarSolve)
    }
    val wrongMetadataSize = ArrayMultibandTile(Array(
      DoubleArrayTile(Array(1d, 1d), 2, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(2d, 2d), 2, 1, DoubleConstantNoDataCellType): Tile))
    mustReject("metadata tile dimensions") {
      LocalEeMatrixValuesNumeric.validateTileShape(wrongMetadataSize, scalarSolve, 1, 1)
    }

    val infiniteInput = ArrayMultibandTile(Array(
      DoubleArrayTile(Array(1d), 1, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(Double.PositiveInfinity), 1, 1, DoubleConstantNoDataCellType): Tile))
    mustReject("infinite tile input") {
      LocalEeMatrixValuesNumeric.applyTile(infiniteInput, scalarSolve)
    }

    val allNanSolve = LocalEeMatrixValuesSpec.parse(
      "{\"cols\":2,\"op\":\"solve\",\"operands\":[{\"band\":0},{\"band\":1}," +
        "{\"band\":2},{\"band\":3},{\"band\":4},{\"band\":5}]," +
        "\"rhs_cols\":1,\"rows\":2,\"v\":1}")
    val allNanInput = ArrayMultibandTile(Array(
      DoubleArrayTile(Array(1d, 1d), 2, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(0d, 0d), 2, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(0d, 0d), 2, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(1d, 1d), 2, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(Double.NaN, Double.NaN), 2, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(Double.NaN, Double.NaN), 2, 1, DoubleConstantNoDataCellType): Tile))
    val allNanOutput = LocalEeMatrixValuesNumeric.applyTile(allNanInput, allNanSolve)
    require(allNanOutput.bandCount == 2 && allNanOutput.cols == 2 && allNanOutput.rows == 1,
      "all-NaN solve changed the expected output shape")
    var band = 0
    while (band < allNanOutput.bandCount) {
      var col = 0
      while (col < allNanOutput.cols) {
        require(allNanOutput.band(band).getDouble(col, 0).isNaN,
          "all-NaN solve output must remain NoData in every matrix cell")
        col += 1
      }
      band += 1
    }
  }

  private def checkBudgets(cases: Vector[JsonNode]): String = {
    val small = LocalEeMatrixValuesSpec.parse(
      "{\"cols\":1,\"op\":\"solve\",\"operands\":[{\"band\":0},{\"band\":1}]," +
        "\"rhs_cols\":1,\"rows\":1,\"v\":1}")
    val smallWork = LocalEeMatrixValuesBudget.workPerPixel(small)
    require(smallWork > 0L, "matrix values work charge must be positive")
    val maxPixels = LocalEeMatrixValuesBudget.MaxTileWork / smallWork
    LocalEeMatrixValuesBudget.check(maxPixels, 1L, small)
    mustReject("per-tile work") {
      LocalEeMatrixValuesBudget.check(maxPixels + 1L, 1L, small)
    }
    LocalEeMatrixValuesBudget.check(1L, LocalEeMatrixValuesBudget.MaxTileKeys, small)
    mustReject("tile-key cap") {
      LocalEeMatrixValuesBudget.check(1L, LocalEeMatrixValuesBudget.MaxTileKeys + 1L, small)
    }

    val largeSpec = LocalEeMatrixValuesSpec.parse(
      cases.find(_.get("label").asText() == "max_solve_input_cells_64").get.get("spec").asText())
    val totalKeyBoundary = LocalEeMatrixValuesBudget.MaxTotalWork /
      LocalEeMatrixValuesBudget.workPerPixel(largeSpec)
    require(totalKeyBoundary > 0L && totalKeyBoundary < LocalEeMatrixValuesBudget.MaxTileKeys,
      "matrix values aggregate-work control did not exercise the total cap")
    LocalEeMatrixValuesBudget.check(1L, totalKeyBoundary, largeSpec)
    mustReject("aggregate work") {
      LocalEeMatrixValuesBudget.check(1L, totalKeyBoundary + 1L, largeSpec)
    }

    val solve2x2 = LocalEeMatrixValuesSpec.parse(
      "{\"cols\":2,\"op\":\"solve\",\"operands\":[{\"band\":0},{\"band\":1}," +
        "{\"band\":2},{\"band\":3},{\"band\":4},{\"band\":5}]," +
        "\"rhs_cols\":1,\"rows\":2,\"v\":1}")
    val solveWork = LocalEeMatrixValuesBudget.workPerPixel(solve2x2)
    val solveMaxPixels = LocalEeMatrixValuesBudget.MaxTileWork / solveWork
    require(solveWork == 2520L, s"unexpected 2x2 solve work estimate: $solveWork")
    LocalEeMatrixValuesBudget.check(128L * 128L, 1L, solve2x2)
    mustReject("256x256 solve tile work") {
      LocalEeMatrixValuesBudget.check(256L * 256L, 1L, solve2x2)
    }
    LocalEeMatrixValuesBudget.check(solveMaxPixels, 1L, solve2x2)
    mustReject("solve max tile pixels") {
      LocalEeMatrixValuesBudget.check(solveMaxPixels + 1L, 1L, solve2x2)
    }

    val inverse2x2 = LocalEeMatrixValuesSpec.parse(
      "{\"cols\":2,\"op\":\"inverse\",\"operands\":[{\"band\":0},{\"band\":1}," +
        "{\"band\":2},{\"band\":3}],\"rhs_cols\":0,\"rows\":2,\"v\":1}")
    val inverseWork = LocalEeMatrixValuesBudget.workPerPixel(inverse2x2)
    val inverseMaxPixels = LocalEeMatrixValuesBudget.MaxTileWork / inverseWork
    require(inverseWork == 400L, s"unexpected 2x2 inverse work estimate: $inverseWork")
    LocalEeMatrixValuesBudget.check(128L * 128L, 1L, inverse2x2)
    LocalEeMatrixValuesBudget.check(256L * 256L, 1L, inverse2x2)
    LocalEeMatrixValuesBudget.check(inverseMaxPixels, 1L, inverse2x2)
    mustReject("inverse max tile pixels") {
      LocalEeMatrixValuesBudget.check(inverseMaxPixels + 1L, 1L, inverse2x2)
    }

    val smallMaxPixels = LocalEeMatrixValuesBudget.MaxTileWork / smallWork
    val smallKeyCapacity = math.min(LocalEeMatrixValuesBudget.MaxTileKeys,
      LocalEeMatrixValuesBudget.MaxTotalWork / smallWork)
    val largeKeyCapacity = math.min(LocalEeMatrixValuesBudget.MaxTileKeys, totalKeyBoundary)
    s"solve2_work=$solveWork solve2_max_pixels=$solveMaxPixels solve_128x128=pass " +
      s"solve_256x256=reject inverse2_work=$inverseWork inverse2_max_pixels=$inverseMaxPixels " +
      s"inverse_128x128=pass inverse_256x256=pass small_work=$smallWork " +
      s"small_max_pixels=$smallMaxPixels small_key_capacity=$smallKeyCapacity " +
      s"input_cells64_work=${LocalEeMatrixValuesBudget.workPerPixel(largeSpec)} " +
      s"input_cells64_key_capacity=$largeKeyCapacity"
  }

  private def checkClose(
    label: String, band: Int, pixel: Int, actual: Double, expected: Double,
    absoluteTolerance: Double, relativeTolerance: Double
  ): Unit = {
    if (expected.isNaN) {
      require(actual.isNaN, s"$label output $band pixel $pixel should be NoData, got $actual")
    } else {
      require(actual.isFinite, s"$label output $band pixel $pixel should be finite, got $actual")
      val tolerance = math.max(absoluteTolerance,
        relativeTolerance * math.max(math.abs(actual), math.abs(expected)))
      require(math.abs(actual - expected) <= tolerance,
        s"$label output $band pixel $pixel differs: $actual != $expected (tol=$tolerance)")
    }
  }

  private def tileFrom(node: JsonNode): MultibandTile = {
    val bands = node.elements().asScala.map { band =>
      val values = band.elements().asScala.map(parseValue).toArray
      require(values.nonEmpty, "matrix fixture bands must contain pixels")
      DoubleArrayTile(values, values.length, 1, DoubleConstantNoDataCellType): Tile
    }.toArray
    require(bands.nonEmpty && bands.forall(_.cols == bands(0).cols),
      "matrix fixture bands must have a shared positive width")
    ArrayMultibandTile(bands)
  }

  private def parseValue(node: JsonNode): Double = {
    val text = node.asText()
    if (text == "NaN") Double.NaN else java.lang.Double.valueOf(text)
  }

  private def mustReject(label: String)(action: => Any): Unit = {
    var rejected = false
    try action catch {
      case _: IllegalArgumentException => rejected = true
      case _: ArithmeticException => rejected = true
    }
    require(rejected, s"matrix values $label control was accepted")
  }
}
