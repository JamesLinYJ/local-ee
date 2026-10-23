package local.ee.reduce

import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, GridBounds, MultibandTile, Tile}
import geotrellis.raster.buffer.BufferedTile
import geotrellis.spark._
import org.apache.spark.Partitioner
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded Float64 focal reductions with a fresh spatial halo for every iteration. */
final class LocalEeFocalCubeProcesses extends Serializable {
  @OpenEOProcess(
    id = "local_ee_focal",
    description = "Apply a bounded Float64 focal reduction to actual raster pixels.",
    returns = "datacube"
  )
  def localEeFocal(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_focal requires only a spec argument")
    val spec = arguments.get("spec") match {
      case value: String => LocalEeFocalSpec.parse(value)
      case _ => throw new IllegalArgumentException("focal spec must be a JSON string")
    }
    val input = LocalEeReduceSupport.validate(data, "local_ee_focal")
    require(input.names.length == 1, "local_ee_focal requires exactly one input band")
    val plan = preflight(input, spec)

    // Force complete value, key, shape and finiteness validation before any halo is built.
    val kind = input.kind
    val times = input.times.toSet
    val grid = input.grid
    val minimum = input.minSpatial
    val maximum = input.maxSpatial
    val cols = input.cols
    val rows = input.rows
    val checked: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeReduceSupport.keyInGrid(key, kind, times, grid, minimum, maximum),
        "local_ee_focal key lies outside declared grid bounds")
      key -> LocalEeReduceSupport.copyAsDouble(tile, 1, cols, rows)
    }
    require(checked.count() == plan.keyCount,
      "local_ee_focal source key count changed during tile validation")

    val bounds = GridBounds[Int](grid.minCol, grid.minRow, grid.maxCol, grid.maxRow)
    val output = runIterations(checked, input.kind, input.cols, input.rows, bounds, spec)
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, Seq("v")))
  }

  private def preflight(
    input: LocalEeReduceSupport.Input, spec: LocalEeFocalSpec.Value
  ): LocalEeFocalBudget.Plan = {
    val keys = input.source.keys.take((LocalEeFocalBudget.MaxSourceKeys + 1L).toInt)
    LocalEeFocalBudget.plan(keys.length.toLong, input.cols, input.rows, spec)
  }

  private def runIterations(
    initial: RDD[(Any, MultibandTile)], kind: String, cols: Int, rows: Int,
    bounds: GridBounds[Int], spec: LocalEeFocalSpec.Value
  ): RDD[(Any, MultibandTile)] = {
    var current = initial
    var iteration = 0
    while (iteration < spec.iterations) {
      current = kind match {
        case "spatial" => spatialPass(current, cols, rows, bounds, spec)
        case "temporal" => temporalPass(current, cols, rows, bounds, spec)
        case _ => throw new IllegalArgumentException("local_ee_focal input key type is unsupported")
      }
      iteration += 1
    }
    current
  }

  private def spatialPass(
    source: RDD[(Any, MultibandTile)], cols: Int, rows: Int,
    bounds: GridBounds[Int], spec: LocalEeFocalSpec.Value
  ): RDD[(Any, MultibandTile)] = {
    val typed = source.asInstanceOf[RDD[(SpatialKey, MultibandTile)]]
    val radius = math.max(spec.radiusX, spec.radiusY)
    if (radius == 0) typed.map { case (key, tile) =>
      key -> applyUnbuffered(tile, cols, rows, spec)
    }.asInstanceOf[RDD[(Any, MultibandTile)]]
    else {
      val buffered = typed.bufferTiles(radius, bounds, typed.partitioner)
      buffered.map { case (key, tile) =>
        key -> applyBuffered(tile, cols, rows, spec)
      }.asInstanceOf[RDD[(Any, MultibandTile)]]
    }
  }

  private def temporalPass(
    source: RDD[(Any, MultibandTile)], cols: Int, rows: Int,
    bounds: GridBounds[Int], spec: LocalEeFocalSpec.Value
  ): RDD[(Any, MultibandTile)] = {
    val typed = source.asInstanceOf[RDD[(SpaceTimeKey, MultibandTile)]]
    val radius = math.max(spec.radiusX, spec.radiusY)
    if (radius == 0) typed.map { case (key, tile) =>
      key -> applyUnbuffered(tile, cols, rows, spec)
    }.asInstanceOf[RDD[(Any, MultibandTile)]]
    else {
      val buffered = typed.bufferTiles(radius, bounds, typed.partitioner)
      buffered.map { case (key, tile) =>
        key -> applyBuffered(tile, cols, rows, spec)
      }.asInstanceOf[RDD[(Any, MultibandTile)]]
    }
  }

  private def applyUnbuffered(
    tile: MultibandTile, cols: Int, rows: Int, spec: LocalEeFocalSpec.Value
  ): MultibandTile = ArrayMultibandTile(Array[Tile](LocalEeFocalNumeric.applyBufferedTile(
    tile.band(0), GridBounds[Int](0, 0, cols - 1, rows - 1), cols, rows, spec)))

  private def applyBuffered(
    buffered: BufferedTile[MultibandTile], cols: Int, rows: Int, spec: LocalEeFocalSpec.Value
  ): MultibandTile =
    ArrayMultibandTile(Array[Tile](LocalEeFocalNumeric.applyBufferedTile(
      buffered.tile.band(0), buffered.targetArea, cols, rows, spec)))
}

/** ServiceLoader entry point for the atomic raster adapter JAR. */
final class LocalEeFocalCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeFocalCubeProcesses()
}
