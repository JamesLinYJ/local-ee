package local.ee.reduce

import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, GridBounds, MultibandTile, Tile}
import geotrellis.raster.buffer.BufferedTile
import geotrellis.spark._
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded single-pass Float64 distance transforms over actual source tiles. */
final class LocalEeDistanceCubeProcesses extends Serializable {
  @OpenEOProcess(
    id = "local_ee_distance",
    description = "Compute bounded distance to the nearest valid nonzero raster pixel.",
    returns = "datacube"
  )
  def localEeDistance(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_distance requires only a spec argument")
    val spec = arguments.get("spec") match {
      case value: String => LocalEeDistanceSpec.parse(value)
      case _ => throw new IllegalArgumentException("distance spec must be a JSON string")
    }
    // Reject known oversized layouts before shared validation evaluates any
    // upstream RDD to enumerate keys or inspect its first tile.
    data match {
      case cube: OpenEORasterCube[_] =>
        require(cube.openEOMetadata.bands != null && cube.openEOMetadata.bands.length == 1,
          "local_ee_distance requires exactly one input band")
        val layout = cube.metadata.layout.tileLayout
        LocalEeDistanceBudget.plan(1L, layout.tileCols, layout.tileRows, spec)
      case _ => throw new IllegalArgumentException("local_ee_distance requires a raster cube")
    }
    val input = LocalEeReduceSupport.validate(data, "local_ee_distance")
    require(input.names.length == 1, "local_ee_distance requires exactly one input band")
    val plan = preflight(input, spec)

    // Validate and copy every source tile before halo construction; closures retain no cube or RDD.
    val kind = input.kind
    val times = input.times.toSet
    val grid = input.grid
    val minimum = input.minSpatial
    val maximum = input.maxSpatial
    val cols = input.cols
    val rows = input.rows
    val checked: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeReduceSupport.keyInGrid(key, kind, times, grid, minimum, maximum),
        "local_ee_distance key lies outside declared grid bounds")
      key -> LocalEeReduceSupport.copyAsDouble(tile, 1, cols, rows)
    }
    require(checked.count() == plan.keyCount,
      "local_ee_distance source key count changed during tile validation")

    val bounds = GridBounds[Int](grid.minCol, grid.minRow, grid.maxCol, grid.maxRow)
    val output = runOnce(checked, kind, cols, rows, bounds, spec)
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, Seq("v")))
  }

  private def preflight(
    input: LocalEeReduceSupport.Input, spec: LocalEeDistanceSpec.Value
  ): LocalEeDistanceBudget.Plan = {
    val keys = input.source.keys.take((LocalEeDistanceBudget.MaxSourceKeys + 1L).toInt)
    LocalEeDistanceBudget.plan(keys.length.toLong, input.cols, input.rows, spec)
  }

  private def runOnce(
    source: RDD[(Any, MultibandTile)], kind: String, cols: Int, rows: Int,
    bounds: GridBounds[Int], spec: LocalEeDistanceSpec.Value
  ): RDD[(Any, MultibandTile)] = kind match {
    case "spatial" =>
      val typed = source.asInstanceOf[RDD[(SpatialKey, MultibandTile)]]
      if (spec.halo == 0) typed.map { case (key, tile) =>
        key -> applyUnbuffered(tile, cols, rows, spec)
      }.asInstanceOf[RDD[(Any, MultibandTile)]]
      else typed.bufferTiles(spec.halo, bounds, typed.partitioner).map { case (key, tile) =>
        key -> applyBuffered(tile, cols, rows, spec)
      }.asInstanceOf[RDD[(Any, MultibandTile)]]
    case "temporal" =>
      val typed = source.asInstanceOf[RDD[(SpaceTimeKey, MultibandTile)]]
      if (spec.halo == 0) typed.map { case (key, tile) =>
        key -> applyUnbuffered(tile, cols, rows, spec)
      }.asInstanceOf[RDD[(Any, MultibandTile)]]
      else typed.bufferTiles(spec.halo, bounds, typed.partitioner).map { case (key, tile) =>
        key -> applyBuffered(tile, cols, rows, spec)
      }.asInstanceOf[RDD[(Any, MultibandTile)]]
    case _ => throw new IllegalArgumentException("local_ee_distance input key type is unsupported")
  }

  private def applyUnbuffered(
    tile: MultibandTile, cols: Int, rows: Int, spec: LocalEeDistanceSpec.Value
  ): MultibandTile = ArrayMultibandTile(Array[Tile](LocalEeDistanceNumeric.applyBufferedTile(
    tile.band(0), GridBounds[Int](0, 0, cols - 1, rows - 1), cols, rows, spec)))

  private def applyBuffered(
    buffered: BufferedTile[MultibandTile], cols: Int, rows: Int, spec: LocalEeDistanceSpec.Value
  ): MultibandTile = ArrayMultibandTile(Array[Tile](LocalEeDistanceNumeric.applyBufferedTile(
    buffered.tile.band(0), buffered.targetArea, cols, rows, spec)))
}

/** ServiceLoader entry point for the atomic distance adapter JAR. */
final class LocalEeDistanceCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeDistanceCubeProcesses()
}
