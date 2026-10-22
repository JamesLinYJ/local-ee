package local.ee.smile

import geotrellis.raster.{DoubleConstantNoDataCellType, IntArrayTile, IntConstantNoDataCellType, MultibandTile, Tile}

/** Actual Smile prediction over GeoTrellis values, preserving source-cell precision and masks. */
object LocalEeSmileRfNumeric {
  private val NoDataInt = Int.MinValue

  def predictValue(values: Array[Double], model: LocalEeSmileRfModel): Int = {
    require(model != null && model.forest != null, "Random forest model must come from the trusted trainer")
    require(values != null && values.length == model.schema.length,
      "Random forest prediction dimension must match the ordered model schema")
    require(values.forall(_.isFinite), "Valid random forest prediction pixels must be finite")
    val label = model.forest.predict(values)
    require(label >= 0 && label < model.classCount,
      "Smile RandomForest returned a class outside its trained range")
    label
  }

  /** Any selected-band NoData masks a cell; valid infinities fail instead of being hidden. */
  def classifyTile(tile: MultibandTile, bands: Int, cols: Int, rows: Int,
                   model: LocalEeSmileRfModel): Tile = {
    require(tile != null && model != null && tile.bandCount == bands &&
      bands == model.schema.length && tile.cols == cols && tile.rows == rows,
      "Random forest tile bands or dimensions changed within the cube")
    val source = Array.tabulate(bands)(index => tile.band(index).convert(DoubleConstantNoDataCellType))
    val values = new Array[Double](bands)
    val output = Array.fill(Math.multiplyExact(cols, rows))(NoDataInt)
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        var hasNoData = false
        var band = 0
        while (band < bands) {
          val value = source(band).getDouble(col, row)
          require(value.isNaN || value.isFinite,
            "Valid random forest input pixels must be finite or NoData")
          if (value.isNaN) hasNoData = true
          values(band) = value
          band += 1
        }
        if (!hasNoData) output(row * cols + col) = predictValue(values, model)
        col += 1
      }
      row += 1
    }
    IntArrayTile(output, cols, rows, IntConstantNoDataCellType)
  }
}
