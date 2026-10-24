package local.ee.reduce

import geotrellis.layer.{SpatialKey, SpaceTimeKey}
import geotrellis.proj4.CRS
import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded native producer for projected great-circle polygon-cell area fractions. */
final class LocalEeClipCoverageCubeProcesses extends Serializable {
  private val MaxTileKeys = 100000
  private val MaxTileCells = 10000000L
  private val MaxDecodedCells = 100000000L

  @OpenEOProcess(
    id = "local_ee_clip_coverage",
    description = "Compute projected polygon-cell area fractions on an actual raster grid.",
    returns = "datacube"
  )
  def localEeClipCoverage(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_clip_coverage requires only a spec argument")
    val wire = arguments.get("spec") match {
      case value: String => value
      case _ => throw new IllegalArgumentException("clip coverage spec must be a JSON string")
    }
    val spec = LocalEeClipCoverageSpec.parse(wire)
    val input = LocalEeClassifyReduceBridge.validate(data, "local_ee_clip_coverage")
    require(input.names.length == 1,
      "local_ee_clip_coverage requires exactly one actual source band")

    val metadata = input.source.metadata
    val layout = metadata.layout
    val tileLayout = layout.tileLayout
    val grid = LocalEeClipCoverageGeometry.Grid(
      layout.extent.xmin, layout.extent.ymin, layout.extent.xmax, layout.extent.ymax,
      Math.multiplyExact(tileLayout.layoutCols.toLong, tileLayout.tileCols.toLong),
      Math.multiplyExact(tileLayout.layoutRows.toLong, tileLayout.tileRows.toLong),
      tileLayout.tileCols, tileLayout.tileRows)
    val epsg = supportedEpsg(metadata.crs)
    val plan = LocalEeClipCoverageGeometry.plan(spec, metadata.crs, epsg, grid)

    // Count the real cube keys before allocating the projected JTS geometry or output RDD.
    val keyCount = input.source.keys.take(MaxTileKeys + 1).length.toLong
    require(keyCount > 0L && keyCount <= MaxTileKeys,
      s"local_ee_clip_coverage supports 1 to $MaxTileKeys tile keys")
    val tileCells = Math.multiplyExact(input.cols.toLong, input.rows.toLong)
    require(tileCells > 0L && tileCells <= MaxTileCells,
      s"local_ee_clip_coverage tile exceeds the $MaxTileCells-cell limit")
    val decodedCells = Math.multiplyExact(tileCells, keyCount)
    require(decodedCells <= MaxDecodedCells,
      s"local_ee_clip_coverage exceeds the $MaxDecodedCells decoded-cell limit")
    val observedTimeCount = if (input.kind == "temporal") input.times.size.toLong.max(1L) else 1L
    // The shared admission routine precharges construction before projecting, then traces and
    // deduplicates bounded global boundary-cell candidates before any output RDD is allocated.
    val admission = LocalEeClipCoverageBudget.admit(
      spec.positions, plan, grid, keyCount, observedTimeCount, tileCells, decodedCells
    )(() => LocalEeClipCoverageGeometry.project(spec, metadata.crs, epsg, grid, plan).geometry)

    // Spark captures immutable geometry/grid facts, not the cube or ContextRDD wrapper.
    val source = input.source
    val cols = input.cols
    val rows = input.rows
    val kind = input.kind
    val times = input.times.toSet
    val minCol = input.minCol
    val minRow = input.minRow
    val maxCol = input.maxCol
    val maxRow = input.maxRow
    val minSpatial = input.minSpatial
    val maxSpatial = input.maxSpatial
    val geometry = admission.geometry
    val output: RDD[(Any, MultibandTile)] = source.map { case (key, tile) =>
      require(LocalEeClassifyReduceBridge.keyInGrid(key, kind, times, minCol, minRow,
        maxCol, maxRow, minSpatial, maxSpatial),
        "local_ee_clip_coverage key lies outside declared source grid bounds")
      require(tile != null && tile.bandCount == 1 && tile.cols == cols && tile.rows == rows,
        "local_ee_clip_coverage source tile band count or dimensions changed within the cube")
      val spatial = key match {
        case value: SpatialKey => value
        case value: SpaceTimeKey => value.spatialKey
        case _ => throw new IllegalArgumentException("local_ee_clip_coverage encountered an unsupported tile key")
      }
      key -> ArrayMultibandTile(Array[Tile](LocalEeClipCoverageNumeric.applyTile(
        tile, geometry, grid, spatial, cols, rows)))
    }
    val layerMetadata = source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeClassifyReduceBridge.cubeMetadata(input, Seq("v")))
  }

  private def supportedEpsg(crs: CRS): Int = {
    val candidates = Vector(4326, 3857) ++ (32601 to 32660) ++ (32701 to 32760)
    candidates.find(code => try CRS.fromEpsgCode(code) == crs catch { case _: Exception => false })
      .getOrElse(throw new IllegalArgumentException(
        "local_ee_clip_coverage supports only EPSG:4326, EPSG:3857 and EPSG:32601..32660/32701..32760"))
  }

}

/** ServiceLoader entry point registered by the native adapter builder. */
final class LocalEeClipCoverageCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeClipCoverageCubeProcesses()
}
