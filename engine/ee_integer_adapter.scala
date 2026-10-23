package local.ee.integer

import geotrellis.raster.{DoubleConstantNoDataCellType, FloatConstantNoDataCellType, MultibandTile}
import geotrellis.spark.ContextRDD
import geotrellis.layer.TileLayerMetadata
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEORasterCubeMetadata, OpenEOProcess}

/** Local, versioned GeoTrellis SPI adapter for EE operations with exact semantics. */
final class LocalEeIntegerCubeProcesses {
  /**
   * Convert every present input cell to a physical Float64 cell and preserve
   * the source mask as GeoTrellis NaN NoData. Band names and spatial/temporal
   * layer metadata are carried forward unchanged except for cell type.
   */
  @OpenEOProcess(
    id = "local_ee_to_double",
    description = "Convert all raster bands to Float64 while preserving NoData and cube metadata.",
    returns = "datacube"
  )
  def localEeToDouble(data: Object): Object = {
    val cube = data.asInstanceOf[OpenEORasterCube[Any]]
    val targetType = DoubleConstantNoDataCellType
    val source = cube.asInstanceOf[ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]]]
    val converted: RDD[(Any, MultibandTile)] = source.mapValues(
      (tile: MultibandTile) => LocalEeCellConversion.toDouble(tile)
    )
    val metadata = source.metadata.copy(cellType = targetType)
    new OpenEORasterCube[Any](converted, metadata, cube.openEOMetadata)
  }

  /** Restore the native Float32 cell type while preserving an existing mask. */
  @OpenEOProcess(
    id = "local_ee_to_float",
    description = "Convert all raster bands to Float32 while preserving NoData and cube metadata.",
    returns = "datacube"
  )
  def localEeToFloat(data: Object): Object = {
    val cube = data.asInstanceOf[OpenEORasterCube[Any]]
    val targetType = FloatConstantNoDataCellType
    val source = cube.asInstanceOf[ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]]]
    val converted: RDD[(Any, MultibandTile)] = source.mapValues(
      (tile: MultibandTile) => LocalEeCellConversion.toFloat(tile)
    )
    val metadata = source.metadata.copy(cellType = targetType)
    new OpenEORasterCube[Any](converted, metadata, cube.openEOMetadata)
  }
}

/** ServiceLoader entry point recognized by the pinned GeoTrellis extensions JAR. */
final class LocalEeIntegerCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeIntegerCubeProcesses()
}
