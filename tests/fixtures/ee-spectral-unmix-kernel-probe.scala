package local.ee.reduce

import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, FloatArrayTile, FloatConstantNoDataCellType, MultibandTile, Tile}
import java.nio.file.{Files, Paths}
import scala.collection.JavaConverters._

/** Trusted actual-GeoTrellis tile probe. It starts no SparkContext or service. */
object EeSpectralUnmixKernelProbe {
  private val Mapper = new ObjectMapper()

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "expected one spectral-unmix fixture path")
    val fixture = Mapper.readTree(Files.readAllBytes(Paths.get(args(0))))
    require(fixture.path("schema").asText() == "local-ee-spectral-unmix-native/v1",
      "unexpected spectral-unmix fixture schema")
    val cases = fixture.path("cases").elements().asScala.toVector
    require(cases.nonEmpty, "spectral-unmix probe requires at least one positive case")
    val actualOutputs = cases.map(row => runCase(row, fixture.path("require_nonzero").asBoolean(false)))
    val invalidSpecs = fixture.path("invalid_specs").elements().asScala.toVector
    invalidSpecs.foreach { row => mustReject("invalid wire") {
      LocalEeSpectralUnmixSpec.parse(row.asText())
    }}
    val rejectedInputs = fixture.path("reject_inputs").elements().asScala.toVector
    rejectedInputs.foreach { row => mustReject(row.path("label").asText("invalid input")) {
      val spec = LocalEeSpectralUnmixSpec.parse(row.path("spec").asText())
      val tile = tileFrom(row.path("input_bands"))
      val budget = LocalEeSpectralUnmixBudget.check(spec, tile.cols, tile.rows, 1L)
      val plan = LocalEeSpectralUnmixSolver.build(spec)
      LocalEeSpectralUnmixBudget.recheckTile(tile, spec, tile.cols, tile.rows, budget)
      LocalEeSpectralUnmixNumeric.applyTile(tile, spec, plan)
    }}
    val budgetSummary = checkBudgets()
    val result = Mapper.createObjectNode()
    result.put("schema", "local-ee-spectral-unmix-native-result/v1")
    val outputArray = result.putArray("cases")
    actualOutputs.foreach(outputArray.add)
    result.put("case_count", cases.length)
    result.put("invalid_spec_count", invalidSpecs.length)
    result.put("rejected_input_count", rejectedInputs.length)
    result.put("summary", s"SPECTRAL_UNMIX_KERNEL_OK cases=${cases.length} " +
      s"output_cells=${actualOutputs.map(_.path("output_cells").asInt()).sum} " +
      s"invalid_specs=${invalidSpecs.length} rejected_inputs=${rejectedInputs.length} " + budgetSummary)
    println("SPECTRAL_UNMIX_RESULT " + Mapper.writeValueAsString(result))
  }

  private def runCase(
    row: JsonNode, requireAnyNonzero: Boolean
  ): com.fasterxml.jackson.databind.node.ObjectNode = {
    val label = row.path("label").asText()
    val spec = LocalEeSpectralUnmixSpec.parse(row.path("spec").asText())
    val tile = tileFrom(row.path("input_bands"), row.path("input_cell_type").asText("float64"))
    val admission = LocalEeSpectralUnmixBudget.check(spec, tile.cols, tile.rows, 1L)
    val solver = LocalEeSpectralUnmixSolver.build(spec)
    LocalEeSpectralUnmixBudget.recheckTile(tile, spec, tile.cols, tile.rows, admission)
    val output = LocalEeSpectralUnmixNumeric.applyTile(tile, spec, solver)
    val expected = row.path("expected_values")
    require(expected.isArray && expected.size() == spec.components,
      s"$label expected output must contain one array per endmember")
    val expectedNames = row.path("expected_bands")
    require(expectedNames.isArray && expectedNames.size() == spec.components &&
      (0 until spec.components).forall(index => expectedNames.get(index).asText() == s"unmix$index"),
      s"$label output metadata must be unmix0..unmix${spec.components - 1}")
    val absolute = row.path("absolute_tolerance").asDouble(0d)
    val relative = row.path("relative_tolerance").asDouble(0d)
    require(absolute.isFinite && absolute >= 0d && relative.isFinite && relative >= 0d,
      s"$label tolerances must be finite and nonnegative")
    val actualJson = Mapper.createObjectNode()
    actualJson.put("label", label)
    actualJson.putArray("band_names").addAll((0 until spec.components).map(index =>
      Mapper.getNodeFactory.textNode(s"unmix$index")).asJava)
    val actualBands = actualJson.putArray("actual_bands")
    val checkedCells = Math.multiplyExact(output.bandCount, output.cols * output.rows)
    var component = 0
    while (component < output.bandCount) {
      val actualValues = actualBands.addArray()
      val expectedValues = expected.get(component)
      require(expectedValues.isArray && expectedValues.size() == output.cols * output.rows,
        s"$label expected component $component has the wrong pixel count")
      var pixel = 0
      while (pixel < output.cols * output.rows) {
        val value = output.band(component).getDouble(pixel % output.cols, pixel / output.cols)
        val target = parseValue(expectedValues.get(pixel))
        checkClose(label, component, pixel, value, target, absolute, relative)
        actualValues.add(formatValue(value))
        pixel += 1
      }
      component += 1
    }
    val required = row.path("require_nonzero").elements().asScala.toVector
    var foundNonzero = false
    required.foreach { coordinate =>
      require(coordinate.isArray && coordinate.size() == 2,
        s"$label required-nonzero entry must be [component,pixel]")
      val band = coordinate.get(0).asInt()
      val pixel = coordinate.get(1).asInt()
      require(band >= 0 && band < output.bandCount && pixel >= 0 && pixel < output.cols * output.rows,
        s"$label required-nonzero entry is outside the output")
      val value = output.band(band).getDouble(pixel % output.cols, pixel / output.cols)
      require(value.isFinite && value != 0d, s"$label expected a nonzero finite output")
      foundNonzero = true
    }
    if (requireAnyNonzero && required.isEmpty) {
      foundNonzero = (0 until output.bandCount).exists { band =>
        (0 until output.cols * output.rows).exists { pixel =>
          val value = output.band(band).getDouble(pixel % output.cols, pixel / output.cols)
          value.isFinite && value != 0d
        }
      }
    }
    if (requireAnyNonzero || required.nonEmpty) {
      require(foundNonzero, s"$label expected at least one finite nonzero output")
    }
    actualJson.put("output_cells", checkedCells)
    actualJson
  }

  private def checkBudgets(): String = {
    val scalar = LocalEeSpectralUnmixSpec.parse(
      "{\"endmembers\":[[\"3ff0000000000000\"]],\"nonNegative\":false," +
        "\"sumToOne\":false,\"v\":1}")
    val admission = LocalEeSpectralUnmixBudget.check(scalar, 1, 1, 1L)
    val pixelBoundary = (LocalEeSpectralUnmixBudget.MaxTileWork - admission.precomputeWork) /
      admission.perPixelWork
    require(pixelBoundary > 0L && pixelBoundary < 10000000L,
      "spectral-unmix tile-work boundary did not exercise the work cap")
    LocalEeSpectralUnmixBudget.check(scalar, pixelBoundary.toInt, 1, 1L)
    mustReject("per-tile work") {
      LocalEeSpectralUnmixBudget.check(scalar, Math.toIntExact(pixelBoundary + 1L), 1, 1L)
    }
    val wideRows = (0 until 6).map(_ => (0 until 8).map(_ => "\"3ff0000000000000\"")
      .mkString("[", ",", "]")).mkString("[", ",", "]")
    val wide = LocalEeSpectralUnmixSpec.parse(
      s"{\"endmembers\":$wideRows,\"nonNegative\":true,\"sumToOne\":true,\"v\":1}")
    val aggregateBase = LocalEeSpectralUnmixBudget.check(wide, 1, 1, 1L)
    val keyBoundary = (LocalEeSpectralUnmixBudget.MaxTotalWork - aggregateBase.precomputeWork) /
      aggregateBase.perPixelWork
    require(keyBoundary > 0L && keyBoundary < LocalEeSpectralUnmixBudget.MaxTileKeys,
      "spectral-unmix aggregate-work boundary must be below the independent key cap")
    LocalEeSpectralUnmixBudget.check(wide, 1, 1, keyBoundary)
    mustReject("aggregate work") {
      LocalEeSpectralUnmixBudget.check(wide, 1, 1, keyBoundary + 1L)
    }
    mustReject("tile-key cap") {
      LocalEeSpectralUnmixBudget.check(scalar, 1, 1,
        LocalEeSpectralUnmixBudget.MaxTileKeys + 1L)
    }
    mustReject("decoded-cell cap") {
      LocalEeSpectralUnmixBudget.check(scalar, 10000001, 1, 1L)
    }
    val eightRows = (0 until 8).map(_ => (0 until 8).map(_ => "\"3ff0000000000000\"")
      .mkString("[", ",", "]")).mkString("[", ",", "]")
    val eight = LocalEeSpectralUnmixSpec.parse(
      s"{\"endmembers\":$eightRows,\"nonNegative\":true,\"sumToOne\":true,\"v\":1}")
    mustReject("8x8 all-face precharge") {
      LocalEeSpectralUnmixBudget.check(eight, 1, 1, 1L)
    }
    val normal = LocalEeSpectralUnmixSpec.parse(
      "{\"endmembers\":[[\"3ff0000000000000\",\"0000000000000000\",\"0000000000000000\"]," +
        "[\"0000000000000000\",\"3ff0000000000000\",\"0000000000000000\"]," +
        "[\"0000000000000000\",\"0000000000000000\",\"3ff0000000000000\"]]," +
        "\"nonNegative\":true,\"sumToOne\":true,\"v\":1}")
    val normalBase = LocalEeSpectralUnmixBudget.check(normal, 1, 1, 1L)
    val normalPixelBoundary = (LocalEeSpectralUnmixBudget.MaxTileWork -
      normalBase.precomputeWork) / normalBase.perPixelWork
    require(normalPixelBoundary > 0L && normalPixelBoundary < 10000000L,
      "normal 3x3 simplex tile-work boundary is outside the decoded-cell envelope")
    LocalEeSpectralUnmixBudget.check(normal, Math.toIntExact(normalPixelBoundary), 1, 1L)
    mustReject("normal 3x3 simplex pixel boundary") {
      LocalEeSpectralUnmixBudget.check(normal, Math.toIntExact(normalPixelBoundary + 1L), 1, 1L)
    }
    mustReject("normal 3x3 simplex 256x256 tile") {
      LocalEeSpectralUnmixBudget.check(normal, 256, 256, 1L)
    }
    s"tile_boundary_pixels=$pixelBoundary key_boundary=$keyBoundary " +
      s"normal_3x3_simplex_max_tile_pixels=$normalPixelBoundary normal_256x256_rejected=true " +
      s"decoded_cell_limit=${LocalEeSpectralUnmixBudget.MaxTileDecodedCells} " +
      "precharged_svd_rank_faces_once=true"
  }

  private def tileFrom(node: JsonNode, cellType: String = "float64"): MultibandTile = {
    require(node.isArray && node.size() > 0, "spectral-unmix input bands must be a nonempty array")
    require(cellType == "float64" || cellType == "float32",
      "spectral-unmix fixture cell type must be float64 or float32")
    val bands = node.elements().asScala.map { values =>
      require(values.isArray && values.size() > 0, "spectral-unmix input bands must contain pixels")
      val cells = values.elements().asScala.map(parseValue).toArray
      if (cellType == "float32")
        FloatArrayTile(cells.map(_.toFloat), cells.length, 1, FloatConstantNoDataCellType): Tile
      else DoubleArrayTile(cells, cells.length, 1, DoubleConstantNoDataCellType): Tile
    }.toArray
    require(bands.forall(_.cols == bands(0).cols), "spectral-unmix input bands have unequal lengths")
    ArrayMultibandTile(bands)
  }

  private def parseValue(node: JsonNode): Double = {
    require(node.isTextual, "spectral-unmix fixture values must be strings")
    node.asText() match {
      case "NaN" => Double.NaN
      case "Infinity" => Double.PositiveInfinity
      case "-Infinity" => Double.NegativeInfinity
      case text => java.lang.Double.valueOf(text)
    }
  }

  private def formatValue(value: Double): String =
    if (value.isNaN) "NaN" else java.lang.Double.toString(if (value == 0d) 0d else value)

  private def checkClose(
    label: String, component: Int, pixel: Int, actual: Double, expected: Double,
    absolute: Double, relative: Double
  ): Unit = {
    if (expected.isNaN) {
      require(actual.isNaN, s"$label output $component pixel $pixel should be NoData, got $actual")
    } else {
      require(actual.isFinite, s"$label output $component pixel $pixel should be finite, got $actual")
      val tolerance = math.max(absolute,
        relative * math.max(math.abs(actual), math.abs(expected)))
      require(math.abs(actual - expected) <= tolerance,
        s"$label output $component pixel $pixel differs: $actual != $expected (tol=$tolerance)")
    }
  }

  private def mustReject(label: String)(action: => Any): Unit = {
    var rejected = false
    try action catch {
      case _: IllegalArgumentException => rejected = true
      case _: ArithmeticException => rejected = true
    }
    require(rejected, s"spectral-unmix $label control was accepted")
  }
}
