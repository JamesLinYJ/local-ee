package local.ee.reduce

import com.fasterxml.jackson.databind.JsonNode
import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import java.math.BigDecimal
import java.nio.file.{Files, Paths}
import scala.collection.JavaConverters._

/** Standalone trusted GeoTrellis QR/SVD tile checks without Spark or SPI loading. */
object EeMatrixOrthogonalKernelProbe {
  private val Tolerance = new BigDecimal("1e-10")

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one matrix orthogonal fixture path")
    val fixture = new ObjectMapper().readTree(Files.readAllBytes(Paths.get(args(0))))
    require(fixture.get("schema").asText() == "local-ee-matrix-orthogonal-kernel-synthetic/v1",
      "unexpected matrix orthogonal fixture schema")
    val cases = fixture.get("cases").elements().asScala.toVector
    var checkedCells = 0
    var qrCases = 0
    var svdCases = 0
    var admittedCases = 0
    var directKernelOnlyCases = 0
    cases.foreach { row =>
      val label = row.get("label").asText()
      val spec = LocalEeMatrixValuesSpec.parse(row.get("spec").asText())
      val input = tileFrom(row.get("input_bands"))
      if (label.endsWith("_outside_budget")) {
        val work = LocalEeMatrixOrthogonalBudget.workPerPixel(spec,
          LocalEeMatrixFactorizationBudget.envelopeForTile(input, spec, input.cols, input.rows))
        require(work > LocalEeMatrixValuesBudget.MaxTileWork,
          s"$label must remain outside the per-tile preflight cap")
        directKernelOnlyCases += 1
      } else {
        val work = LocalEeMatrixOrthogonalBudget.workForTile(input, spec, input.cols, input.rows)
        require(work > 0L, s"$label did not pass orthogonal work admission")
        admittedCases += 1
      }
      val result = LocalEeMatrixValuesNumeric.applyTile(input, spec)
      require(result.bandCount == spec.outputCells,
        s"$label returned ${result.bandCount} factors, expected ${spec.outputCells}")
      require(result.cols == input.cols && result.rows == input.rows,
        s"$label changed tile dimensions")
      val actual = Array.tabulate(result.bandCount)(band => result.band(band).getDouble(0, 0))
      if (row.get("mask").asBoolean()) {
        require(actual.forall(_.isNaN), s"$label must mask the entire factor output")
      } else {
        require(actual.forall(_.isFinite), s"$label produced a nonfinite factor")
        val source = matrixFrom(row.get("input_bands"), spec.rows, spec.cols)
        if (spec.op == "qr") {
          checkQr(label, source, actual, spec.rows, spec.cols)
          qrCases += 1
        } else {
          checkSvd(label, source, actual, spec.rows, spec.cols, row.get("rank").asInt())
          if (row.has("singular_values")) {
            checkSingularReferences(label, actual, spec.rows, spec.cols, row.get("singular_values"))
          }
          svdCases += 1
        }
      }
      checkedCells += actual.length
    }

    val invalidSpecs = fixture.get("invalid_specs").elements().asScala.toVector
    invalidSpecs.foreach(row => mustReject("invalid orthogonal spec") {
      LocalEeMatrixValuesSpec.parse(row.asText())
    })
    checkInputValidation()
    checkJacobiSubnormalIdentity()
    val budgetSummary = checkBudgets()
    println(s"MATRIX_ORTHOGONAL_KERNEL_OK cases=${cases.length} admitted=$admittedCases " +
      s"direct_kernel_only=$directKernelOnlyCases qr=$qrCases svd=$svdCases " +
      s"output_cells=$checkedCells invalid_specs=${invalidSpecs.length} " +
      "finite_factor_checks=true normwise_reconstruction=true infinite_input_reject=true " + budgetSummary)
  }

  private def checkQr(label: String, source: Array[Array[Double]],
                      output: Array[Double], rows: Int, cols: Int): Unit = {
    val p = math.min(rows, cols)
    val q = Array.tabulate(rows, p)((row, col) => output(row * p + col))
    val offset = rows * p
    val r = Array.tabulate(p, cols)((row, col) => output(offset + row * cols + col))
    checkOrthonormal(label, "Q", q, p)
    var row = 0
    while (row < p) {
      var col = 0
      while (col < math.min(row, cols)) {
        require(r(row)(col) == 0d, s"$label R is not upper trapezoidal at ($row,$col)")
        col += 1
      }
      row += 1
    }
    if (label == "qr_tiny_trailing_diagonal") {
      val tinyDiagonal = r(1)(1)
      require(tinyDiagonal != 0d && math.abs(tinyDiagonal) == java.lang.Double.longBitsToDouble(1L),
        "QR must retain the representable minimum-subnormal trailing diagonal")
    }
    checkBackward(label, source, (i, j) => {
      var sum = BigDecimal.ZERO
      var k = 0
      while (k < p) {
        sum = sum.add(new BigDecimal(q(i)(k)).multiply(new BigDecimal(r(k)(j))))
        k += 1
      }
      sum
    })
  }

  private def checkSvd(label: String, source: Array[Array[Double]], output: Array[Double],
                       rows: Int, cols: Int, expectedRank: Int): Unit = {
    val p = math.min(rows, cols)
    val u = Array.tabulate(rows, p)((row, col) => output(row * p + col))
    val sOffset = rows * p
    val singular = Array.tabulate(p)(index => output(sOffset + index * p + index))
    var row = 0
    while (row < p) {
      var col = 0
      while (col < p) {
        if (row != col) require(output(sOffset + row * p + col) == 0d,
          s"$label S must be diagonal")
        col += 1
      }
      row += 1
    }
    require(singular.count(_ > 0d) == expectedRank,
      s"$label has ${singular.count(_ > 0d)} positive singular values, expected $expectedRank")
    var index = 0
    while (index < p) {
      require(singular(index) >= 0d, s"$label has a negative singular value")
      if (index > 0) require(singular(index - 1) >= singular(index),
        s"$label singular values are not descending")
      index += 1
    }
    val vOffset = sOffset + p * p
    val v = Array.tabulate(cols, p)((row, col) => output(vOffset + row * p + col))
    checkOrthonormal(label, "U", u, p)
    checkOrthonormal(label, "V", v, p)
    checkBackward(label, source, (i, j) => {
      var sum = BigDecimal.ZERO
      var k = 0
      while (k < p) {
        sum = sum.add(new BigDecimal(u(i)(k)).multiply(new BigDecimal(singular(k)))
          .multiply(new BigDecimal(v(j)(k))))
        k += 1
      }
      sum
    })
  }

  private def checkSingularReferences(label: String, output: Array[Double], rows: Int, cols: Int,
                                      reference: JsonNode): Unit = {
    val p = math.min(rows, cols)
    val offset = rows * p
    val actual = Array.tabulate(p)(index => output(offset + index * p + index))
    val expected = reference.elements().asScala.map(node => java.lang.Double.valueOf(node.asText())).toArray
    require(expected.length == p, s"$label singular reference shape changed")
    var index = 0
    while (index < p) {
      if (expected(index) == 0d) {
        require(actual(index) == 0d, s"$label expected an exact zero singular value")
      } else {
        val relative = math.abs(actual(index) - expected(index)) / expected(index)
        require(actual(index) > 0d && relative <= 1e-10,
          s"$label singular value $index lost relative accuracy: got ${actual(index)}, expected ${expected(index)}")
      }
      index += 1
    }
  }

  private def checkOrthonormal(label: String, name: String,
                               matrix: Array[Array[Double]], columns: Int): Unit = {
    var left = 0
    while (left < columns) {
      var right = left
      while (right < columns) {
        var dot = 0d
        var row = 0
        while (row < matrix.length) {
          dot += matrix(row)(left) * matrix(row)(right)
          row += 1
        }
        val expected = if (left == right) 1d else 0d
        require(dot.isFinite && math.abs(dot - expected) <= 1e-10,
          s"$label $name columns $left/$right are not orthonormal: $dot")
        right += 1
      }
      left += 1
    }
  }

  private def checkBackward(label: String, source: Array[Array[Double]],
                            reconstruct: (Int, Int) => BigDecimal): Unit = {
    var sourceSquared = BigDecimal.ZERO
    var errorSquared = BigDecimal.ZERO
    var row = 0
    while (row < source.length) {
      var col = 0
      while (col < source(0).length) {
        val expected = new BigDecimal(source(row)(col))
        val residual = reconstruct(row, col).subtract(expected)
        sourceSquared = sourceSquared.add(expected.multiply(expected))
        errorSquared = errorSquared.add(residual.multiply(residual))
        col += 1
      }
      row += 1
    }
    val residualNorm = errorSquared.sqrt(new java.math.MathContext(80))
    val sourceNorm = sourceSquared.sqrt(new java.math.MathContext(80))
    require(if (sourceSquared.signum() == 0) errorSquared.signum() == 0
      else residualNorm.compareTo(sourceNorm.multiply(Tolerance)) <= 0,
      s"$label factor reconstruction exceeds normwise tolerance")
  }

  private def checkInputValidation(): Unit = {
    val spec = LocalEeMatrixValuesSpec.parse(matrixSpec("svd", 2, 2))
    val invalid = ArrayMultibandTile(Array(
      DoubleArrayTile(Array(Double.NaN), 1, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(Double.PositiveInfinity), 1, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(0d), 1, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(1d), 1, 1, DoubleConstantNoDataCellType): Tile))
    mustReject("infinity beside NoData") { LocalEeMatrixValuesNumeric.applyTile(invalid, spec) }

    val one = LocalEeMatrixValuesSpec.parse(matrixSpec("qr", 1, 1))
    val wrongBands = ArrayMultibandTile(Array(
      DoubleArrayTile(Array(1d), 1, 1, DoubleConstantNoDataCellType): Tile,
      DoubleArrayTile(Array(2d), 1, 1, DoubleConstantNoDataCellType): Tile))
    mustReject("orthogonal input band count") { LocalEeMatrixValuesNumeric.applyTile(wrongBands, one) }
    val wrongShape = ArrayMultibandTile(Array(
      DoubleArrayTile(Array(1d, 2d), 2, 1, DoubleConstantNoDataCellType): Tile))
    mustReject("orthogonal tile shape") {
      LocalEeMatrixValuesNumeric.validateTileShape(wrongShape, one, 1, 1)
    }
  }

  private def checkJacobiSubnormalIdentity(): Unit = {
    val minimum = java.lang.Double.longBitsToDouble(1L)
    val source = Array(Array(1e308, 0d), Array(0d, minimum))
    val flat = Array(1e308, 0d, 0d, minimum)
    val spec = LocalEeMatrixValuesSpec.parse(matrixSpec("svd", 2, 2))
    val bound = LocalEeMatrixOrthogonalBudget.decimalDigitLimit(spec,
      LocalEeMatrixOrthogonalBudget.envelopeForValues(flat))
    val factors = LocalEeMatrixSvdJacobi.decompose(source, 2, bound)
      .getOrElse(throw new IllegalArgumentException("Jacobi discarded a subnormal diagonal direction"))
    require(factors.singular.length == 2 && factors.singular(0) == 1e308 &&
      factors.singular(1) == minimum,
      "Jacobi must preserve zero-identity accumulation for a representable subnormal singular value")
  }

  private def checkBudgets(): String = {
    val qr2 = LocalEeMatrixValuesSpec.parse(matrixSpec("qr", 2, 2))
    val svd2 = LocalEeMatrixValuesSpec.parse(matrixSpec("svd", 2, 2))
    val svd3x2 = LocalEeMatrixValuesSpec.parse(matrixSpec("svd", 3, 2))
    val svd3x3 = LocalEeMatrixValuesSpec.parse(matrixSpec("svd", 3, 3))
    val qr8x4 = LocalEeMatrixValuesSpec.parse(matrixSpec("qr", 8, 4))
    val values2 = Array(3d, 1d, 4d, 2d)
    val values3x2 = Array(1d, 2d, 3d, 4d, 5d, 6d)
    val qrWork = LocalEeMatrixOrthogonalBudget.workPerPixel(qr2,
      LocalEeMatrixOrthogonalBudget.envelopeForValues(values2))
    val svdWork = LocalEeMatrixOrthogonalBudget.workPerPixel(svd2,
      LocalEeMatrixOrthogonalBudget.envelopeForValues(values2))
    val tallWork = LocalEeMatrixOrthogonalBudget.workPerPixel(svd3x2,
      LocalEeMatrixOrthogonalBudget.envelopeForValues(values3x2))
    require(qrWork > 0L && svdWork > qrWork && tallWork > svdWork,
      "orthogonal budgets must charge bounded factor dimensions")
    val maxPixels2 = LocalEeMatrixValuesBudget.MaxTileWork / svdWork
    val maxPixels3x2 = LocalEeMatrixValuesBudget.MaxTileWork / tallWork
    require(maxPixels2 > 0L && maxPixels3x2 > 0L,
      "standard SVD estimates must admit at least one tile pixel")
    val mixedRankDeficient = Array(1e100, 1e100, 2e100,
      0d, 1e-200, 1e-200,
      0d, 0d, 0d)
    val mixedEnvelope = LocalEeMatrixOrthogonalBudget.envelopeForValues(mixedRankDeficient)
    val mixedWork = LocalEeMatrixOrthogonalBudget.workPerPixel(svd3x3, mixedEnvelope)
    require(mixedWork <= LocalEeMatrixValuesBudget.MaxTileWork,
      "the mixed-scale rank-2 Jacobi regression must fit a one-pixel SVD tile")
    val minimum = java.lang.Double.longBitsToDouble(1L)
    val subnormalEnvelope = LocalEeMatrixOrthogonalBudget.envelopeForValues(
      Array(1e308, 0d, 0d, minimum))
    val subnormalWork = LocalEeMatrixOrthogonalBudget.workPerPixel(svd2, subnormalEnvelope)
    require(subnormalWork <= LocalEeMatrixValuesBudget.MaxTileWork,
      "the representable mixed-scale subnormal SVD regression must fit a one-pixel tile")
    val qrExtreme = Array(1e308, 0d, 0d, 1d,
      0d, 0d, 0d, 0d,
      0d, 0d, 1d, 0d,
      0d, 0d, 0d, minimum,
      0d, 0d, 0d, 0d,
      0d, 0d, 0d, 0d,
      0d, 0d, 0d, 0d,
      0d, 0d, 0d, 0d)
    val qrExtremeWork = LocalEeMatrixOrthogonalBudget.workPerPixel(qr8x4,
      LocalEeMatrixOrthogonalBudget.envelopeForValues(qrExtreme))
    require(qrExtremeWork > LocalEeMatrixValuesBudget.MaxTileWork,
      "mixed-exponent 8x4 QR must expose its fail-closed work-budget boundary")
    mustReject("SVD per-tile work limit") {
      require(Math.multiplyExact(maxPixels2 + 1L, svdWork) <=
        LocalEeMatrixValuesBudget.MaxTileWork, "tile exceeds orthogonal budget")
    }
    mustReject("SVD aggregate work limit") {
      LocalEeMatrixOrthogonalBudget.aggregateWork(svdWork,
        LocalEeMatrixValuesBudget.MaxTotalWork / svdWork + 1L)
    }
    val exact64Tall = LocalEeMatrixValuesSpec.parse(matrixSpec("svd", 8, 4))
    val exact64Wide = LocalEeMatrixValuesSpec.parse(matrixSpec("svd", 4, 8))
    require(exact64Tall.outputCells == 64 && exact64Wide.outputCells == 64,
      "both SVD orientations with 64 outputs must be admitted")
    val maxSide2 = math.sqrt(maxPixels2.toDouble).toLong
    val maxSide3x2 = math.sqrt(maxPixels3x2.toDouble).toLong
    s"qr2_work=$qrWork svd2_work=$svdWork svd3x2_work=$tallWork " +
      s"max_svd2_pixels=$maxPixels2 max_svd2_square_side=$maxSide2 " +
      s"max_svd3x2_pixels=$maxPixels3x2 max_svd3x2_square_side=$maxSide3x2 " +
      s"svd3x3_mixed_work=$mixedWork svd2_subnormal_work=$subnormalWork " +
      s"qr8x4_extreme_rejected=true qr8x4_extreme_work=$qrExtremeWork " +
      "output64_both_orientations=true"
  }

  private def matrixSpec(op: String, rows: Int, cols: Int): String = {
    val operands = (0 until rows * cols).map(index => s"{\"band\":$index}").mkString(",")
    s"{\"cols\":$cols,\"op\":\"$op\",\"operands\":[$operands]," +
      s"\"rhs_cols\":0,\"rows\":$rows,\"v\":1}"
  }

  private def matrixFrom(node: JsonNode, rows: Int, cols: Int): Array[Array[Double]] =
    Array.tabulate(rows, cols) { (row, col) => parseValue(node.get(row * cols + col).get(0)) }

  private def tileFrom(node: JsonNode): MultibandTile = {
    val bands = node.elements().asScala.map { band =>
      val values = band.elements().asScala.map(parseValue).toArray
      DoubleArrayTile(values, values.length, 1, DoubleConstantNoDataCellType): Tile
    }.toArray
    ArrayMultibandTile(bands)
  }

  private def parseValue(node: JsonNode): Double = {
    val value = node.asText()
    if (value == "NaN") Double.NaN else java.lang.Double.valueOf(value)
  }

  private def mustReject(label: String)(body: => Unit): Unit = {
    var rejected = false
    try body catch { case _: IllegalArgumentException => rejected = true }
    require(rejected, s"$label must be rejected")
  }
}
