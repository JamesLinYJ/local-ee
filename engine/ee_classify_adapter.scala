package local.ee.reduce {

import geotrellis.layer.SpatialKey
import geotrellis.raster.MultibandTile
import org.apache.spark.rdd.RDD
import geotrellis.spark.ContextRDD
import geotrellis.layer.TileLayerMetadata
import org.openeo.geotrelliscommon.{OpenEORasterCube, OpenEORasterCubeMetadata}

/** Public bridge for the reducer helpers, whose ownership is package-scoped. */
object LocalEeClassifyReduceBridge {
  final case class Input(
    cube: OpenEORasterCube[Any],
    source: ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]],
    names: Seq[String], kind: String, times: Set[Long],
    minCol: Int, minRow: Int, maxCol: Int, maxRow: Int,
    minSpatial: SpatialKey, maxSpatial: SpatialKey, cols: Int, rows: Int
  )

  def validate(data: Object, process: String): Input = {
    val value = LocalEeReduceSupport.validate(data, process)
    Input(value.cube, value.source, value.names, value.kind, value.times.toSet,
      value.grid.minCol, value.grid.minRow, value.grid.maxCol, value.grid.maxRow,
      value.minSpatial, value.maxSpatial, value.cols, value.rows)
  }

  def keyInGrid(key: Any, kind: String, times: Set[Long], minCol: Int, minRow: Int,
                maxCol: Int, maxRow: Int, minSpatial: SpatialKey, maxSpatial: SpatialKey): Boolean =
    LocalEeReduceSupport.keyInGrid(key, kind, times,
      LocalEeReduceSupport.Grid(minCol, minRow, maxCol, maxRow), minSpatial, maxSpatial)

  def cubeMetadata(input: Input, bands: Seq[String]): OpenEORasterCubeMetadata =
    LocalEeReduceSupport.cubeMetadata(input.cube, bands)
}
}

package local.ee.classify {

import geotrellis.raster.{ArrayMultibandTile, IntConstantNoDataCellType, MultibandTile, Tile}
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}
import local.ee.reduce.LocalEeClassifyReduceBridge

/** GeoTrellis boundary for exact static minimum-distance classification. */
final class LocalEeClassifyCubeProcesses extends Serializable {
  private val MaxClassificationWork = 67108864L

  @OpenEOProcess(
    id = "local_ee_minimum_distance",
    description = "Classify complete finite pixels against exact static class centers.",
    returns = "datacube"
  )
  def localEeMinimumDistance(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("model"),
      "local_ee_minimum_distance requires only a model argument")
    val model = LocalEeClassifyModel.fromJavaMap(arguments.get("model") match {
      case value: java.util.Map[_, _] => value
      case _ => throw new IllegalArgumentException("model must be an object")
    })
    val input = LocalEeClassifyReduceBridge.validate(data, "local_ee_minimum_distance")
    require(input.names == model.schema, "input cube bands must match model schema names and order")

    val classDimensions = Math.multiplyExact(model.labels.length.toLong, model.schema.length.toLong)
    val tileWork = Math.multiplyExact(Math.multiplyExact(input.cols.toLong, input.rows.toLong), classDimensions)
    val keyCount = input.source.keys.take(100001).length.toLong
    require(tileWork <= MaxClassificationWork && keyCount <= MaxClassificationWork / tileWork,
      s"local_ee_minimum_distance exceeds the $MaxClassificationWork classification-work budget")

    val bands = input.names.length
    val cols = input.cols
    val rows = input.rows
    val kind = input.kind
    val times = input.times
    val minCol = input.minCol
    val minRow = input.minRow
    val maxCol = input.maxCol
    val maxRow = input.maxRow
    val minSpatial = input.minSpatial
    val maxSpatial = input.maxSpatial
    val output: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeClassifyReduceBridge.keyInGrid(key, kind, times, minCol, minRow,
        maxCol, maxRow, minSpatial, maxSpatial),
        "local_ee_minimum_distance key lies outside declared grid bounds")
      key -> ArrayMultibandTile(Array[Tile](LocalEeClassifyNumeric.classifyTile(tile, bands, cols, rows, model)))
    }
    val layerMetadata = input.source.metadata.copy(cellType = IntConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeClassifyReduceBridge.cubeMetadata(input, Seq("v")))
  }
}

}

package local.ee.classify {

import org.openeo.geotrelliscommon.CubeProcessProvider

/** ServiceLoader entry point; the task-level builder adds this provider explicitly. */
final class LocalEeClassifyCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeClassifyCubeProcesses()
}

}
