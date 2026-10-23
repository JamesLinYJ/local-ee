package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import java.nio.file.{Files, Paths}
import scala.collection.JavaConverters._

/** Standalone trusted GeoTrellis Cholesky/LU controls without Spark or SPI loading. */
object EeMatrixFactorKernelProbe {
  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one matrix factor fixture path")
    val fixture = new ObjectMapper().readTree(Files.readAllBytes(Paths.get(args(0))))
    require(fixture.get("schema").asText() == "local-ee-matrix-factor-kernel-synthetic/v1",
      "unexpected matrix factor fixture schema")
    val cases = fixture.get("cases").elements().asScala.toVector
    var checkedCells = 0
    var nonzeroChecks = 0
    cases.foreach { row =>
      val label = row.get("label").asText()
      val spec = LocalEeMatrixValuesSpec.parse(row.get("spec").asText())
      val input = tileFrom(row.get("input_bands"))
      val result = LocalEeMatrixValuesNumeric.applyTile(input, spec)
      val expected = row.get("expected").elements().asScala.toVector
      require(result.bandCount == expected.length,
        s"$label returned ${result.bandCount} bands, expected ${expected.length}")
      require(result.cols == input.cols && result.rows == input.rows,
        s"$label changed tile dimensions")
      val absoluteTolerance = row.get("absolute_tolerance").asDouble()
      val relativeTolerance = row.get("relative_tolerance").asDouble()
      var band = 0
      while (band < expected.length) {
        val bandPixels = expected(band).elements().asScala.toVector
        var pixel = 0
        while (pixel < bandPixels.length) {
          checkClose(label, band, pixel, result.band(band).getDouble(pixel, 0),
            parseValue(bandPixels(pixel)), absoluteTolerance, relativeTolerance)
          pixel += 1
          checkedCells += 1
        }
        band += 1
      }
      row.path("require_nonzero").elements().asScala.foreach { coordinate =>
        require(coordinate.isArray && coordinate.size() == 2,
          s"$label has an invalid required-nonzero coordinate")
        val outputBand = coordinate.get(0).asInt()
        val pixel = coordinate.get(1).asInt()
        require(outputBand >= 0 && outputBand < result.bandCount &&
          pixel >= 0 && pixel < result.cols * result.rows,
          s"$label required-nonzero coordinate is outside output")
        val actual = result.band(outputBand).getDouble(pixel % result.cols, pixel / result.cols)
        require(actual.isFinite && actual != 0d,
          s"$label output $outputBand pixel $pixel must be finite and nonzero")
        nonzeroChecks += 1
      }
    }

    val invalidSpecs = fixture.get("invalid_specs").elements().asScala.toVector
    invalidSpecs.foreach { row => mustReject("invalid factor spec") {
      LocalEeMatrixValuesSpec.parse(row.asText())
    }}
    checkTileValidation()
    val budgetSummary = checkBudgets()
    println(s"MATRIX_FACTOR_KERNEL_OK cases=${cases.length} output_cells=$checkedCells " +
      s"invalid_specs=${invalidSpecs.length} required_nonzero=$nonzeroChecks " +
      s"tile_checks=4 envelope_checks=6 whole_factor_mask=true $budgetSummary")
  }

  private def checkTileValidation(): Unit = {
    val cholesky = LocalEeMatrixValuesSpec.parse(
      "{\"cols\":1,\"op\":\"cholesky\",\"operands\":[{\"band\":0}]," +
        "\"rhs_cols\":0,\"rows\":1,\"v\":1}")
    val wrongBands = ArrayMultibandTile(Array(
      DoubleArrayTile(Array(1d), 1, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(1d), 1, 1, DoubleConstantNoDataCellType): Tile))
    mustReject("factor input band count") {
      LocalEeMatrixValuesNumeric.applyTile(wrongBands, cholesky)
    }
    val wrongMetadata = ArrayMultibandTile(Array(
      DoubleArrayTile(Array(1d, 1d), 2, 1, DoubleConstantNoDataCellType): Tile))
    mustReject("factor metadata dimensions") {
      LocalEeMatrixValuesNumeric.validateTileShape(wrongMetadata, cholesky, 1, 1)
    }

    val lu = LocalEeMatrixValuesSpec.parse(
      "{\"cols\":2,\"op\":\"lu\",\"operands\":[{\"band\":0},{\"band\":1}," +
        "{\"band\":2},{\"band\":3}],\"rhs_cols\":0,\"rows\":2,\"v\":1}")
    val nonfinite = ArrayMultibandTile(Array(
      DoubleArrayTile(Array(Double.NaN), 1, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(Double.PositiveInfinity), 1, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(0d), 1, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(1d), 1, 1, DoubleConstantNoDataCellType): Tile))
    mustReject("infinite source beside NoData") {
      LocalEeMatrixValuesNumeric.applyTile(nonfinite, lu)
    }
  }

  private def checkBudgets(): String = {
    val choleskyMax = LocalEeMatrixValuesSpec.parse(
      "{\"cols\":8,\"op\":\"cholesky\",\"operands\":[" +
        (0 until 64).map(index => s"{\"band\":$index}").mkString(",") +
        "],\"rhs_cols\":0,\"rows\":8,\"v\":1}")
    val cholWork = LocalEeMatrixValuesBudget.workPerPixel(choleskyMax)
    require(cholWork > 0L, "factorization work charge must be positive")
    LocalEeMatrixValuesBudget.check(32L, 1L, choleskyMax)
    val cholPixels = LocalEeMatrixValuesBudget.MaxTileWork / cholWork
    mustReject("Cholesky per-tile work") {
      LocalEeMatrixValuesBudget.check(cholPixels + 1L, 1L, choleskyMax)
    }
    val cholKeys = LocalEeMatrixValuesBudget.MaxTotalWork / (32L * cholWork)
    LocalEeMatrixValuesBudget.check(32L, cholKeys, choleskyMax)
    mustReject("Cholesky aggregate work") {
      LocalEeMatrixValuesBudget.check(32L, cholKeys + 1L, choleskyMax)
    }

    val lu2 = luSpec(2)
    val integer128 = repeatedLuTile(Array(4d, 2d, 1d, 3d), 128)
    val fractional256 = repeatedLuTile(Array(1.5d, 0.5d, 0.25d, 1.25d), 256)
    val integerEnvelope = LocalEeMatrixFactorizationBudget.envelopeForTile(integer128, lu2, 128, 128)
    val integer128Work = LocalEeMatrixFactorizationBudget.workForTile(integer128, lu2, 128, 128)
    val fractional256Work = LocalEeMatrixFactorizationBudget.workForTile(fractional256, lu2, 256, 256)
    require(integer128Work <= LocalEeMatrixValuesBudget.MaxTileWork &&
      fractional256Work <= LocalEeMatrixValuesBudget.MaxTileWork,
      "ordinary integer/fractional LU tiles should fit the existing per-tile cap")
    LocalEeMatrixFactorizationBudget.requireWithinEnvelope(integer128, lu2, 128, 128, integerEnvelope)
    require(LocalEeMatrixFactorizationBudget.aggregateWork(fractional256Work, 1L) ==
      fractional256Work, "ordinary 256-square LU tile should fit the aggregate cap")
    mustReject("LU aggregate work") {
      LocalEeMatrixFactorizationBudget.aggregateWork(
        LocalEeMatrixValuesBudget.MaxTotalWork / 2L + 1L, 2L)
    }

    val minimumSubnormal = java.lang.Double.longBitsToDouble(1L)
    val extreme = repeatedLuTile(Array(1e308, 0d, 0d, minimumSubnormal), 1)
    val extremeWork = LocalEeMatrixFactorizationBudget.workForTile(extreme, lu2, 1, 1)
    require(extremeWork > fractional256Work / (256L * 256L) &&
      extremeWork <= LocalEeMatrixValuesBudget.MaxTileWork,
      "extreme exponent spread should be charged by its derived rational bound")
    mustReject("extreme LU per-tile work") {
      LocalEeMatrixFactorizationBudget.workForTile(
        repeatedLuTile(Array(1e308, 0d, 0d, minimumSubnormal), 4), lu2, 4, 4)
    }
    mustReject("changed source exponent envelope") {
      LocalEeMatrixFactorizationBudget.requireWithinEnvelope(extreme, lu2, 1, 1, integerEnvelope)
    }

    val emptyEnvelope = LocalEeMatrixFactorizationBudget.Envelope(false, false, 0, 0, 1)
    val negativeTile = repeatedLuTile(Array(
      math.scalb(1d, -100), math.scalb(1d, -101),
      math.scalb(1d, -102), math.scalb(1d, -103)), 1)
    val negativeEnvelope = LocalEeMatrixFactorizationBudget.envelopeForTile(negativeTile, lu2, 1, 1)
    require(negativeEnvelope.minExponent == -103 && negativeEnvelope.maxExponent == -100,
      s"negative exponent fixture has unexpected bounds: $negativeEnvelope")
    val zeroTile = repeatedLuTile(Array(0d, 0d, 0d, 0d), 1)
    val zeroEnvelope = LocalEeMatrixFactorizationBudget.envelopeForTile(zeroTile, lu2, 1, 1)
    require(LocalEeMatrixFactorizationBudget.merge(emptyEnvelope, negativeEnvelope) == negativeEnvelope &&
      LocalEeMatrixFactorizationBudget.merge(negativeEnvelope, emptyEnvelope) == negativeEnvelope,
      "empty envelope must be an identity for negative-exponent source bounds")
    require(LocalEeMatrixFactorizationBudget.merge(zeroEnvelope, negativeEnvelope) == negativeEnvelope &&
      LocalEeMatrixFactorizationBudget.merge(negativeEnvelope, zeroEnvelope) == negativeEnvelope,
      "zero-only envelope must not widen negative-exponent source bounds")
    val secondNegativeTile = repeatedLuTile(Array(
      math.scalb(1d, -102), math.scalb(1d, -101), 0d, math.scalb(1d, -103)), 1)
    val secondNegativeEnvelope = LocalEeMatrixFactorizationBudget.envelopeForTile(
      secondNegativeTile, lu2, 1, 1)
    val mergedNegativeEnvelope = LocalEeMatrixFactorizationBudget.merge(
      negativeEnvelope, secondNegativeEnvelope)
    require(mergedNegativeEnvelope.minExponent == -103 && mergedNegativeEnvelope.maxExponent == -100,
      s"all-negative envelope merge has unexpected bounds: $mergedNegativeEnvelope")
    val negativeEnvelopeWork = LocalEeMatrixFactorizationBudget.workForEnvelope(lu2, negativeEnvelope)
    val zeroWidenedWork = LocalEeMatrixFactorizationBudget.workForEnvelope(
      lu2, negativeEnvelope.copy(maxExponent = 0))
    require(negativeEnvelopeWork == LocalEeMatrixFactorizationBudget.workForTile(
      negativeTile, lu2, 1, 1) && zeroWidenedWork > negativeEnvelopeWork,
      "negative input budget must use merged source exponents instead of empty-envelope zero")
    s"cholesky8_work=$cholWork lu2_integer_128_work=$integer128Work " +
      s"lu2_fractional_256_work=$fractional256Work lu2_extreme_1_work=$extremeWork " +
      s"lu2_negative_1_work=$negativeEnvelopeWork lu2_zero_widened_1_work=$zeroWidenedWork " +
      "lu_envelope_merge=pass " +
      "factor_tile_and_key_limits=pass"
  }

  private def luSpec(size: Int): LocalEeMatrixValuesSpec.Value =
    LocalEeMatrixValuesSpec.parse(
      s"{\"cols\":$size,\"op\":\"lu\",\"operands\":[" +
        (0 until size * size).map(index => s"{\"band\":$index}").mkString(",") +
        s"],\"rhs_cols\":0,\"rows\":$size,\"v\":1}")

  private def repeatedLuTile(values: Array[Double], side: Int): MultibandTile = {
    val count = Math.multiplyExact(side, side)
    ArrayMultibandTile(values.map(value =>
      DoubleArrayTile(Array.fill(count)(value), side, side, DoubleConstantNoDataCellType): Tile))
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
      require(values.nonEmpty, "factor fixture bands must contain pixels")
      DoubleArrayTile(values, values.length, 1, DoubleConstantNoDataCellType): Tile
    }.toArray
    require(bands.nonEmpty && bands.forall(_.cols == bands(0).cols),
      "factor fixture bands must have a shared positive width")
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
    require(rejected, s"matrix factor $label was accepted")
  }
}
