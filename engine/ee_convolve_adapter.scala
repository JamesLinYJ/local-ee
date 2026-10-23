package local.ee.reduce

import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, GridBounds, MultibandTile, Tile}
import geotrellis.raster.buffer.BufferedTile
import geotrellis.spark._
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded one-band Float64 Image.convolve adapter preserving source keys and metadata. */
final class LocalEeConvolveCubeProcesses extends Serializable {
  @OpenEOProcess(
    id = "local_ee_convolve",
    description = "Apply a bounded exact Float64 convolution kernel to actual raster pixels.",
    returns = "datacube"
  )
  def localEeConvolve(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_convolve requires only a spec argument")
    val spec = arguments.get("spec") match {
      case value: String => LocalEeConvolveSpec.parse(value)
      case _ => throw new IllegalArgumentException("convolve spec must be a JSON string")
    }
    val input = LocalEeReduceSupport.validate(data, "local_ee_convolve")
    require(input.names.length == 1, "local_ee_convolve requires exactly one input band")
    val plan = preflight(input, spec)

    // Keep only immutable metadata scalars and the parsed spec in the Spark closure.
    val kind = input.kind
    val times = input.times.toSet
    val grid = input.grid
    val minimum = input.minSpatial
    val maximum = input.maxSpatial
    val cols = input.cols
    val rows = input.rows
    val checked: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeReduceSupport.keyInGrid(key, kind, times, grid, minimum, maximum),
        "local_ee_convolve key lies outside declared grid bounds")
      key -> LocalEeReduceSupport.copyAsDouble(tile, 1, cols, rows)
    }
    require(checked.count() == plan.keyCount,
      "local_ee_convolve source key count changed during tile validation")

    val bounds = GridBounds[Int](grid.minCol, grid.minRow, grid.maxCol, grid.maxRow)
    val output: RDD[(Any, MultibandTile)] = kind match {
      case "spatial" => spatialPass(checked, cols, rows, bounds, spec, plan.radius)
      case "temporal" => temporalPass(checked, cols, rows, bounds, spec, plan.radius)
      case _ => throw new IllegalArgumentException("local_ee_convolve input key type is unsupported")
    }
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, Seq("v")))
  }

  private def preflight(
    input: LocalEeReduceSupport.Input, spec: LocalEeConvolveSpec.Value
  ): LocalEeConvolveBudget.Plan = {
    val keys = input.source.keys.take((LocalEeConvolveBudget.MaxSourceKeys + 1L).toInt)
    LocalEeConvolveBudget.plan(keys.length.toLong, input.cols, input.rows, spec)
  }

  private def spatialPass(
    source: RDD[(Any, MultibandTile)], cols: Int, rows: Int,
    bounds: GridBounds[Int], spec: LocalEeConvolveSpec.Value, radius: Int
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
    bounds: GridBounds[Int], spec: LocalEeConvolveSpec.Value, radius: Int
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
    tile: MultibandTile, cols: Int, rows: Int, spec: LocalEeConvolveSpec.Value
  ): MultibandTile = ArrayMultibandTile(Array[Tile](LocalEeConvolveNumeric.applyBufferedTile(
    tile.band(0), GridBounds[Int](0, 0, cols - 1, rows - 1), cols, rows, spec)))

  private def applyBuffered(
    buffered: BufferedTile[MultibandTile], cols: Int, rows: Int, spec: LocalEeConvolveSpec.Value
  ): MultibandTile = ArrayMultibandTile(Array[Tile](LocalEeConvolveNumeric.applyBufferedTile(
    buffered.tile.band(0), buffered.targetArea, cols, rows, spec)))
}

/** ServiceLoader entry point for the atomic native adapter JAR. */
final class LocalEeConvolveCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeConvolveCubeProcesses()
}
