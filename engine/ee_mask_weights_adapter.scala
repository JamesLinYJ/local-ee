package local.ee.reduce

import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded SPI for one-band validity and two-band fractional-mask projections. */
final class LocalEeMaskWeightsCubeProcesses extends Serializable {
  private val MaxMaskWeightWork = 67108864L
  private val MaxTileKeys = 100000L

  @OpenEOProcess(
    id = "local_ee_mask_weights",
    description = "Project NoData into an independent finite mask-weight band.",
    returns = "datacube"
  )
  def localEeMaskWeights(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_mask_weights requires only a spec argument")
    val wire = arguments.get("spec") match {
      case value: String => value
      case _ => throw new IllegalArgumentException("mask weights spec must be a JSON string")
    }
    // Reject malformed and noncanonical specifications before any cube or RDD access.
    val spec = LocalEeMaskWeightsSpec.parse(wire)
    val input = LocalEeClassifyReduceBridge.validate(data, "local_ee_mask_weights")
    require(input.names.size == spec.inputBands,
      s"local_ee_mask_weights ${spec.op} requires exactly ${spec.inputBands} ordered input bands")

    val tilePixels = Math.multiplyExact(input.cols.toLong, input.rows.toLong)
    require(tilePixels > 0L, "local_ee_mask_weights tile dimensions must be positive")
    val workPerPixel = Math.addExact(Math.multiplyExact(spec.inputBands.toLong, 2L), 1L)
    val perTileWork = Math.multiplyExact(tilePixels, workPerPixel)
    require(perTileWork <= MaxMaskWeightWork,
      s"local_ee_mask_weights exceeds the $MaxMaskWeightWork per-tile work budget")

    // This capped key action precharges the complete lazy pass before any pixel work is submitted.
    val keyCount = input.source.keys.take(MaxTileKeys.toInt + 1).length.toLong
    require(keyCount > 0L && keyCount <= MaxTileKeys,
      s"local_ee_mask_weights supports 1 to $MaxTileKeys tile keys")
    require(keyCount <= MaxMaskWeightWork / perTileWork,
      s"local_ee_mask_weights exceeds the $MaxMaskWeightWork aggregate work budget")

    // Spark captures only bounded immutable metadata and the parsed spec, never the cube/RDD wrapper.
    val kind = input.kind
    val times = input.times.toSet
    val minCol = input.minCol
    val minRow = input.minRow
    val maxCol = input.maxCol
    val maxRow = input.maxRow
    val minSpatial = input.minSpatial
    val maxSpatial = input.maxSpatial
    val bands = spec.inputBands
    val cols = input.cols
    val rows = input.rows
    val output: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeClassifyReduceBridge.keyInGrid(key, kind, times, minCol, minRow,
        maxCol, maxRow, minSpatial, maxSpatial),
        "local_ee_mask_weights key lies outside declared grid bounds")
      require(tile != null && tile.bandCount == bands && tile.cols == cols && tile.rows == rows,
        "local_ee_mask_weights tile band count or dimensions changed within the cube")
      key -> ArrayMultibandTile(Array[Tile](LocalEeMaskWeightsNumeric.applyTile(tile, spec)))
    }
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeClassifyReduceBridge.cubeMetadata(input, Seq("v")))
  }
}

/** ServiceLoader entry point registered by the atomic adapter builder. */
final class LocalEeMaskWeightsCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeMaskWeightsCubeProcesses()
}
