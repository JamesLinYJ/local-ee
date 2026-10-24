package local.ee.reduce

import com.fasterxml.jackson.databind.{JsonNode, ObjectMapper}
import geotrellis.layer.SpatialKey
import geotrellis.proj4.{CRS, LatLng, Transform}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import local.ee.image.sample.{LocalEeImageSampleKernel, LocalEeImageSampleOptions}
import local.ee.sample.LocalEeSampleKernel
import org.locationtech.jts.geom.{Envelope, Geometry, GeometryFactory, Polygon}
import org.openeo.geotrelliscommon.{CubeProcessProvider, CubeProcessRegistry}

import java.io.File
import java.nio.file.Files
import scala.jdk.CollectionConverters._

/** Actual GeoTrellis tiles through clip coverage, mask projection and Image.sample kernels. */
object EeClipCoverageKernelProbe {
  private val Mapper = new ObjectMapper()
  private val GeometryFactory = new GeometryFactory()
  private val ApplyMask = LocalEeMaskWeightsSpec.parse("{\"op\":\"apply\",\"v\":1}")
  private val CleanResult = LocalEeMaskWeightsSpec.parse("{\"op\":\"result_value\",\"v\":1}")
  private val Validity = LocalEeMaskWeightsSpec.parse("{\"op\":\"validity\",\"v\":1}")
  private val Update = LocalEeMaskWeightsSpec.parse("{\"op\":\"update\",\"v\":1}")

  private final case class Control(name: String, actual: Double, reference: Double,
                                    tolerance: Double, referenceSource: String)
  private final case class MaskedScience(values: Tile, weights: Tile)

  def main(args: Array[String]): Unit = {
    require(args.length == 1, "usage: EeClipCoverageKernelProbe ee-geodesic-clip-wave70-v1.json")
    val fixturePath = new File(args(0)).toPath.toRealPath()
    val fixtureBytes = Files.readAllBytes(fixturePath)
    val fixture = Mapper.readTree(fixtureBytes)
    require(fixture.get("schema").asText() == "local-ee-geodesic-clip-wave70/v1",
      "unexpected geodesic clip fixture schema")
    val contract = fixture.get("expected_clip_coverage_contract")
    val spec = LocalEeClipCoverageSpec.parse(contract.toString)
    val default256BudgetProbe = default256AdmissionProbe(spec)

    // Labeled synthetic native grid: this is not a Sentinel-2 asset or scale assertion.
    val crs = CRS.fromEpsgCode(32647)
    val grid = LocalEeClipCoverageGeometry.Grid(
      600000.0, 3340000.0, 680000.0, 3420000.0, 8L, 8L, 8, 8)
    val plan = LocalEeClipCoverageGeometry.plan(spec, crs, 32647, grid)
    val projected = LocalEeClipCoverageGeometry.project(spec, crs, 32647, grid, plan)
    val rawValues = Array.tabulate(64) { index =>
      if (index == 63) Double.NaN else 100.0 + index.toDouble
    }
    val raw = DoubleArrayTile(rawValues, 8, 8, DoubleConstantNoDataCellType)
    val rawBands = ArrayMultibandTile(Array[Tile](raw))
    val coverage = LocalEeClipCoverageNumeric.applyTile(rawBands, projected.geometry, grid,
      SpatialKey(0, 0), 8, 8)
    val clippedScience = LocalEeMaskWeightsNumeric.applyTile(
      ArrayMultibandTile(Array[Tile](raw, coverage)), ApplyMask)
    val unary = applyScienceMath(raw, coverage, "absolute", "[{\"band\":0}]")
    val scalarTwice = applyScienceMath(raw, coverage, "multiply",
      "[{\"band\":0},{\"constant\":\"4000000000000000\"}]")

    val regionWkt = polygonWkt(spec.polygons.head.head)
    val sampleGrid = LocalEeSampleKernel.Grid(
      grid.xmin, grid.ymin, grid.xmax, grid.ymax, grid.columns, grid.rows,
      grid.tileCols, grid.tileRows)
    val explicitRegion = LocalEeSampleKernel.prepareFeatures(
      LocalEeSampleKernel.parseAndProjectWkts(java.util.Arrays.asList(regionWkt), crs), sampleGrid).head
    val fullFootprint = LocalEeSampleKernel.prepareFeatures(Seq(
      GeometryFactory.toGeometry(new Envelope(grid.xmin, grid.xmax, grid.ymin, grid.ymax))), sampleGrid).head
    val toWgs84 = Transform(crs, LatLng)
    val key = SpatialKey(0, 0)
    val explicitFalse = sampleRows(ArrayMultibandTile(Array[Tile](clippedScience)), key,
      sampleGrid, explicitRegion, LocalEeImageSampleOptions.Value(None, None, 0, dropNulls = false), toWgs84)
    val explicitTrue = sampleRows(ArrayMultibandTile(Array[Tile](clippedScience)), key,
      sampleGrid, explicitRegion, LocalEeImageSampleOptions.Value(None, None, 0, dropNulls = true), toWgs84)
    val maskFalse = sampleRows(ArrayMultibandTile(Array[Tile](coverage)), key,
      sampleGrid, explicitRegion, LocalEeImageSampleOptions.Value(None, None, 0, dropNulls = false), toWgs84)
    // The no-region default binds the whole actual source footprint, so positive clip-edge
    // pixels are not accidentally removed by reapplying the clip polygon's center test.
    val defaultTrue = sampleRows(ArrayMultibandTile(Array[Tile](clippedScience)), key,
      sampleGrid, fullFootprint, LocalEeImageSampleOptions.Value(None, None, 0, dropNulls = true), toWgs84)
    val unaryDefaultTrue = sampleRows(ArrayMultibandTile(Array[Tile](unary.values)), key,
      sampleGrid, fullFootprint, LocalEeImageSampleOptions.Value(None, None, 0, dropNulls = true), toWgs84)
    val scalarDefaultTrue = sampleRows(ArrayMultibandTile(Array[Tile](scalarTwice.values)), key,
      sampleGrid, fullFootprint, LocalEeImageSampleOptions.Value(None, None, 0, dropNulls = true), toWgs84)

    require(coverage.getDouble(7, 7) == 0.0,
      "source NoData must produce a valid zero coverage value")
    var positiveCoverage = 0
    var partialCoverage = 0
    var index = 0
    while (index < 64) {
      val weight = coverage.getDouble(index % 8, index / 8)
      require(weight.isFinite && weight >= 0.0 && weight <= 1.0,
        "coverage tile contains a value outside [0,1]")
      if (weight > 0.0) {
        positiveCoverage += 1
        if (weight < 1.0) partialCoverage += 1
        val rawValue = raw.getDouble(index % 8, index / 8)
        val clippedValue = clippedScience.getDouble(index % 8, index / 8)
        if (rawValue.isFinite) require(clippedValue == rawValue,
          "clip coverage must not multiply the independent science value")
      } else require(clippedScience.getDouble(index % 8, index / 8).isNaN,
        "zero coverage must mask the clipped science value")
      require(unary.weights.getDouble(index % 8, index / 8) == weight &&
        scalarTwice.weights.getDouble(index % 8, index / 8) == weight,
        "unary/scalar science math must preserve the independent fractional clip weights")
      index += 1
    }
    require(positiveCoverage > 0 && partialCoverage > 0,
      "synthetic tile must exercise actual positive fractional boundary cells")
    require(explicitFalse.isArray && explicitTrue.isArray &&
      maskFalse.isArray && defaultTrue.isArray &&
      unaryDefaultTrue.isArray && scalarDefaultTrue.isArray,
      "sample kernels did not return their actual row arrays")

    val controls = numericControls()
    checkEmptyLayoutContacts()
    checkInfinityBeforeEmptyGeometry()
    val poleRoundTripRejected = checkPoleRoundingRejected()
    val providers = java.util.ServiceLoader.load(classOf[CubeProcessProvider]).stream()
      .iterator().asScala.map(_.get()).toVector
    require(providers.exists(_.isInstanceOf[LocalEeClipCoverageCubeProcessProvider]),
      "clip coverage ServiceLoader provider is absent from the actual adapter JAR")
    require(CubeProcessRegistry.processIds().asScala.contains("local_ee_clip_coverage"),
      "clip coverage SPI annotation is not registered")

    val output = new java.util.LinkedHashMap[String, Object]()
    output.put("schema", "local-ee-clip-coverage-native-tile-result/v1")
    output.put("producer", "local.ee.reduce.EeClipCoverageKernelProbe")
    output.put("fixture_schema", fixture.get("schema").asText())
    output.put("fixture_contract", Mapper.readTree(contract.toString))
    output.put("fixture_sha256", sha256(fixtureBytes))
    val gridRecord = new java.util.LinkedHashMap[String, Object]()
    gridRecord.put("kind", "synthetic-kernel-grid")
    gridRecord.put("crs", "EPSG:32647")
    gridRecord.put("xmin", java.lang.Double.valueOf(grid.xmin))
    gridRecord.put("ymin", java.lang.Double.valueOf(grid.ymin))
    gridRecord.put("xmax", java.lang.Double.valueOf(grid.xmax))
    gridRecord.put("ymax", java.lang.Double.valueOf(grid.ymax))
    gridRecord.put("columns", java.lang.Long.valueOf(grid.columns))
    gridRecord.put("rows", java.lang.Long.valueOf(grid.rows))
    gridRecord.put("tile_cols", Int.box(grid.tileCols))
    gridRecord.put("tile_rows", Int.box(grid.tileRows))
    gridRecord.put("cell_width_projected_units", java.lang.Double.valueOf(grid.cellWidth))
    gridRecord.put("cell_height_projected_units", java.lang.Double.valueOf(grid.cellHeight))
    gridRecord.put("key", java.util.Arrays.asList(0, 0))
    output.put("grid", gridRecord)
    output.put("source_band", "nir")
    output.put("raw_source_values_row_major", pixels(raw))
    output.put("coverage_band", "v")
    output.put("coverage_values_row_major", pixels(coverage))
    output.put("clipped_science_values_row_major", pixels(clippedScience))
    output.put("unary_absolute_science_values_row_major", pixels(unary.values))
    output.put("unary_absolute_mask_weights_row_major", pixels(unary.weights))
    output.put("scalar_multiply_2_science_values_row_major", pixels(scalarTwice.values))
    output.put("scalar_multiply_2_mask_weights_row_major", pixels(scalarTwice.weights))
    output.put("sample_rows", sampleRowsRecord(explicitFalse, explicitTrue, maskFalse,
      defaultTrue, unaryDefaultTrue, scalarDefaultTrue))
    output.put("default_256_admission_probe", default256BudgetProbe)
    output.put("tile_invariants", Map(
      "positive_coverage_cells" -> Int.box(positiveCoverage),
      "partial_coverage_cells" -> Int.box(partialCoverage),
      "source_nodata_cell_coverage_zero" -> java.lang.Boolean.TRUE,
      "fractional_coverage_keeps_raw_science_bits" -> java.lang.Boolean.TRUE,
      "zero_coverage_masks_science" -> java.lang.Boolean.TRUE,
      "nonpolar_intermediate_rejected" -> java.lang.Boolean.valueOf(poleRoundTripRejected),
      "sample_row_schema" -> Seq("feature", "row", "col", "x", "y", "values").asJava
    ).asJava)
    output.put("independent_numeric_reference_controls", controls.asJava)
    output.put("scope", "Actual GeoTrellis tile kernels and registered native provider; " +
      "synthetic source grid and values; no SparkContext, service, Google request, or private raster.")
    println("EE_CLIP_COVERAGE_TILE_RESULT " + Mapper.writeValueAsString(output))
  }

  private def sampleRows(
    tile: MultibandTile, key: SpatialKey, grid: LocalEeSampleKernel.Grid,
    feature: LocalEeSampleKernel.FeatureGeometry, options: LocalEeImageSampleOptions.Value,
    toWgs84: (Double, Double) => (Double, Double)
  ): JsonNode = {
    val population = LocalEeImageSampleKernel.cellsInTile(key, grid, feature).length.toLong
    val rows = LocalEeImageSampleKernel.sampleTileIterator(Some(tile), key, grid, feature,
      options, tile.bandCount, population, toWgs84).toVector
    Mapper.readTree(LocalEeImageSampleKernel.rowsJson(rows))
  }

  /** Reuse the production admission method for a common one-degree 256x256 source tile. */
  private def default256AdmissionProbe(
    spec: LocalEeClipCoverageSpec.Value
  ): java.util.Map[String, Object] = {
    val crs = CRS.fromEpsgCode(4326)
    val grid = LocalEeClipCoverageGeometry.Grid(100.0, 30.0, 101.0, 31.0,
      256L, 256L, 256, 256)
    val plan = LocalEeClipCoverageGeometry.plan(spec, crs, 4326, grid)
    val tileCells = 256L * 256L
    val admission = LocalEeClipCoverageBudget.admit(
      spec.positions, plan, grid, 1L, 1L, tileCells, tileCells
    )(() => LocalEeClipCoverageGeometry.project(spec, crs, 4326, grid, plan).geometry)
    val source = ArrayMultibandTile(Array[Tile](constantTile(1.0, 256, 256)))
    val coverage = LocalEeClipCoverageNumeric.applyTile(source, admission.geometry, grid,
      SpatialKey(0, 0), 256, 256)
    var positive = 0L
    var partial = 0L
    var sum = 0.0
    var row = 0
    while (row < 256) {
      var col = 0
      while (col < 256) {
        val value = coverage.getDouble(col, row)
        require(value.isFinite && value >= 0.0 && value <= 1.0,
          "default 256x256 synthetic coverage contains an invalid weight")
        if (value > 0.0) {
          positive += 1L
          if (value < 1.0) partial += 1L
          sum += value
        }
        col += 1
      }
      row += 1
    }
    val coveringSpec = LocalEeClipCoverageSpec.Value(Vector(polygon(
      Vector((80,0),(120,0),(120,60),(80,60),(80,0)))), 5)
    val coveringPlan = LocalEeClipCoverageGeometry.plan(coveringSpec, crs, 4326, grid)
    val coveringCells = LocalEeClipCoverageBudget.admit(
      coveringSpec.positions, coveringPlan, grid, 1L, 1L, tileCells, tileCells
    )(() => LocalEeClipCoverageGeometry.project(coveringSpec, crs, 4326, grid, coveringPlan).geometry)
    val coveringTile = LocalEeClipCoverageNumeric.applyTile(source, coveringCells.geometry, grid,
      SpatialKey(0, 0), 256, 256)
    var coveringCellCount = 0L
    row = 0
    while (row < 256) {
      var col = 0
      while (col < 256) {
        require(coveringTile.getDouble(col, row) == 1.0,
          "a polygon covering the source grid must yield full cell coverage")
        coveringCellCount += 1L
        col += 1
      }
      row += 1
    }
    val result = new java.util.LinkedHashMap[String, Object]()
    result.put("label", "synthetic-256x256-one-degree-EPSG4326-grid")
    result.put("extent", java.util.Arrays.asList(100.0, 30.0, 101.0, 31.0))
    result.put("tile_cols", Int.box(256))
    result.put("tile_rows", Int.box(256))
    result.put("observed_time_count", Long.box(1L))
    result.put("geometry_segments", Long.box(plan.segments))
    result.put("projected_boundary_segments", Long.box(admission.boundarySegments))
    result.put("bbox_candidate_visits", Long.box(admission.boundaryVisits))
    result.put("unique_global_boundary_cells", Long.box(admission.uniqueBoundaryCells))
    result.put("charged_boundary_cells", admission.boundaryCells.toString)
    result.put("total_work", admission.totalWork.toString)
    result.put("max_work", Long.box(LocalEeClipCoverageBudget.MaxCoverageWork))
    result.put("admitted", java.lang.Boolean.TRUE)
    result.put("actual_positive_coverage_cells", Long.box(positive))
    result.put("actual_partial_coverage_cells", Long.box(partial))
    result.put("actual_coverage_weight_sum", java.lang.Double.valueOf(sum))
    result.put("full_layout_cover_plan_boundary_bound",
      coveringPlan.boundaryCellUpperBoundPerTile.toString)
    result.put("full_layout_cover_charged_boundary_cells", coveringCells.boundaryCells.toString)
    result.put("full_layout_cover_actual_cells", Long.box(coveringCellCount))
    result
  }

  private def sampleRowsRecord(
    explicitFalse: JsonNode, explicitTrue: JsonNode, maskFalse: JsonNode, defaultTrue: JsonNode,
    unaryDefaultTrue: JsonNode, scalarDefaultTrue: JsonNode
  ): java.util.Map[String, Object] = {
    val result = new java.util.LinkedHashMap[String, Object]()
    result.put("explicit_roi_clip_sample_drop_nulls_false", explicitFalse)
    result.put("explicit_roi_clip_sample_drop_nulls_true", explicitTrue)
    result.put("explicit_roi_mask_getter_sample_drop_nulls_false", maskFalse)
    result.put("source_footprint_default_sample_drop_nulls_true", defaultTrue)
    result.put("source_footprint_unary_absolute_sample_drop_nulls_true", unaryDefaultTrue)
    result.put("source_footprint_scalar_multiply_2_sample_drop_nulls_true", scalarDefaultTrue)
    result
  }

  private def applyScienceMath(raw: Tile, oldWeight: Tile, operation: String,
                               operands: String): MaskedScience = {
    val guardedRaw = LocalEeMaskWeightsNumeric.applyTile(
      ArrayMultibandTile(Array[Tile](raw, constantTile(1.0, raw.cols, raw.rows))), ApplyMask)
    val wire = s"{\"dtype\":null,\"op\":\"$operation\",\"operands\":$operands,\"v\":1}"
    val spec = LocalEeIntegerValuesSpec.parse(wire)
    val rawResult = LocalEeIntegerValuesNumeric.applyTile(ArrayMultibandTile(Array[Tile](guardedRaw)), spec)
    val clean = LocalEeMaskWeightsNumeric.applyTile(ArrayMultibandTile(Array[Tile](rawResult)), CleanResult)
    val valid = LocalEeMaskWeightsNumeric.applyTile(ArrayMultibandTile(Array[Tile](clean)), Validity)
    val weight = LocalEeMaskWeightsNumeric.applyTile(ArrayMultibandTile(Array[Tile](valid, oldWeight)), Update)
    val values = LocalEeMaskWeightsNumeric.applyTile(ArrayMultibandTile(Array[Tile](clean, weight)), ApplyMask)
    MaskedScience(values, weight)
  }

  private def numericControls(): Vector[java.util.Map[String, Object]] = {
    val cases = Vector(
      coverageCase("meridian_half", 4326, -1.0, -1.0, 1.0, 1.0,
        Vector(polygon(Vector((-20,-20),(0,-20),(0,20),(-20,20),(-20,-20)))), 0.5, 1e-12,
        "independent exact meridian overlap"),
      coverageCase("meridian_touch_zero", 4326, -1.0, -1.0, 1.0, 1.0,
        Vector(polygon(Vector((1.0,-20.0),(20.0,-20.0),(20.0,20.0),(1.0,20.0),(1.0,-20.0)))),
        0.0, 0.0, "independent exact meridian boundary contact"),
      coverageCase("meridian_near_touch_positive_2^-52", 4326, -1.0, -1.0, 1.0, 1.0,
        Vector(polygon(Vector((1.0-math.pow(2.0,-51),-20.0),(20.0,-20.0),(20.0,20.0),
          (1.0-math.pow(2.0,-51),20.0),(1.0-math.pow(2.0,-51),-20.0)))),
        math.pow(2.0,-52), 0.0, "independent exact representable positive meridian sliver"),
      coverageCase("hole_contains_center", 4326, -1.0, -1.0, 1.0, 1.0,
        Vector(polygon(Vector((-20,-20),(20,-20),(20,20),(-20,20),(-20,-20)),
          Vector(Vector((-0.5,-10),(0.5,-10),(0.5,10),(-0.5,10),(-0.5,-10))))), 0.5, 1e-12,
        "independent exact meridian shell-minus-hole overlap"),
      coverageCase("multipart_disjoint", 4326, -1.0, -1.0, 1.0, 1.0,
        Vector(polygon(Vector((-2,-10),(-0.75,-10),(-0.75,10),(-2,10),(-2,-10))),
          polygon(Vector((0.5,-10),(2,-10),(2,10),(0.5,10),(0.5,-10)))), 0.375, 1e-12,
        "independent exact meridian multipart overlap"),
      coverageCase("tiny_positive_2^-31", 4326, -1.0, -1.0, 1.0, 1.0,
        Vector(polygon(Vector((1.0/1024.0,-10.0),(1.0/1024.0+math.pow(2.0,-30),-10.0),
          (1.0/1024.0+math.pow(2.0,-30),10.0),(1.0/1024.0,10.0),(1.0/1024.0,-10.0)))),
        math.pow(2.0,-31), 1e-14, "independent exact positive meridian sliver"),
      coverageCase("high_latitude_outside_center", 4326, -5.0, 60.0, 5.0, 70.0,
        Vector(polygon(Vector((-40,60),(40,60),(40,70),(-40,70),(-40,60)))),
        0.3885597161386822, 2e-6, "independent spherical integral reference"),
      coverageCase("equator_inflection_half_cell", 4326, 0.0, -8.0, 8.0, 0.0,
        Vector(polygon(Vector((0,-8),(16,8),(16,15),(0,15),(0,-8)))),
        0.5024448690956461, 2e-6, "independent dense-curve projected-area convergence"),
      coverageCase("utm_32n_native_cell", 32632, 450000.0, 6800000.0, 650000.0, 7000000.0,
        Vector(polygon(Vector((8,58),(12,58),(12,62),(8,62),(8,58)))),
        0.38080038179637254, 2e-6, "independent dense-curve PROJ/GEOS convergence"),
      coverageCase("web_mercator_native_cell", 3857, 1000000.0, 8300000.0, 1400000.0, 9100000.0,
        Vector(polygon(Vector((8,58),(12,58),(12,62),(8,62),(8,58)))),
        0.589510924140391, 2e-6, "independent dense-curve PROJ/GEOS convergence")
    )
    cases
  }

  private def coverageCase(name: String, epsg: Int, xmin: Double, ymin: Double,
                           xmax: Double, ymax: Double,
                           polygons: Vector[Vector[Vector[LocalEeClipCoverageSpec.Position]]],
                           reference: Double, tolerance: Double, referenceSource: String): java.util.Map[String, Object] = {
    val positions = polygons.iterator.flatMap(_.iterator).map(_.length).sum
    val spec = LocalEeClipCoverageSpec.Value(polygons, positions)
    val crs = CRS.fromEpsgCode(epsg)
    val grid = LocalEeClipCoverageGeometry.Grid(xmin, ymin, xmax, ymax, 1L, 1L, 1, 1)
    val plan = LocalEeClipCoverageGeometry.plan(spec, crs, epsg, grid)
    val geometry = LocalEeClipCoverageGeometry.project(spec, crs, epsg, grid, plan).geometry
    val input = ArrayMultibandTile(Array[Tile](DoubleArrayTile(Array(1.0), 1, 1,
      DoubleConstantNoDataCellType)))
    val actual = LocalEeClipCoverageNumeric.applyTile(input, geometry, grid, SpatialKey(0, 0), 1, 1)
      .getDouble(0, 0)
    require(math.abs(actual - reference) <= tolerance,
      s"$name native fraction $actual differs from separate reference $reference")
    val result = new java.util.LinkedHashMap[String, Object]()
    result.put("id", name)
    result.put("actual_native_fraction", java.lang.Double.valueOf(actual))
    result.put("separate_reference_fraction", java.lang.Double.valueOf(reference))
    result.put("absolute_difference", java.lang.Double.valueOf(math.abs(actual - reference)))
    result.put("tolerance", java.lang.Double.valueOf(tolerance))
    result.put("reference_source", referenceSource)
    result
  }

  private def checkEmptyLayoutContacts(): Unit = {
    val grid = LocalEeClipCoverageGeometry.Grid(-1.0, -1.0, 1.0, 1.0, 1L, 1L, 1, 1)
    val crs = CRS.fromEpsgCode(4326)
    val touching = LocalEeClipCoverageSpec.Value(Vector(polygon(
      Vector((1,-1),(2,-1),(2,1),(1,1),(1,-1)))), 5)
    val disjoint = LocalEeClipCoverageSpec.Value(Vector(polygon(
      Vector((2,-1),(3,-1),(3,1),(2,1),(2,-1)))), 5)
    Vector(touching, disjoint).foreach { spec =>
      val plan = LocalEeClipCoverageGeometry.plan(spec, crs, 4326, grid)
      val geometry = LocalEeClipCoverageGeometry.project(spec, crs, 4326, grid, plan).geometry
      require(geometry.isEmpty, "touching/disjoint source layouts must produce empty coverage geometry")
      val tile = ArrayMultibandTile(Array[Tile](DoubleArrayTile(Array(1.0), 1, 1,
        DoubleConstantNoDataCellType)))
      require(LocalEeClipCoverageNumeric.applyTile(tile, geometry, grid, SpatialKey(0, 0), 1, 1)
        .getDouble(0, 0) == 0.0, "empty coverage geometry must yield a valid zero tile")
    }
  }

  private def checkInfinityBeforeEmptyGeometry(): Unit = {
    val grid = LocalEeClipCoverageGeometry.Grid(0.0, 0.0, 1.0, 1.0, 1L, 1L, 1, 1)
    val empty = GeometryFactory.createMultiPolygon(Array.empty[Polygon])
    val tile = ArrayMultibandTile(Array[Tile](DoubleArrayTile(Array(Double.PositiveInfinity), 1, 1,
      DoubleConstantNoDataCellType)))
    var rejected = false
    try LocalEeClipCoverageNumeric.applyTile(tile, empty, grid, SpatialKey(0, 0), 1, 1)
    catch { case _: IllegalArgumentException => rejected = true }
    require(rejected, "source infinity must be rejected before an empty-geometry shortcut")
  }

  private def checkPoleRoundingRejected(): Boolean = {
    val almostPole = 90.0 - 1e-10
    val spec = LocalEeClipCoverageSpec.Value(Vector(polygon(
      Vector((-0.5, almostPole), (0.5, almostPole), (0.0, 89.0), (-0.5, almostPole)))), 4)
    val grid = LocalEeClipCoverageGeometry.Grid(-2.0, 80.0, 2.0, 90.0, 1L, 1L, 1, 1)
    var rejected = false
    try LocalEeClipCoverageGeometry.plan(spec, CRS.fromEpsgCode(4326), 4326, grid)
    catch { case error: IllegalArgumentException =>
      rejected = Option(error.getMessage).exists(_.contains("non-polar WGS84"))
    }
    require(rejected,
      "a great-circle sample rounded to the pole must reject instead of flattening to latitude 90")
    rejected
  }

  private def polygon(
    exterior: Seq[(Double, Double)], holes: Seq[Seq[(Double, Double)]] = Seq.empty
  ): Vector[Vector[LocalEeClipCoverageSpec.Position]] = {
    val rings: Seq[Seq[(Double, Double)]] = Seq(exterior) ++ holes
    rings.iterator.map { ring =>
      ring.iterator.map { position =>
        LocalEeClipCoverageSpec.Position(position._1, position._2)
      }.toVector
    }.toVector
  }

  private def polygonWkt(ring: Vector[LocalEeClipCoverageSpec.Position]): String =
    "POLYGON ((" + ring.map(point => s"${point.lon} ${point.lat}").mkString(", ") + "))"

  private def constantTile(value: Double, cols: Int, rows: Int): Tile =
    DoubleArrayTile(Array.fill(cols * rows)(value), cols, rows, DoubleConstantNoDataCellType)

  private def pixels(tile: Tile): java.util.List[Object] = {
    val values = new java.util.ArrayList[Object](tile.cols * tile.rows)
    var row = 0
    while (row < tile.rows) {
      var col = 0
      while (col < tile.cols) {
        val value = tile.getDouble(col, row)
        values.add(if (value.isNaN) null else java.lang.Double.valueOf(value))
        col += 1
      }
      row += 1
    }
    values
  }

  private def sha256(bytes: Array[Byte]): String = {
    val digest = java.security.MessageDigest.getInstance("SHA-256").digest(bytes)
    digest.map(value => f"${value & 0xff}%02x").mkString
  }
}
