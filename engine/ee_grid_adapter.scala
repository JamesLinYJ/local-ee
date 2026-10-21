package local.ee.grid

import geotrellis.layer.{KeyBounds, SpatialKey, SpaceTimeKey, TileLayerMetadata}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import geotrellis.spark.ContextRDD
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEORasterCubeMetadata, OpenEOProcess}

/** Bounded raster materialization for scalar Earth Engine image pixels. */
final class LocalEeGridCubeProcesses extends Serializable {
  private val MaxGridKeys = 100000L
  private val MaxGeneratedCells = 100000000L
  private val MaxTimeKeys = 10000

  @OpenEOProcess(
    id = "local_ee_constant_on_grid",
    description = "Materialize one finite Float64 constant band on an existing raster grid.",
    returns = "datacube"
  )
  def localEeConstantOnGrid(data: Object, arguments: java.util.Map[String, Object]): Object = {
    val value = scalar(arguments)
    val cube = data.asInstanceOf[OpenEORasterCube[Any]]
    val source = cube.asInstanceOf[ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]]]
    val sample = source.take(1).headOption.getOrElse(
      throw new IllegalArgumentException("local_ee_constant_on_grid requires a non-empty raster template")
    )
    val names = cube.openEOMetadata.bands
    require(names.size == 1, "local_ee_constant_on_grid requires exactly one template band")
    val sampleTile = sample._2
    require(sampleTile.bandCount == 1, "local_ee_constant_on_grid requires exactly one template band")

    val metadata = source.metadata
    val sourceBounds = metadata.bounds.getOrElse(
      throw new IllegalArgumentException("template metadata has EmptyBounds; no finite tile keys can be inferred")
    )
    require(sameKeyKind(sample._1, sourceBounds.minKey) && sameKeyKind(sample._1, sourceBounds.maxKey),
      "template key type does not match its metadata bounds")
    val layout = metadata.layout
    val tileLayout = layout.tileLayout
    val tileCols = tileLayout.tileCols
    val tileRows = tileLayout.tileRows
    require(tileCols > 0 && tileRows > 0, "template tile dimensions must be positive")
    require(sampleTile.cols == tileCols && sampleTile.rows == tileRows,
      "template tile dimensions do not match its layout")
    val grid = finiteGrid(metadata)
    require(grid.contains(sample._1), "template key bounds do not match its finite metadata extent")

    val spatialCount = Math.multiplyExact(grid.cols.toLong, grid.rows.toLong)
    val times = sample._1 match {
      case _: SpatialKey => Array.emptyLongArray
      case _: SpaceTimeKey =>
        val found = source.map(_._1.asInstanceOf[SpaceTimeKey].instant).distinct().take(MaxTimeKeys + 1).sorted
        require(found.nonEmpty && found.length <= MaxTimeKeys,
          s"template has more than $MaxTimeKeys time keys or no recoverable time keys")
        found
      case key => throw new IllegalArgumentException(s"unsupported template key type: ${key.getClass.getName}")
    }
    val timeCount = if (times.isEmpty) 1L else times.length.toLong
    require(spatialCount <= MaxGridKeys / timeCount, s"constant grid exceeds $MaxGridKeys tile keys")
    val keyCount = spatialCount * timeCount
    val cellsPerTile = Math.multiplyExact(tileCols.toLong, tileRows.toLong)
    require(keyCount <= MaxGeneratedCells / cellsPerTile,
      s"constant grid exceeds $MaxGeneratedCells generated cells including all time keys")

    val partitions = math.max(1, math.min(source.getNumPartitions, keyCount.toInt))
    val generated: RDD[(Any, MultibandTile)] = source.context
      .range(0L, keyCount, 1L, partitions)
      .map { index =>
        val timeIndex = (index / spatialCount).toInt
        val withinTime = index % spatialCount
        val col = grid.minCol + (withinTime % grid.cols).toInt
        val row = grid.minRow + (withinTime / grid.cols).toInt
        val key: Any = if (times.isEmpty) SpatialKey(col, row)
          else SpaceTimeKey(col, row, times(timeIndex))
        val tile = ArrayMultibandTile(Array[Tile](DoubleArrayTile.fill(
          value, tileCols, tileRows, DoubleConstantNoDataCellType
        )))
        key -> tile
      }

    val bounds: KeyBounds[Any] = if (times.isEmpty) {
      KeyBounds[Any](SpatialKey(grid.minCol, grid.minRow), SpatialKey(grid.maxCol, grid.maxRow))
    } else {
      KeyBounds[Any](SpaceTimeKey(grid.minCol, grid.minRow, times.head),
        SpaceTimeKey(grid.maxCol, grid.maxRow, times.last))
    }
    val outputMetadata = new OpenEORasterCubeMetadata(names)
    outputMetadata.inputProducts_$eq(Option(cube.openEOMetadata.inputProducts).getOrElse(Seq.empty))
    val layerMetadata = metadata.copy(cellType = DoubleConstantNoDataCellType, bounds = bounds)
    new OpenEORasterCube[Any](generated, layerMetadata, outputMetadata)
  }

  private final class Grid(val minCol: Int, val minRow: Int, val maxCol: Int, val maxRow: Int)
      extends Serializable {
    val cols: Int = maxCol - minCol + 1
    val rows: Int = maxRow - minRow + 1
    def contains(key: Any): Boolean = key match {
      case spatial: SpatialKey => contains(spatial)
      case temporal: SpaceTimeKey => contains(temporal.spatialKey)
      case _ => false
    }
    private def contains(key: SpatialKey): Boolean =
      key.col >= minCol && key.col <= maxCol && key.row >= minRow && key.row <= maxRow
  }

  private def finiteGrid(metadata: TileLayerMetadata[Any]): Grid = {
    val extent = metadata.extent
    require(!extent.isEmpty && Seq(extent.xmin, extent.ymin, extent.xmax, extent.ymax).forall(_.isFinite),
      "template metadata extent must be finite and non-empty")
    require(!metadata.bounds.isEmpty, "template metadata has EmptyBounds; no finite tile keys can be inferred")
    val keyBounds = metadata.bounds.get
    val spatialMin = spatialKey(keyBounds.minKey)
    val spatialMax = spatialKey(keyBounds.maxKey)
    val tileBounds = metadata.tileBounds
    val layout = metadata.layout.tileLayout
    val minCol = math.max(0, tileBounds.colMin)
    val minRow = math.max(0, tileBounds.rowMin)
    val maxCol = math.min(layout.layoutCols - 1, tileBounds.colMax)
    val maxRow = math.min(layout.layoutRows - 1, tileBounds.rowMax)
    require(minCol <= maxCol && minRow <= maxRow, "template extent does not intersect its finite layout")
    require(spatialMin.col >= minCol && spatialMin.row >= minRow &&
      spatialMax.col <= maxCol && spatialMax.row <= maxRow,
      "template key bounds extend outside its finite metadata extent")
    new Grid(minCol, minRow, maxCol, maxRow)
  }

  private def spatialKey(key: Any): SpatialKey = key match {
    case spatial: SpatialKey => spatial
    case temporal: SpaceTimeKey => temporal.spatialKey
    case other => throw new IllegalArgumentException(s"unsupported template key type: ${other.getClass.getName}")
  }

  private def sameKeyKind(left: Any, right: Any): Boolean = (left, right) match {
    case (_: SpatialKey, _: SpatialKey) => true
    case (_: SpaceTimeKey, _: SpaceTimeKey) => true
    case _ => false
  }

  private def scalar(arguments: java.util.Map[String, Object]): Double = {
    require(arguments != null && arguments.containsKey("value"), "local_ee_constant_on_grid requires value")
    val raw = arguments.get("value")
    require(raw.isInstanceOf[java.lang.Number], "constant value must be a finite number")
    val number = raw.asInstanceOf[java.lang.Number].doubleValue()
    require(number.isFinite, "constant value must be finite")
    if (number == Math.rint(number)) {
      val exact = new java.math.BigDecimal(number)
      raw match {
        case integer: java.math.BigInteger =>
          require(exact.compareTo(new java.math.BigDecimal(integer)) == 0,
            "integer constant is not exactly representable as Float64")
        case decimal: java.math.BigDecimal =>
          require(exact.compareTo(decimal) == 0,
            "integer constant is not exactly representable as Float64")
        case integral: java.lang.Byte => require(number.toByte == integral.byteValue(), "integer constant is not exactly representable as Float64")
        case integral: java.lang.Short => require(number.toShort == integral.shortValue(), "integer constant is not exactly representable as Float64")
        case integral: java.lang.Integer => require(number.toInt == integral.intValue(), "integer constant is not exactly representable as Float64")
        case integral: java.lang.Long => require(number.toLong == integral.longValue(), "integer constant is not exactly representable as Float64")
        case _ => ()
      }
    }
    number
  }
}

/** ServiceLoader entry point; the task-level builder adds this provider explicitly. */
final class LocalEeGridCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeGridCubeProcesses()
}
