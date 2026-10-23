package local.ee.math {

import geotrellis.raster.{ArrayMultibandTile, FloatConstantNoDataCellType, MultibandTile, Tile}
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}
import local.ee.reduce.LocalEeClassifyReduceBridge

/** GeoTrellis SPI adapter for bounded, actual Float32 pixel math. */
final class LocalEePixelMathCubeProcesses extends Serializable {
  private val MaxPixelMathWork = 67108864L

  @OpenEOProcess(
    id = "local_ee_pixel_math",
    description = "Apply one closed Float32 math operation to actual raster pixels.",
    returns = "datacube"
  )
  def localEePixelMath(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("operation"),
      "local_ee_pixel_math requires only an operation argument")
    val operation = arguments.get("operation") match {
      case value: String => value
      case _ => throw new IllegalArgumentException("pixel math operation must be a string")
    }
    val arity = LocalEePixelMathNumeric.arity(operation)
    val input = LocalEeClassifyReduceBridge.validate(data, "local_ee_pixel_math")
    val expectedNames = if (arity == 1) Seq("x") else Seq("x", "y")
    require(input.names == expectedNames,
      s"local_ee_pixel_math $operation requires input bands in order: ${expectedNames.mkString(", ")}")

    // The existing trusted bridge checks finite global grid/key bounds and aggregate/per-tile
    // decoded-cell caps. Check operation work before constructing the lazy result RDD.
    val tilePixels = Math.multiplyExact(input.cols.toLong, input.rows.toLong)
    require(tilePixels > 0L && tilePixels <= MaxPixelMathWork,
      s"local_ee_pixel_math exceeds the $MaxPixelMathWork operation-work budget")
    val keyCount = input.source.keys.take(100001).length.toLong
    require(keyCount > 0L && keyCount <= MaxPixelMathWork / tilePixels,
      s"local_ee_pixel_math exceeds the $MaxPixelMathWork operation-work budget")

    val sample = input.source.take(1).head._2
    require(sample.bandCount == arity && sample.cols == input.cols && sample.rows == input.rows,
      "local_ee_pixel_math sample tile band count or dimensions do not match metadata")
    var bandIndex = 0
    while (bandIndex < arity) {
      require(sample.band(bandIndex).cellType == FloatConstantNoDataCellType,
        "local_ee_pixel_math input bands must use Float32 with NaN NoData")
      bandIndex += 1
    }

    // Capture only immutable metadata values in this Spark closure, never Input, cube or RDD.
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
        "local_ee_pixel_math key lies outside declared grid bounds")
      require(tile != null && tile.bandCount == arity && tile.cols == cols && tile.rows == rows,
        "local_ee_pixel_math tile band count or dimensions changed within the cube")
      key -> ArrayMultibandTile(Array[Tile](LocalEePixelMathNumeric.applyTile(tile, operation)))
    }
    val layerMetadata = input.source.metadata.copy(cellType = FloatConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeClassifyReduceBridge.cubeMetadata(input, Seq("v")))
  }
}

/** ServiceLoader entry point for the atomic raster-math adapter JAR. */
final class LocalEePixelMathCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEePixelMathCubeProcesses()
}

}
