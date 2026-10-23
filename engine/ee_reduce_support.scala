package local.ee.reduce

import geotrellis.layer.{SpatialKey, SpaceTimeKey, TileLayerMetadata}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import geotrellis.spark.ContextRDD
import org.openeo.geotrelliscommon.{OpenEORasterCube, OpenEORasterCubeMetadata}

/** Shared validation and numeric kernels kept separate from the SPI surface. */
private[reduce] object LocalEeReduceSupport {
  private val MaxTileKeys = 100000
  private val MaxTimeKeys = 10000
  private val MaxBands = 1000
  private val MaxDecodedCells = 100000000L
  private val MaxTileDecodedCells = 10000000L

  final case class Grid(minCol: Int, minRow: Int, maxCol: Int, maxRow: Int) extends Serializable
  final case class Input(
    cube: OpenEORasterCube[Any],
    source: ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]],
    names: Seq[String], kind: String, times: Array[Long], grid: Grid,
    minSpatial: SpatialKey, maxSpatial: SpatialKey, cols: Int, rows: Int
  )

  def validate(data: Object, process: String): Input = {
    val cube = data match {
      case value: OpenEORasterCube[_] => value.asInstanceOf[OpenEORasterCube[Any]]
      case _ => throw new IllegalArgumentException(s"$process data must be an OpenEORasterCube")
    }
    val source = cube.asInstanceOf[ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]]]
    val metadata = source.metadata
    val bounds = metadata.bounds.getOrElse(throw new IllegalArgumentException(s"$process has EmptyBounds"))
    val extent = metadata.extent
    require(!extent.isEmpty && Seq(extent.xmin, extent.ymin, extent.xmax, extent.ymax).forall(_.isFinite),
      s"$process extent must be finite and non-empty")
    require(extent.intersects(metadata.layout.extent) && metadata.layout.extent.contains(extent),
      s"$process extent must lie inside its declared layout")
    val tileLayout = metadata.layout.tileLayout
    val cols = tileLayout.tileCols
    val rows = tileLayout.tileRows
    require(cols > 0 && rows > 0, s"$process tile dimensions must be positive")
    val grid = finiteGrid(metadata)
    val (kind, minSpatial, maxSpatial) = (bounds.minKey, bounds.maxKey) match {
      case (minimum: SpatialKey, maximum: SpatialKey) => ("spatial", minimum, maximum)
      case (minimum: SpaceTimeKey, maximum: SpaceTimeKey) =>
        require(minimum.instant <= maximum.instant, s"$process time bounds are reversed")
        ("temporal", minimum.spatialKey, maximum.spatialKey)
      case _ => throw new IllegalArgumentException(s"$process bounds must use SpatialKey or SpaceTimeKey consistently")
    }
    require(minSpatial.col <= maxSpatial.col && minSpatial.row <= maxSpatial.row &&
      inside(minSpatial, grid) && inside(maxSpatial, grid), s"$process bounds lie outside its finite grid")
    val names = Option(cube.openEOMetadata.bands).map(_.toSeq).getOrElse(Seq.empty)
    require(names.nonEmpty && names.size <= MaxBands && names.forall(name => name != null && name.nonEmpty),
      s"$process requires 1 to $MaxBands named bands")
    require(names.distinct.size == names.size, s"$process band names must be unique")
    val keys = source.keys.take(MaxTileKeys + 1)
    require(keys.nonEmpty && keys.length <= MaxTileKeys, s"$process supports 1 to $MaxTileKeys tile keys")
    require(keys.distinct.length == keys.length, s"$process input contains duplicate tile keys")
    val times = if (kind == "temporal") {
      val minimum = bounds.minKey.asInstanceOf[SpaceTimeKey].instant
      val maximum = bounds.maxKey.asInstanceOf[SpaceTimeKey].instant
      val observed = keys.map {
        case key: SpaceTimeKey =>
          require(inside(key, grid) && inBounds(key.spatialKey, minSpatial, maxSpatial),
            s"$process key lies outside metadata grid bounds")
          require(key.instant >= minimum && key.instant <= maximum,
            s"$process time key lies outside metadata bounds")
          key.instant
        case _ => throw new IllegalArgumentException(s"$process key type does not match metadata bounds")
      }.distinct.sorted
      require(observed.length <= MaxTimeKeys, s"$process supports at most $MaxTimeKeys observed instants")
      require(observed.nonEmpty, s"$process has no observed temporal instant")
      observed
    } else {
      keys.foreach {
        case key: SpatialKey => require(inside(key, grid) && inBounds(key, minSpatial, maxSpatial),
          s"$process key lies outside metadata grid bounds")
        case _ => throw new IllegalArgumentException(s"$process key type does not match metadata bounds")
      }
      Array.emptyLongArray
    }
    val sample = source.take(1).headOption.getOrElse(throw new IllegalArgumentException(s"$process input is empty"))
    require(sample._2.bandCount == names.size && sample._2.cols == cols && sample._2.rows == rows,
      s"$process sample tile band count or dimensions do not match metadata")
    val tileCells = Math.multiplyExact(Math.multiplyExact(cols.toLong, rows.toLong), names.size.toLong)
    require(tileCells <= MaxTileDecodedCells && keys.length.toLong <= MaxDecodedCells / tileCells,
      s"$process exceeds the decoded-cell budget")
    Input(cube, source, names, kind, times, grid, minSpatial, maxSpatial, cols, rows)
  }

  private def finiteGrid(metadata: TileLayerMetadata[Any]): Grid = {
    val tileBounds = metadata.tileBounds
    val layout = metadata.layout.tileLayout
    val minCol = math.max(0, tileBounds.colMin)
    val minRow = math.max(0, tileBounds.rowMin)
    val maxCol = math.min(layout.layoutCols - 1, tileBounds.colMax)
    val maxRow = math.min(layout.layoutRows - 1, tileBounds.rowMax)
    require(minCol <= maxCol && minRow <= maxRow, "metadata extent has no finite tile grid")
    Grid(minCol, minRow, maxCol, maxRow)
  }

  private def inside(key: SpatialKey, grid: Grid): Boolean =
    key.col >= grid.minCol && key.col <= grid.maxCol && key.row >= grid.minRow && key.row <= grid.maxRow

  private def inside(key: SpaceTimeKey, grid: Grid): Boolean = inside(key.spatialKey, grid)

  private def inBounds(key: SpatialKey, minimum: SpatialKey, maximum: SpatialKey): Boolean =
    key.col >= minimum.col && key.col <= maximum.col && key.row >= minimum.row && key.row <= maximum.row

  def keyInGrid(
    key: Any, kind: String, times: Set[Long], grid: Grid, minSpatial: SpatialKey, maxSpatial: SpatialKey
  ): Boolean = key match {
    case value: SpatialKey => kind == "spatial" && inside(value, grid) && inBounds(value, minSpatial, maxSpatial)
    case value: SpaceTimeKey => kind == "temporal" && times.contains(value.instant) &&
      inside(value, grid) && inBounds(value.spatialKey, minSpatial, maxSpatial)
    case _ => false
  }

  def cubeMetadata(cube: OpenEORasterCube[Any], bands: Seq[String]): OpenEORasterCubeMetadata = {
    val result = new OpenEORasterCubeMetadata(bands)
    result.inputProducts_$eq(Option(cube.openEOMetadata.inputProducts).getOrElse(Seq.empty))
    result
  }

  def copyAsDouble(tile: MultibandTile, bands: Int, cols: Int, rows: Int): MultibandTile = {
    require(tile.bandCount == bands && tile.cols == cols && tile.rows == rows,
      "tile band count or dimensions changed within the input cube")
    val output = new Array[Tile](bands)
    var band = 0
    while (band < bands) {
      // Read with the original cell type's mask. An intermediate convert can
      // mistake a valid Int.MinValue for NoData with a user-defined sentinel.
      val source = tile.band(band)
      val values = new Array[Double](cols * rows)
      var row = 0
      while (row < rows) {
        var col = 0
        while (col < cols) {
          val value = source.getDouble(col, row)
          require(value.isNaN || value.isFinite, "input pixels must be finite or NoData")
          values(row * cols + col) = value
          col += 1
        }
        row += 1
      }
      output(band) = DoubleArrayTile(values, cols, rows, DoubleConstantNoDataCellType)
      band += 1
    }
    ArrayMultibandTile(output)
  }

}
