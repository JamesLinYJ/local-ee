import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.SpatialKey
import geotrellis.proj4.CRS
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, FloatArrayTile, FloatConstantNoDataCellType, MultibandTile, Tile}
import java.io.File
import local.ee.image.sample.{LocalEeImageSampleCubeProcessProvider, LocalEeImageSampleCubeProcesses, LocalEeImageSampleKernel, LocalEeImageSampleOptions}
import local.ee.sample.LocalEeSampleKernel
import org.locationtech.jts.geom.Geometry
import org.openeo.geotrelliscommon.{CubeProcessProvider, CubeProcessRegistry}
import scala.jdk.CollectionConverters._

/** Trusted standalone Image.sample kernel probe; no SparkContext or engine service. */
object ImageSampleKernelProbe {
  private val mapper = new ObjectMapper()

  private def number(value: Any): Double = value match {
    case null => Double.NaN
    case raw: Number => raw.doubleValue()
    case _ => throw new IllegalArgumentException("fixture pixel must be a number or null")
  }

  private def tile(row: java.util.Map[String, Object]): MultibandTile = {
    val bands = row.get("bands").asInstanceOf[java.util.List[java.util.List[Any]]].asScala.map { values =>
      val input = values.asScala.map(number).toArray
      if (row.get("cell_type") == "float32")
        FloatArrayTile(input.map(_.toFloat), 2, 2, FloatConstantNoDataCellType): Tile
      else DoubleArrayTile(input, 2, 2, DoubleConstantNoDataCellType): Tile
    }.toArray
    ArrayMultibandTile(bands)
  }

  private def runCase(
    row: java.util.Map[String, Object], grid: LocalEeSampleKernel.Grid,
    tiles: Map[SpatialKey, MultibandTile], reverse: Boolean
  ): String = {
    val geometry: Geometry = LocalEeSampleKernel.parseAndProjectWkts(
      java.util.Arrays.asList(row.get("wkt").asInstanceOf[String]), CRS.fromEpsgCode(4326)).head
    val feature = LocalEeSampleKernel.prepareFeatures(Seq(geometry), grid).head
    val keys = LocalEeImageSampleKernel.candidateKeys(
      feature, grid, SpatialKey(0, 0), SpatialKey(3, 1))
    val rawOptions = mapper.writeValueAsString(row.get("options"))
    val options = LocalEeImageSampleOptions.parse(rawOptions)
    val population = if (options.numPixels.contains(0)) 0L else
      keys.iterator.flatMap(key => LocalEeImageSampleKernel.cellsInTile(key, grid, feature)).length.toLong
    val order = if (reverse) keys.reverse else keys
    val records = order.iterator.flatMap { key =>
      LocalEeImageSampleKernel.sampleTileIterator(tiles.get(key), key, grid, feature, options,
        2, population, (x, y) => (x, y))
    }.toVector
    LocalEeImageSampleKernel.rowsJson(records)
  }

  private def rejectOptions(value: String): Boolean = try {
    LocalEeImageSampleOptions.parse(value)
    false
  } catch { case _: IllegalArgumentException => true }

  /** A finite 3-tile metadata extent with actual source bounds ending at tile 0. */
  private def missingEdgeTileRegression(): java.util.Map[String, Object] = {
    val grid = LocalEeSampleKernel.Grid(0, 0, 6, 2, 6, 2, 2, 2)
    val geometry = LocalEeSampleKernel.parseAndProjectWkts(
      java.util.Arrays.asList("POLYGON ((2 2, 4 2, 4 0, 2 0, 2 2))"), CRS.fromEpsgCode(4326)).head
    val feature = LocalEeSampleKernel.prepareFeatures(Seq(geometry), grid).head

    // The actual RDD has only key (0, 0), while the finite metadata extent spans keys 0..2.
    val sourceMin = SpatialKey(0, 0)
    val sourceMax = SpatialKey(0, 0)
    val finiteMin = SpatialKey(0, 0)
    val finiteMax = SpatialKey(2, 0)
    val finiteCandidates = LocalEeImageSampleKernel.candidateKeys(feature, grid, finiteMin, finiteMax)
    val incorrectlySourceBounded = LocalEeImageSampleKernel.candidateKeys(feature, grid, sourceMin, sourceMax)
    assert(finiteCandidates == Vector(SpatialKey(1, 0)))
    assert(incorrectlySourceBounded.isEmpty, "regression ROI must lie beyond actual source bounds")

    val options = LocalEeImageSampleOptions.parse(
      "{\"algorithm\":\"splitmix64-grid-v1\",\"factor\":null,\"num_pixels\":null,\"seed\":0,\"drop_nulls\":false}")
    val population = finiteCandidates.iterator
      .flatMap(key => LocalEeImageSampleKernel.cellsInTile(key, grid, feature)).length.toLong
    val rows = finiteCandidates.iterator.flatMap { key =>
      LocalEeImageSampleKernel.sampleTileIterator(None, key, grid, feature, options, 2, population,
        (x, y) => (x, y))
    }.toVector
    assert(rows.length == 4 && rows.forall(_.values == Vector(None, None)),
      "missing finite edge tile must produce nullable rows when drop_nulls is false")

    val result = new java.util.HashMap[String, Object]()
    result.put("actual_source_bounds", java.util.Arrays.asList(0, 0, 0, 0))
    result.put("finite_tile_bounds", java.util.Arrays.asList(0, 0, 2, 0))
    result.put("finite_candidate_keys", finiteCandidates.map(key => java.util.Arrays.asList(key.col, key.row)).asJava)
    result.put("source_bounds_candidates_empty", java.lang.Boolean.valueOf(incorrectlySourceBounded.isEmpty))
    result.put("rows", LocalEeImageSampleKernel.rowsJson(rows))
    result
  }

  private def checkKernelGuards(): Unit = {
    val large = LocalEeSampleKernel.Grid(0, 0, 180, 90, 1001, 1001, 1, 1)
    val whole = LocalEeSampleKernel.parseAndProjectWkts(
      java.util.Arrays.asList("POLYGON ((0 90, 180 90, 180 0, 0 0, 0 90))"), CRS.fromEpsgCode(4326)).head
    val oversized = LocalEeSampleKernel.prepareFeatures(Seq(whole), large).head
    var keyBudgetRejected = false
    try LocalEeImageSampleKernel.candidateKeys(oversized, large, SpatialKey(0, 0), SpatialKey(1000, 1000))
    catch { case _: IllegalArgumentException => keyBudgetRejected = true }
    assert(keyBudgetRejected, "oversized metadata grid key generation was not bounded")

    val one = LocalEeSampleKernel.Grid(0, 0, 1, 1, 1, 1, 1, 1)
    val point = LocalEeSampleKernel.prepareFeatures(
      LocalEeSampleKernel.parseAndProjectWkts(java.util.Arrays.asList("POINT (0.5 0.5)"),
        CRS.fromEpsgCode(4326)), one).head
    val infinity = ArrayMultibandTile(Array[Tile](DoubleArrayTile(
      Array(Double.PositiveInfinity), 1, 1, DoubleConstantNoDataCellType)))
    val options = LocalEeImageSampleOptions.parse(
      "{\"algorithm\":\"splitmix64-grid-v1\",\"factor\":null,\"num_pixels\":null,\"seed\":0,\"drop_nulls\":false}")
    var infinityRejected = false
    try LocalEeImageSampleKernel.sampleTileIterator(Some(infinity), SpatialKey(0, 0), one,
      point, options, 1, 1L, (x, y) => (x, y)).toVector
    catch { case _: IllegalArgumentException => infinityRejected = true }
    assert(infinityRejected, "non-null infinite image values must be rejected")
  }

  def main(args: Array[String]): Unit = {
    val fixture = mapper.readValue(new File(args(0)), classOf[java.util.Map[String, Object]])
    val provider = java.util.ServiceLoader.load(classOf[CubeProcessProvider]).stream().iterator().asScala
      .map(_.get()).find(_.isInstanceOf[LocalEeImageSampleCubeProcessProvider])
    assert(provider.isDefined, "Image.sample ServiceLoader provider is missing from the adapter JAR")
    assert(provider.get.getInstance().isInstanceOf[LocalEeImageSampleCubeProcesses])
    assert(CubeProcessRegistry.processIds().asScala.contains("local_ee_image_sample"),
      "Image.sample SPI annotation was not registered")

    val grid = LocalEeSampleKernel.Grid(0, 0, 8, 4, 8, 4, 2, 2)
    val tileRows = fixture.get("tiles").asInstanceOf[java.util.List[java.util.Map[String, Object]]]
    val tiles = tileRows.asScala.map(row =>
      SpatialKey(row.get("col").asInstanceOf[Number].intValue(),
        row.get("row").asInstanceOf[Number].intValue()) -> tile(row)).toMap
    val cases = fixture.get("regions").asInstanceOf[java.util.List[java.util.Map[String, Object]]]
      .asScala.map { row =>
        val forward = runCase(row, grid, tiles, reverse = false)
        val reverse = runCase(row, grid, tiles, reverse = true)
        assert(forward == reverse, s"partition/tile order changed ${row.get("name")} samples")
        val result = new java.util.HashMap[String, Object]()
        result.put("name", row.get("name"))
        result.put("rows", forward)
        result.put("order_invariant", java.lang.Boolean.TRUE)
        result
      }.asJava
    val invalid = fixture.get("invalid_options").asInstanceOf[java.util.List[String]]
    val rejectedOptions = invalid.asScala.count(rejectOptions)
    assert(rejectedOptions == invalid.size(), "an invalid Image.sample option wire value was accepted")
    checkKernelGuards()

    val output = new java.util.HashMap[String, Object]()
    output.put("fixture_version", fixture.get("fixture_version"))
    output.put("cases", cases)
    output.put("invalid_options_rejected", Int.box(rejectedOptions))
    output.put("missing_tile_present", java.lang.Boolean.valueOf(!tiles.contains(SpatialKey(1, 1))))
    output.put("missing_edge_tile", missingEdgeTileRegression())
    println("IMAGE_SAMPLE_KERNEL_RESULT " + mapper.writeValueAsString(output))
  }
}
