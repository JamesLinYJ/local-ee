package local.ee.smile

import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{ArrayMultibandTile, IntConstantNoDataCellType, MultibandTile, Tile}
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

import local.ee.reduce.LocalEeClassifyReduceBridge

/** Thin GeoTrellis process boundary; training remains in the trusted model factory. */
final class LocalEeSmileRfCubeProcesses extends Serializable {
  private val MaxPredictionNodeVisits = 1000000000L

  @OpenEOProcess(
    id = "local_ee_smile_rf",
    description = "Classify finite raster pixels with an internally trained Smile 1.5.3 forest.",
    returns = "datacube"
  )
  def localEeSmileRf(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("model"),
      "local_ee_smile_rf requires only a model argument")
    val model = arguments.get("model") match {
      case value: LocalEeSmileRfModel => value
      case _ => throw new IllegalArgumentException("model must be a trusted Smile random-forest instance")
    }
    require(model.actualTreeCount > 0 && model.maxDepthSum > 0L,
      "Random forest model has invalid trusted tree bounds")

    val input = LocalEeClassifyReduceBridge.validate(data, "local_ee_smile_rf")
    require(input.names.toVector == model.schema,
      "input cube bands must match the random-forest schema names and order")
    val keyCount = input.source.keys.take(100001).length.toLong
    val pixels = Math.multiplyExact(Math.multiplyExact(input.cols.toLong, input.rows.toLong), keyCount)
    val visits = Math.multiplyExact(pixels, model.maxDepthSum)
    require(visits <= MaxPredictionNodeVisits,
      s"local_ee_smile_rf exceeds the $MaxPredictionNodeVisits prediction-node-visit budget")

    val bands = model.schema.length
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
        "local_ee_smile_rf key lies outside declared grid bounds")
      key match {
        case _: SpatialKey => ()
        case _: SpaceTimeKey => ()
        case _ => throw new IllegalArgumentException("local_ee_smile_rf encountered an unsupported key type")
      }
      require(tile.bandCount == bands && tile.cols == cols && tile.rows == rows,
        "local_ee_smile_rf tile band count or dimensions changed within the cube")
      key -> ArrayMultibandTile(Array[Tile](
        LocalEeSmileRfNumeric.classifyTile(tile, bands, cols, rows, model)))
    }
    val layerMetadata = input.source.metadata.copy(cellType = IntConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeClassifyReduceBridge.cubeMetadata(input, Seq("v")))
  }
}

/** ServiceLoader entry point for the separate Smile RF adapter JAR. */
final class LocalEeSmileRfCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeSmileRfCubeProcesses()
}
