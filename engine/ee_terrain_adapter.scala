package local.ee.reduce

import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{ArrayMultibandTile, DoubleConstantNoDataCellType, GridBounds, MultibandTile, Tile}
import geotrellis.raster.buffer.BufferedTile
import geotrellis.spark._
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}

/** Bounded one-band slope/aspect/hillshade SPI preserving the real grid and observed keys. */
final class LocalEeTerrainCubeProcesses extends Serializable {
  @OpenEOProcess(
    id = "local_ee_terrain",
    description = "Calculate local-tangent slope, aspect, or hillshade from four-connected raster neighbors.",
    returns = "datacube"
  )
  def localEeTerrain(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 1 && arguments.containsKey("spec"),
      "local_ee_terrain requires only a spec argument")
    val spec = arguments.get("spec") match {
      case value: String => LocalEeTerrainSpec.parse(value)
      case _ => throw new IllegalArgumentException("terrain spec must be a JSON string")
    }
    val input = LocalEeReduceSupport.validate(data, "local_ee_terrain")
    require(input.names.length == 1, "local_ee_terrain requires exactly one input band")
    val grid = metricGrid(input)
    val plan = preflight(input)

    // Validate every real cell before the halo path runs; NaN is the sole NoData encoding.
    val kind = input.kind
    val times = input.times.toSet
    val sourceGrid = input.grid
    val minimum = input.minSpatial
    val maximum = input.maxSpatial
    val cols = input.cols
    val rows = input.rows
    val checked: RDD[(Any, MultibandTile)] = input.source.map { case (key, tile) =>
      require(LocalEeReduceSupport.keyInGrid(key, kind, times, sourceGrid, minimum, maximum),
        "local_ee_terrain key lies outside declared grid bounds")
      validateTile(tile, cols, rows)
      key -> tile
    }
    require(checked.count() == plan.keyCount,
      "local_ee_terrain source key count changed during tile validation")

    val bounds = GridBounds[Int](sourceGrid.minCol, sourceGrid.minRow, sourceGrid.maxCol, sourceGrid.maxRow)
    val crs = input.source.metadata.crs
    val output: RDD[(Any, MultibandTile)] = kind match {
      case "spatial" => spatialPass(checked, cols, rows, bounds, grid, crs, spec)
      case "temporal" => temporalPass(checked, cols, rows, bounds, grid, crs, spec)
      case _ => throw new IllegalArgumentException("local_ee_terrain input key type is unsupported")
    }
    val layerMetadata = input.source.metadata.copy(cellType = DoubleConstantNoDataCellType)
    new OpenEORasterCube[Any](output, layerMetadata,
      LocalEeReduceSupport.cubeMetadata(input.cube, Seq("v")))
  }

  private def preflight(input: LocalEeReduceSupport.Input): LocalEeTerrainBudget.Plan = {
    val keys = input.source.keys.take((LocalEeTerrainBudget.MaxSourceKeys + 1L).toInt)
    LocalEeTerrainBudget.plan(keys.length.toLong, input.cols, input.rows)
  }

  private def metricGrid(input: LocalEeReduceSupport.Input): LocalEeTerrainMetric.Grid = {
    val layout = input.source.metadata.layout
    val tileLayout = layout.tileLayout
    val columns = Math.multiplyExact(tileLayout.layoutCols.toLong, input.cols.toLong)
    val rows = Math.multiplyExact(tileLayout.layoutRows.toLong, input.rows.toLong)
    require(columns <= (1L << 52) && rows <= (1L << 52),
      "local_ee_terrain pixel-center half-cell coordinates exceed exact binary64 indexing")
    val extent = layout.extent
    val width = extent.xmax - extent.xmin
    val height = extent.ymax - extent.ymin
    require(Seq(extent.xmin, extent.ymin, extent.xmax, extent.ymax, width, height).forall(_.isFinite) &&
      width > 0.0d && height > 0.0d,
      "local_ee_terrain actual layout extent must be finite and non-empty")
    LocalEeTerrainMetric.Grid(extent.xmin, extent.ymax, width / columns.toDouble,
      height / rows.toDouble, columns, rows)
  }

  private def validateTile(tile: MultibandTile, cols: Int, rows: Int): Unit = {
    require(tile != null && tile.bandCount == 1 && tile.cols == cols && tile.rows == rows,
      "local_ee_terrain tile band count or dimensions changed within the cube")
    val band = tile.band(0)
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        val value = band.getDouble(col, row)
        require(value.isNaN || value.isFinite,
          "local_ee_terrain input pixels must be finite or NoData")
        col += 1
      }
      row += 1
    }
  }

  private def spatialPass(
    source: RDD[(Any, MultibandTile)], cols: Int, rows: Int, bounds: GridBounds[Int],
    grid: LocalEeTerrainMetric.Grid, crs: geotrellis.proj4.CRS, spec: LocalEeTerrainSpec.Value
  ): RDD[(Any, MultibandTile)] = {
    val typed = source.asInstanceOf[RDD[(SpatialKey, MultibandTile)]]
    typed.bufferTiles(1, bounds, typed.partitioner).map { case (key, buffered) =>
      key -> outputTile(buffered, key.col, key.row, cols, rows, grid, crs, spec)
    }.asInstanceOf[RDD[(Any, MultibandTile)]]
  }

  private def temporalPass(
    source: RDD[(Any, MultibandTile)], cols: Int, rows: Int, bounds: GridBounds[Int],
    grid: LocalEeTerrainMetric.Grid, crs: geotrellis.proj4.CRS, spec: LocalEeTerrainSpec.Value
  ): RDD[(Any, MultibandTile)] = {
    val typed = source.asInstanceOf[RDD[(SpaceTimeKey, MultibandTile)]]
    typed.bufferTiles(1, bounds, typed.partitioner).map { case (key, buffered) =>
      key -> outputTile(buffered, key.col, key.row, cols, rows, grid, crs, spec)
    }.asInstanceOf[RDD[(Any, MultibandTile)]]
  }

  private def outputTile(
    buffered: BufferedTile[MultibandTile], tileCol: Int, tileRow: Int, cols: Int, rows: Int,
    grid: LocalEeTerrainMetric.Grid, crs: geotrellis.proj4.CRS, spec: LocalEeTerrainSpec.Value
  ): MultibandTile = {
    val transform = LocalEeTerrainMetric.fromCrs(crs)
    val result = LocalEeTerrainNumeric.applyBufferedTile(buffered.tile.band(0), buffered.targetArea,
      cols, rows, tileCol, tileRow, grid, transform, spec)
    ArrayMultibandTile(Array[Tile](result.tile))
  }
}

/** ServiceLoader entry point for the atomic native adapter JAR. */
final class LocalEeTerrainCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeTerrainCubeProcesses()
}
