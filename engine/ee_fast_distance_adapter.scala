package local.ee.reduce

import geotrellis.raster.{ArrayMultibandTile, IntConstantNoDataCellType, MultibandTile, Tile}
import geotrellis.spark._
import org.apache.spark.HashPartitioner
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded multi-hop SPI adapter for the local fast distance transform. */
final class LocalEeFastDistanceCubeProcesses extends Serializable {
  @OpenEOProcess(
    id = "local_ee_fast_distance_transform",
    description = "Compute a capped pixel distance transform with a bounded multi-hop halo.",
    returns = "datacube"
  )
  def localEeFastDistanceTransform(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_fast_distance_transform requires only a spec argument")
    val spec = arguments.get("spec") match {
      case value: String => LocalEeFastDistanceSpec.parse(value)
      case _ => throw new IllegalArgumentException("fast distance spec must be a JSON string")
    }

    // Reject impossible metadata-only layouts before the shared validator's
    // bounded key census and sample-tile action.
    val cube = data match {
      case value: OpenEORasterCube[_] => value.asInstanceOf[OpenEORasterCube[Any]]
      case _ => throw new IllegalArgumentException("local_ee_fast_distance_transform requires a raster cube")
    }
    require(cube.openEOMetadata.bands != null && cube.openEOMetadata.bands.length == 1,
      "local_ee_fast_distance_transform requires exactly one input band")
    val tileLayout = cube.metadata.layout.tileLayout
    LocalEeFastDistanceBudget.plan(1L, tileLayout.tileCols, tileLayout.tileRows, spec)

    // The shared bounded validator checks metadata, duplicate keys, key bounds,
    // observed times, a sample tile and source-cell limits. Its bounded key
    // census is upstream IO; the exact count plan below precedes the shuffle.
    val input = LocalEeReduceSupport.validate(data, "local_ee_fast_distance_transform")
    require(input.names.length == 1, "local_ee_fast_distance_transform requires exactly one input band")
    val keyValues = input.source.keys.take((LocalEeFastDistanceBudget.MaxSourceKeys + 1L).toInt)
    val plan = LocalEeFastDistanceBudget.plan(keyValues.length.toLong, input.cols, input.rows, spec)
    require(keyValues.distinct.length == keyValues.length,
      "local_ee_fast_distance_transform input contains duplicate tile keys")

    val kind = input.kind
    val times = input.times.toSet
    val grid = input.grid
    val minimum = input.minSpatial
    val maximum = input.maxSpatial
    keyValues.foreach { key =>
      require(LocalEeReduceSupport.keyInGrid(key, kind, times, grid, minimum, maximum),
        "local_ee_fast_distance_transform key lies outside declared grid bounds")
    }
    val centers = keyValues.iterator.map(LocalEeFastDistanceHalo.fromAny(_, kind)).toSet
    require(centers.size == keyValues.length,
      "local_ee_fast_distance_transform input contains duplicate normalized keys")
    val bounds = LocalEeFastDistanceHalo.SpatialBounds(
      math.max(grid.minCol, minimum.col), math.max(grid.minRow, minimum.row),
      math.min(grid.maxCol, maximum.col), math.min(grid.maxRow, maximum.row))
    val cols = input.cols
    val rows = input.rows

    // Capture only bounded keys and immutable scalar metadata in Spark closures.
    // Tile values are validated lazily before each source-target and fragment allocation.
    val source = input.source
    val fragments: RDD[(LocalEeFastDistanceHalo.Key, LocalEeFastDistanceHalo.Piece)] =
      source.flatMap { case (key, tile) =>
        require(LocalEeReduceSupport.keyInGrid(key, kind, times, grid, minimum, maximum),
          "local_ee_fast_distance_transform key changed outside declared bounds")
        require(tile != null && tile.bandCount == 1,
          "local_ee_fast_distance_transform tiles must contain one band")
        val sourceKey = LocalEeFastDistanceHalo.fromAny(key, kind)
        require(centers.contains(sourceKey),
          "local_ee_fast_distance_transform source key changed after bounded validation")
        val targets = LocalEeFastDistanceHalo.targetsFromTile(tile.band(0), cols, rows)
        LocalEeFastDistanceHalo.emitFragments(sourceKey, targets, centers, cols, rows,
          bounds, spec, plan)
      }

    val partitionCount = math.max(1, source.partitions.length)
    val output: RDD[(Any, MultibandTile)] = fragments
      .groupByKey(new HashPartitioner(partitionCount))
      .flatMap { case (key, pieces) =>
        LocalEeFastDistanceHalo.assemble(pieces, cols, rows, spec, plan).iterator.map { tile =>
          LocalEeFastDistanceHalo.toAny(key) -> ArrayMultibandTile(Array[Tile](tile))
        }
      }

    val layerMetadata = input.source.metadata.copy(cellType = IntConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, Seq("v")))
  }
}

/** ServiceLoader entry point for the fast distance adapter JAR. */
final class LocalEeFastDistanceCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeFastDistanceCubeProcesses()
}
