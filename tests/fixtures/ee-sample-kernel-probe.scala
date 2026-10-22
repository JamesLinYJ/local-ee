import com.fasterxml.jackson.databind.ObjectMapper
import geotrellis.layer.SpatialKey
import geotrellis.proj4.{CRS, LatLng, Transform}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, FloatArrayTile, FloatConstantNoDataCellType, MultibandTile, Tile}
import java.io.File
import local.ee.sample.LocalEeSampleKernel
import org.openeo.geotrelliscommon.{CubeProcessProvider, CubeProcessRegistry}
import scala.jdk.CollectionConverters._

/** Trusted standalone GeoTrellis tile probe: no SparkContext, service, or user script. */
object SampleKernelProbe {
  private val mapper = new ObjectMapper()

  private def number(value: Any): Double = value match {
    case null => Double.NaN
    case raw: Number => raw.doubleValue()
    case raw: String => java.lang.Double.parseDouble(raw)
    case _ => throw new IllegalArgumentException("fixture pixel must be a number or null")
  }

  private def tile(row: java.util.Map[String, Object]): MultibandTile = {
    val width = row.get("tile_cols").asInstanceOf[Number].intValue()
    val height = row.get("tile_rows").asInstanceOf[Number].intValue()
    val floating = row.get("cell_type") == "float32"
    val bands = row.get("bands").asInstanceOf[java.util.List[java.util.List[Any]]].asScala.map { values =>
      val input = values.asScala.map(number).toArray
      if (floating) FloatArrayTile(input.map(_.toFloat), width, height, FloatConstantNoDataCellType): Tile
      else DoubleArrayTile(input, width, height, DoubleConstantNoDataCellType): Tile
    }.toArray
    ArrayMultibandTile(bands)
  }

  private def runCase(row: java.util.Map[String, Object]): java.util.Map[String, Object] = {
    val out = new java.util.HashMap[String, Object]()
    try {
      val grid = LocalEeSampleKernel.Grid(
        row.get("xmin").asInstanceOf[Number].doubleValue(),
        row.get("ymin").asInstanceOf[Number].doubleValue(),
        row.get("xmax").asInstanceOf[Number].doubleValue(),
        row.get("ymax").asInstanceOf[Number].doubleValue(),
        row.get("columns").asInstanceOf[Number].longValue(),
        row.get("rows").asInstanceOf[Number].longValue(),
        row.get("tile_cols").asInstanceOf[Number].intValue(),
        row.get("tile_rows").asInstanceOf[Number].intValue())
      val wkts = row.get("regions").asInstanceOf[java.util.List[String]]
      val crs = CRS.fromEpsgCode(Option(row.get("epsg")).map(_.asInstanceOf[Number].intValue()).getOrElse(4326))
      val geometries = LocalEeSampleKernel.parseAndProjectWkts(wkts, crs)
      val features = LocalEeSampleKernel.prepareFeatures(geometries, grid)
      val toWgs84 = Transform(crs, LatLng)
      val records = LocalEeSampleKernel.sampleTile(tile(row),
        SpatialKey(row.get("key_col").asInstanceOf[Number].intValue(),
          row.get("key_row").asInstanceOf[Number].intValue()), grid, features, (x, y) => {
            val point = toWgs84(x, y)
            (point._1, point._2)
          })
      out.put("rejected", java.lang.Boolean.FALSE)
      out.put("rows", LocalEeSampleKernel.rowsJson(records))
    } catch {
      case _: IllegalArgumentException => out.put("rejected", java.lang.Boolean.TRUE)
    }
    out
  }

  def main(args: Array[String]): Unit = {
    val fixture = mapper.readValue(new File(args(0)), classOf[java.util.Map[String, Object]])
    val providers = java.util.ServiceLoader.load(classOf[CubeProcessProvider]).stream().iterator().asScala
      .map(_.get())
    val provider = providers.find(_.isInstanceOf[local.ee.sample.LocalEeSampleCubeProcessProvider])
    assert(provider.isDefined, "sampleRegions ServiceLoader provider missing from adapter JAR")
    assert(provider.get.getInstance().isInstanceOf[local.ee.sample.LocalEeSampleCubeProcesses])
    assert(CubeProcessRegistry.processIds().asScala.contains("local_ee_sample_regions"),
      "sampleRegions process annotation was not registered")

    val malformed = fixture.get("invalid_wkts").asInstanceOf[java.util.List[String]]
    var rejectedWkts = 0
    malformed.asScala.foreach { wkt =>
      var rejected = false
      try LocalEeSampleKernel.parseAndProjectWkts(java.util.Arrays.asList(wkt), CRS.fromEpsgCode(4326))
      catch { case _: IllegalArgumentException => rejected = true }
      assert(rejected, s"invalid WKT was accepted: $wkt")
      rejectedWkts += 1
    }

    val point = LocalEeSampleKernel.parseAndProjectWkts(java.util.Arrays.asList("POINT (1 1)"),
      CRS.fromEpsgCode(3857)).head.getCoordinate
    val edgeGrid = LocalEeSampleKernel.Grid(0.0, 0.0, 8.0, 6.0, 8, 6, 4, 3)
    val edgeGeometry = LocalEeSampleKernel.parseAndProjectWkts(java.util.Arrays.asList("POINT (4 2.8)"),
      CRS.fromEpsgCode(4326))
    val edgeFeatures = LocalEeSampleKernel.prepareFeatures(edgeGeometry, edgeGrid)
    val edgeCandidates = Seq(SpatialKey(0, 1), SpatialKey(1, 1))
      .count(key => LocalEeSampleKernel.tileMayIntersect(key, edgeGrid, edgeFeatures))
    assert(edgeCandidates == 2, "point-on-tile-boundary must retain both envelope candidates")
    val results = fixture.get("cases").asInstanceOf[java.util.List[java.util.Map[String, Object]]]
      .asScala.map(runCase).asJava
    val output = new java.util.HashMap[String, Object]()
    output.put("cases", results)
    output.put("projected_point", java.util.Arrays.asList(point.x, point.y))
    output.put("invalid_wkt_count", Int.box(rejectedWkts))
    output.put("tile_edge_candidate_count", Int.box(edgeCandidates))
    println("SAMPLE_KERNEL_RESULT " + mapper.writeValueAsString(output))
  }
}
