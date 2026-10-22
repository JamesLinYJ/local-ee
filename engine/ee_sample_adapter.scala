package local.ee.sample

import geotrellis.layer.SpatialKey
import geotrellis.proj4.{LatLng, Transform}
import geotrellis.raster.MultibandTile
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEOProcess}
import local.ee.reduce.LocalEeClassifyReduceBridge

import scala.jdk.CollectionConverters._

/** Bounded native sampleRegions adapter over the actual spatial raster cube. */
final class LocalEeSampleCubeProcesses extends Serializable {
  private val MaxSampleWork = 67108864L

  @OpenEOProcess(
    id = "local_ee_sample_regions",
    description = "Sample finite source-grid pixels under bounded planar WGS84 regions.",
    returns = "string"
  )
  def localEeSampleRegions(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("regions"),
      "local_ee_sample_regions requires only a regions argument")
    val rawRegions = arguments.get("regions") match {
      case values: java.util.List[_] => values.asScala.map {
        case value: String => value
        case _ => throw new IllegalArgumentException("regions must contain only WKT strings")
      }.toVector
      case _ => throw new IllegalArgumentException("regions must be a list of WKT strings")
    }
    require(rawRegions.length <= 1000, "local_ee_sample_regions supports at most 1000 regions")

    val input = LocalEeClassifyReduceBridge.validate(data, "local_ee_sample_regions")
    require(input.kind == "spatial", "local_ee_sample_regions requires a spatial cube without a time dimension")
    require(input.names.nonEmpty && input.names.length <= 64,
      "local_ee_sample_regions requires 1 to 64 source bands")

    val layout = input.source.metadata.layout
    val tileLayout = layout.tileLayout
    val columns = Math.multiplyExact(tileLayout.layoutCols.toLong, tileLayout.tileCols.toLong)
    val rows = Math.multiplyExact(tileLayout.layoutRows.toLong, tileLayout.tileRows.toLong)
    val extent = layout.extent
    val grid = LocalEeSampleKernel.Grid(extent.xmin, extent.ymin, extent.xmax, extent.ymax,
      columns, rows, input.cols, input.rows)

    val geometries = LocalEeSampleKernel.parseAndProjectWkts(rawRegions.asJava, input.source.metadata.crs)
    val features = LocalEeSampleKernel.prepareFeatures(geometries, grid)
    val minCol = input.minCol
    val minRow = input.minRow
    val maxCol = input.maxCol
    val maxRow = input.maxRow
    val minSpatial = input.minSpatial
    val maxSpatial = input.maxSpatial
    val bandCount = input.names.length
    val tileCols = input.cols
    val tileRows = input.rows
    val crs = input.source.metadata.crs
    // This first pass retains the existing all-key checks and independently checks every tile's
    // actual shape before ROI work is charged or any sample rows are produced.
    val validatedSource = input.source.map { case (rawKey, tile) =>
      require(LocalEeClassifyReduceBridge.keyInGrid(rawKey, "spatial", Set.empty,
        minCol, minRow, maxCol, maxRow, minSpatial, maxSpatial),
        "local_ee_sample_regions encountered a tile key outside metadata bounds")
      rawKey match {
        case value: SpatialKey => value
        case _ => throw new IllegalArgumentException("local_ee_sample_regions encountered a non-spatial tile key")
      }
      require(tile.bandCount == bandCount && tile.cols == tileCols && tile.rows == tileRows,
        "local_ee_sample_regions tile band count or dimensions changed within the cube")
      rawKey -> tile
    }
    val candidates = validatedSource.filter { case (rawKey, _) =>
      rawKey match {
        case key: SpatialKey => LocalEeSampleKernel.tileMayIntersect(key, grid, features)
        case _ => false
      }
    }
    val candidateKeyCount = candidates.keys.take(100001).length.toLong
    val tilePixels = Math.multiplyExact(tileCols.toLong, tileRows.toLong)
    if (features.nonEmpty && candidateKeyCount > 0) {
      val tileWork = Math.multiplyExact(tilePixels, features.length.toLong)
      require(tileWork <= MaxSampleWork && candidateKeyCount <= MaxSampleWork / tileWork,
        s"local_ee_sample_regions exceeds the $MaxSampleWork candidate-tile sampling-work budget")
    }

    val rowsRdd = candidates.flatMap { case (rawKey, tile) =>
      require(LocalEeClassifyReduceBridge.keyInGrid(rawKey, "spatial", Set.empty,
        minCol, minRow, maxCol, maxRow, minSpatial, maxSpatial),
        "local_ee_sample_regions encountered a candidate key outside metadata bounds")
      val key = rawKey.asInstanceOf[SpatialKey]
      require(tile.bandCount == bandCount && tile.cols == tileCols && tile.rows == tileRows,
        "local_ee_sample_regions candidate tile band count or dimensions changed")
      val transform = Transform(crs, LatLng)
      LocalEeSampleKernel.sampleTile(tile, key, grid, features, (x, y) => {
        val point = transform(x, y)
        (point._1, point._2)
      })
    }
    val result = rowsRdd.take(1001)
    require(result.length <= 1000, "local_ee_sample_regions result exceeds the 1000-row limit")
    LocalEeSampleKernel.rowsJson(result.toVector)
  }
}

/** ServiceLoader entry point for the atomic integer/raster adapter JAR. */
final class LocalEeSampleCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeSampleCubeProcesses()
}
