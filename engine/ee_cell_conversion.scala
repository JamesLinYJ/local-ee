package local.ee.integer

import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType,
  FloatArrayTile, FloatConstantNoDataCellType, MultibandTile, Tile}

/** Preserve each source cell type's actual mask before changing its physical type.
  * GeoTrellis convert can route Int.MinValue through an intermediate integer NoData
  * convention even when the source has a different user-defined sentinel. Read the
  * source's own getDouble accessor instead, so only its real mask becomes NaN.
  */
object LocalEeCellConversion {
  def toDouble(tile: MultibandTile): MultibandTile = convert(tile, useFloat = false)
  def toFloat(tile: MultibandTile): MultibandTile = convert(tile, useFloat = true)

  private def convert(tile: MultibandTile, useFloat: Boolean): MultibandTile = {
    require(tile != null && tile.cols > 0 && tile.rows > 0 && tile.bandCount > 0,
      "cell conversion requires nonempty raster bands")
    val cells = Math.multiplyExact(tile.cols, tile.rows)
    val output = Array.tabulate[Tile](tile.bandCount) { index =>
      val source = tile.band(index)
      if (useFloat) {
        val values = new Array[Float](cells)
        var row = 0
        while (row < tile.rows) {
          var col = 0
          while (col < tile.cols) {
            values(row * tile.cols + col) = source.getDouble(col, row).toFloat
            col += 1
          }
          row += 1
        }
        FloatArrayTile(values, tile.cols, tile.rows, FloatConstantNoDataCellType)
      } else {
        val values = new Array[Double](cells)
        var row = 0
        while (row < tile.rows) {
          var col = 0
          while (col < tile.cols) {
            values(row * tile.cols + col) = source.getDouble(col, row)
            col += 1
          }
          row += 1
        }
        DoubleArrayTile(values, tile.cols, tile.rows, DoubleConstantNoDataCellType)
      }
    }
    ArrayMultibandTile(output)
  }
}
