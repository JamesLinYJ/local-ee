package local.ee.remap {

import geotrellis.layer.{SpatialKey, SpaceTimeKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}
import local.ee.reduce.LocalEeClassifyReduceBridge

/** GeoTrellis adapter for the closed, bounded local_ee_remap operation. */
final class LocalEeRemapCubeProcesses extends Serializable {
  private val MaxRemapWork = 67108864L

  @OpenEOProcess(
    id = "local_ee_remap",
    description = "Remap one finite raster band using exact binary64 input comparisons.",
    returns = "datacube"
  )
  def localEeRemap(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_remap requires only a spec argument")
    val text = arguments.get("spec") match {
      case value: String => value
      case _ => throw new IllegalArgumentException("local_ee_remap spec must be a JSON string")
    }
    // Bound and independently parse the process string before validating or traversing cube data.
    val spec = LocalEeRemapNumeric.parseSpec(text)
    val input = LocalEeClassifyReduceBridge.validate(data, "local_ee_remap")
    require(input.names.length == 1, "local_ee_remap requires exactly one input band")

    val tilePixels = Math.multiplyExact(input.cols.toLong, input.rows.toLong)
    val tileWork = Math.multiplyExact(tilePixels, math.max(1, spec.from.length).toLong)
    val keyCount = input.source.keys.take(100001).length.toLong
    require(tileWork <= MaxRemapWork && keyCount <= MaxRemapWork / tileWork,
      s"local_ee_remap exceeds the $MaxRemapWork remap-work budget")

    val kind = input.kind
    val times = input.times
    val minCol = input.minCol
    val minRow = input.minRow
    val maxCol = input.maxCol
    val maxRow = input.maxRow
    val minSpatial = input.minSpatial
    val maxSpatial = input.maxSpatial
    val cols = input.cols
    val rows = input.rows
    val output: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeClassifyReduceBridge.keyInGrid(key, kind, times, minCol, minRow,
        maxCol, maxRow, minSpatial, maxSpatial),
        "local_ee_remap key lies outside declared grid bounds")
      key match {
        case _: SpatialKey => ()
        case _: SpaceTimeKey => ()
        case _ => throw new IllegalArgumentException("local_ee_remap encountered an unsupported key type")
      }
      require(tile.bandCount == 1 && tile.cols == cols && tile.rows == rows,
        "local_ee_remap tile band count or dimensions changed within the cube")
      key -> ArrayMultibandTile(Array[Tile](LocalEeRemapNumeric.remapTile(tile, spec)))
    }
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeClassifyReduceBridge.cubeMetadata(input, Seq("v")))
  }
}

/** ServiceLoader entry point for the atomic integer/raster adapter JAR. */
final class LocalEeRemapCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeRemapCubeProcesses()
}

}
