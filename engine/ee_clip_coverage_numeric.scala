package local.ee.reduce

import geotrellis.layer.SpatialKey
import geotrellis.raster.{DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import org.locationtech.jts.geom.{Envelope, Geometry, GeometryFactory}
import org.locationtech.jts.geom.prep.PreparedGeometryFactory

/** Actual-tile projected area coverage kernel; source science values are only validity witnesses. */
private[reduce] object LocalEeClipCoverageNumeric {
  private val GeometryFactory = new GeometryFactory()

  def applyTile(
    input: MultibandTile, geometry: Geometry, grid: LocalEeClipCoverageGeometry.Grid,
    key: SpatialKey, cols: Int, rows: Int
  ): Tile = {
    require(input != null && geometry != null && grid != null && key != null,
      "clip coverage tile inputs must be present")
    require(cols == grid.tileCols && rows == grid.tileRows,
      "clip coverage tile dimensions do not match the trusted source layout")
    require(input.bandCount == 1 && input.cols == cols && input.rows == rows && cols > 0 && rows > 0,
      "clip coverage tile must contain one band with the declared dimensions")
    val cells = Math.multiplyExact(cols.toLong, rows.toLong)
    require(cells <= 10000000L && cells <= Int.MaxValue,
      "clip coverage tile exceeds the 10000000-cell limit")
    val source = input.band(0)

    // Validate every source cell before any geometry-empty or envelope fast path.
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        val value = source.getDouble(col, row)
        require(value.isNaN || value.isFinite,
          "clip coverage source values must be finite or NoData, including outside the ROI")
        col += 1
      }
      row += 1
    }

    val firstCol = Math.multiplyExact(key.col.toLong, cols.toLong)
    val firstRow = Math.multiplyExact(key.row.toLong, rows.toLong)
    require(key.col >= 0 && key.row >= 0 && firstCol + cols <= grid.columns && firstRow + rows <= grid.rows,
      "clip coverage source key lies outside the actual layout grid")
    val output = new Array[Double](cells.toInt)
    val tileGeometry = if (geometry.isEmpty) geometry else {
      val translated = org.locationtech.jts.geom.util.AffineTransformation
        .translationInstance(-firstCol.toDouble, -firstRow.toDouble).transform(geometry)
      val tileBounds = GeometryFactory.toGeometry(new Envelope(0.0, cols.toDouble, 0.0, rows.toDouble))
      val clipped = translated.intersection(tileBounds)
      LocalEeClipCoverageGeometry.positiveAreaOrEmpty(
        translated, tileBounds, clipped, "clip coverage tile geometry")
    }
    val prepared = if (tileGeometry.isEmpty) None
      else Some(new PreparedGeometryFactory().create(tileGeometry))

    row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        val sourceValue = source.getDouble(col, row)
        output(row * cols + col) = if (sourceValue.isNaN || prepared.isEmpty) 0.0
        else coverageForCell(prepared.get, tileGeometry, col, row)
        col += 1
      }
      row += 1
    }
    DoubleArrayTile(output, cols, rows, DoubleConstantNoDataCellType)
  }

  private def coverageForCell(
    prepared: org.locationtech.jts.geom.prep.PreparedGeometry,
    geometry: Geometry, col: Int, row: Int
  ): Double = {
    val left = col.toDouble
    val bottom = row.toDouble
    val right = left + 1.0
    val top = bottom + 1.0
    val cell = GeometryFactory.toGeometry(new Envelope(left, right, bottom, top))
    if (prepared.covers(cell)) return 1.0
    if (!prepared.intersects(cell)) return 0.0

    // The tile geometry is already in pixel units and translated to this tile's origin.
    // The cell has unit area; keeping the overlay local to the tile avoids a full-geometry
    // clone for every fractional edge cell while avoiding map-coordinate cancellation.
    val overlap = LocalEeClipCoverageGeometry.positiveAreaOrEmpty(
      geometry, cell, geometry.intersection(cell), "clip coverage polygon-cell")
    val area = overlap.getArea
    require(area.isFinite && area >= 0.0,
      "clip coverage polygon-cell overlay produced an invalid area")
    require(!(area == 0.0 && !overlap.isEmpty && overlap.getDimension == 2),
      "clip coverage polygon-cell overlay has an ambiguous zero-area polygon result")
    if (area <= 1.0) area
    else if (area <= 1.0 + 2.0 * math.ulp(1.0)) 1.0
    else throw new IllegalArgumentException("clip coverage polygon-cell area exceeds one pixel")
  }
}
