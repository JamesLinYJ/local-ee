package local.ee.reduce

import geotrellis.layer.{KeyBounds, SpatialKey, SpaceTimeKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Float64-only adapters for the EE time and band reducer boundaries. */
final class LocalEeReduceCubeProcesses extends Serializable {
  private val Reducers = Set(
    "mean", "median", "min", "max", "sum", "count", "first", "last", "sd",
    "product", "stdDev", "variance", "sampleVariance")

  @OpenEOProcess(
    id = "local_ee_drop_single_time",
    description = "Drop a singleton temporal dimension without changing Float64 values or masks.",
    returns = "datacube"
  )
  def localEeDropSingleTime(data: Object): Object = {
    val input = LocalEeReduceSupport.validate(data, "local_ee_drop_single_time")
    require(input.kind == "temporal", "local_ee_drop_single_time requires SpaceTimeKey input")
    require(input.times.length == 1, "local_ee_drop_single_time requires exactly one observed instant")
    val instant = input.times.head
    val bounds = input.source.metadata.bounds.get
    require(bounds.minKey.asInstanceOf[SpaceTimeKey].instant == instant &&
      bounds.maxKey.asInstanceOf[SpaceTimeKey].instant == instant,
      "local_ee_drop_single_time metadata bounds must describe the one observed instant")
    val grid = input.grid
    val times = input.times.toSet
    val minSpatial = input.minSpatial
    val maxSpatial = input.maxSpatial
    val bands = input.names.size
    val cols = input.cols
    val rows = input.rows
    val output: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeReduceSupport.keyInGrid(key, "temporal", times, grid, minSpatial, maxSpatial),
        "local_ee_drop_single_time key lies outside declared grid bounds")
      val temporal = key.asInstanceOf[SpaceTimeKey]
      require(temporal.instant == instant, "local_ee_drop_single_time encountered an unexpected instant")
      (SpatialKey(temporal.col, temporal.row): Any) ->
        LocalEeReduceSupport.copyAsDouble(tile, bands, cols, rows)
    }
    val keyBounds: KeyBounds[Any] = KeyBounds[Any](
      SpatialKey(grid.minCol, grid.minRow), SpatialKey(grid.maxCol, grid.maxRow))
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType, bounds = keyBounds)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, input.names))
  }

  @OpenEOProcess(
    id = "local_ee_reduce_bands",
    description = "Reduce ordered input bands per pixel using Float64 values and NaN NoData.",
    returns = "datacube"
  )
  def localEeReduceBands(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("reducer"),
      "local_ee_reduce_bands requires only a reducer argument")
    val reducer = arguments.get("reducer") match {
      case value: String => value
      case _ => throw new IllegalArgumentException("reducer must be a string")
    }
    require(Reducers.contains(reducer), s"unsupported local_ee_reduce_bands reducer: $reducer")
    val input = LocalEeReduceSupport.validate(data, "local_ee_reduce_bands")
    val grid = input.grid
    val times = input.times.toSet
    val kind = input.kind
    val minSpatial = input.minSpatial
    val maxSpatial = input.maxSpatial
    val bands = input.names.size
    val cols = input.cols
    val rows = input.rows
    val output: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeReduceSupport.keyInGrid(key, kind, times, grid, minSpatial, maxSpatial),
        "local_ee_reduce_bands key lies outside declared grid bounds")
      key -> ArrayMultibandTile(Array[Tile](
        LocalEeReduceNumeric.reduceTile(tile, bands, cols, rows, reducer)))
    }
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, Seq("v")))
  }
}

/** ServiceLoader entry point; the task-level builder adds this provider explicitly. */
final class LocalEeReduceCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeReduceCubeProcesses()
}
