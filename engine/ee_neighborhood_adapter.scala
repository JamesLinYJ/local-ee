package local.ee.reduce

import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, GridBounds, MultibandTile, Tile}
import geotrellis.raster.buffer.BufferedTile
import geotrellis.spark._
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded one-band local_ee_neighborhood process over observed raster keys only. */
final class LocalEeNeighborhoodCubeProcesses extends Serializable {
  @OpenEOProcess(
    id = "local_ee_neighborhood",
    description = "Apply bounded exact weighted statistics to actual Float64 neighborhood pixels.",
    returns = "datacube"
  )
  def localEeNeighborhood(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_neighborhood requires only a spec argument")
    val spec = arguments.get("spec") match {
      case value: String => LocalEeNeighborhoodSpec.parse(value)
      case _ => throw new IllegalArgumentException("neighborhood spec must be a JSON string")
    }
    val input = LocalEeReduceSupport.validate(data, "local_ee_neighborhood")
    require(input.names.length == 1, "local_ee_neighborhood requires exactly one input band")
    val keys = input.source.keys.take((LocalEeNeighborhoodBudget.MaxSourceKeys + 1L).toInt)
    val plan = LocalEeNeighborhoodBudget.plan(keys.length.toLong, input.cols, input.rows, spec)

    // Validate full keys and tile data before any spatial or temporal halo is built.
    val kind = input.kind
    val times = input.times.toSet
    val grid = input.grid
    val minimum = input.minSpatial
    val maximum = input.maxSpatial
    val cols = input.cols
    val rows = input.rows
    val checked: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeReduceSupport.keyInGrid(key, kind, times, grid, minimum, maximum),
        "local_ee_neighborhood key lies outside declared grid bounds")
      key -> LocalEeReduceSupport.copyAsDouble(tile, 1, cols, rows)
    }
    require(checked.count() == plan.keyCount,
      "local_ee_neighborhood source key count changed during tile validation")

    val bounds = GridBounds[Int](grid.minCol, grid.minRow, grid.maxCol, grid.maxRow)
    val output: RDD[(Any, MultibandTile)] = kind match {
      case "spatial" => spatialPass(checked, cols, rows, bounds, spec, plan.radius)
      case "temporal" => temporalPass(checked, cols, rows, bounds, spec, plan.radius)
      case _ => throw new IllegalArgumentException("local_ee_neighborhood input key type is unsupported")
    }
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, Seq("v")))
  }

  private def spatialPass(
    source: RDD[(Any, MultibandTile)], cols: Int, rows: Int,
    bounds: GridBounds[Int], spec: LocalEeNeighborhoodSpec.Value, radius: Int
  ): RDD[(Any, MultibandTile)] = {
    val typed = source.asInstanceOf[RDD[(SpatialKey, MultibandTile)]]
    if (radius == 0) typed.map { case (key, tile) =>
      key -> applyUnbuffered(tile, cols, rows, spec)
    }.asInstanceOf[RDD[(Any, MultibandTile)]]
    else typed.bufferTiles(radius, bounds, typed.partitioner).map { case (key, tile) =>
      key -> applyBuffered(tile, cols, rows, spec)
    }.asInstanceOf[RDD[(Any, MultibandTile)]]
  }

  private def temporalPass(
    source: RDD[(Any, MultibandTile)], cols: Int, rows: Int,
    bounds: GridBounds[Int], spec: LocalEeNeighborhoodSpec.Value, radius: Int
  ): RDD[(Any, MultibandTile)] = {
    val typed = source.asInstanceOf[RDD[(SpaceTimeKey, MultibandTile)]]
    if (radius == 0) typed.map { case (key, tile) =>
      key -> applyUnbuffered(tile, cols, rows, spec)
    }.asInstanceOf[RDD[(Any, MultibandTile)]]
    else typed.bufferTiles(radius, bounds, typed.partitioner).map { case (key, tile) =>
      key -> applyBuffered(tile, cols, rows, spec)
    }.asInstanceOf[RDD[(Any, MultibandTile)]]
  }

  private def applyUnbuffered(
    tile: MultibandTile, cols: Int, rows: Int, spec: LocalEeNeighborhoodSpec.Value
  ): MultibandTile = ArrayMultibandTile(Array[Tile](LocalEeNeighborhoodNumeric.applyBufferedTile(
    tile.band(0), GridBounds[Int](0, 0, cols - 1, rows - 1), cols, rows, spec)))

  private def applyBuffered(
    buffered: BufferedTile[MultibandTile], cols: Int, rows: Int, spec: LocalEeNeighborhoodSpec.Value
  ): MultibandTile = ArrayMultibandTile(Array[Tile](LocalEeNeighborhoodNumeric.applyBufferedTile(
    buffered.tile.band(0), buffered.targetArea, cols, rows, spec)))
}

/** ServiceLoader entry point for the adapter JAR. */
final class LocalEeNeighborhoodCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeNeighborhoodCubeProcesses()
}
