package local.ee.mask

import geotrellis.layer.{Bounds, KeyBounds, SpatialKey, SpaceTimeKey, TileLayerMetadata}
import geotrellis.raster.{ArrayMultibandTile, DoubleArrayTile, DoubleConstantNoDataCellType, MultibandTile, Tile}
import geotrellis.spark.ContextRDD
import org.apache.spark.rdd.RDD
import org.openeo.geotrellis.OpenEOProcesses
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEORasterCubeMetadata, OpenEOProcess}

/** Precision-preserving, same-grid implementation of EE Image.unmask. */
final class LocalEeMaskCubeProcesses extends Serializable {
  private val MaxTimeKeys = 10000

  @OpenEOProcess(
    id = "local_ee_unmask",
    description = "Replace NoData pixels from an aligned single-band cube using Float64 values.",
    returns = "datacube"
  )
  def localEeUnmask(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.containsKey("value"), "local_ee_unmask requires value cube")
    val inputCube = asCube(data, "data")
    val valueCube = asCube(arguments.get("value"), "value")
    val sameFootprint = booleanArgument(arguments, "same_footprint", default = true)
    val input = inputCube.asInstanceOf[ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]]]
    val value = valueCube.asInstanceOf[ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]]]
    val inputSample = input.take(1).headOption.getOrElse(
      throw new IllegalArgumentException("local_ee_unmask cannot infer keys or times from an empty input RDD")
    )
    require(input.metadata.bounds.nonEmpty, "local_ee_unmask input has EmptyBounds; exact grid bounds cannot be inferred")
    require(sameKeyKind(inputSample._1, input.metadata.bounds.get.minKey) &&
      sameKeyKind(inputSample._1, input.metadata.bounds.get.maxKey),
      "input key type does not match its metadata bounds")
    val valueSample = value.take(1).headOption
    val names = inputCube.openEOMetadata.bands
    require(names.size == 1, "local_ee_unmask requires exactly one input band")
    require(valueCube.openEOMetadata.bands.size == 1, "local_ee_unmask requires exactly one replacement band")
    require(inputSample._2.bandCount == 1, "local_ee_unmask requires exactly one input band")
    valueSample.foreach(sample => require(sample._2.bandCount == 1,
      "local_ee_unmask requires exactly one replacement band"))
    requireUniqueKeys(input, "input")
    if (valueSample.nonEmpty) requireUniqueKeys(value, "replacement")
    require(input.metadata.layout == value.metadata.layout && input.metadata.crs == value.metadata.crs,
      "local_ee_unmask requires identical CRS and layout; resample explicitly first")
    val tileCols = input.metadata.layout.tileCols
    val tileRows = input.metadata.layout.tileRows
    require(tileCols > 0 && tileRows > 0, "local_ee_unmask tile dimensions must be positive")
    require(inputSample._2.cols == tileCols && inputSample._2.rows == tileRows,
      "input tile dimensions do not match its layout")
    valueSample.foreach(sample => require(sample._2.cols == tileCols && sample._2.rows == tileRows,
      "replacement tile dimensions do not match its layout"))
    require(input.metadata.extent.intersects(input.metadata.layout.extent) &&
      input.metadata.layout.extent.contains(input.metadata.extent),
      "input extent must be finite and inside the aligned layout")
    val inputGrid = finiteGrid(input.metadata)
    val inputTimes = observedTimes(input, inputSample._1)
    if (valueSample.nonEmpty) {
      require(value.metadata.extent.intersects(value.metadata.layout.extent) &&
        value.metadata.layout.extent.contains(value.metadata.extent),
        "replacement extent must be finite and inside the aligned layout")
      require(value.metadata.bounds.nonEmpty, "local_ee_unmask replacement has EmptyBounds")
      finiteGrid(value.metadata)
      require(isSameKeyKind(inputSample._1, valueSample.get._1),
        "local_ee_unmask cannot mix SpatialKey and SpaceTimeKey cubes")
      require(sameKeyKind(valueSample.get._1, value.metadata.bounds.get.minKey) &&
        sameKeyKind(valueSample.get._1, value.metadata.bounds.get.maxKey),
        "replacement key type does not match its metadata bounds")
      require(inputTimes.sameElements(observedTimes(value, valueSample.get._1)),
        "local_ee_unmask requires the same explicit time keys on both cubes")
    }

    val joined: RDD[(Any, MultibandTile)] = input.fullOuterJoin(value).flatMap { case (key, (left, right)) =>
      if (sameFootprint && left.isEmpty && !inputGrid.contains(key)) None
      else {
        require(inLayout(key, input.metadata.layout.tileLayout.layoutCols,
          input.metadata.layout.tileLayout.layoutRows), "cube key lies outside its declared layout")
        val result = mergeTile(left, right, tileCols, tileRows)
        Some(key -> (ArrayMultibandTile(Array[Tile](result)): MultibandTile))
      }
    }
    val outputExtent = if (sameFootprint || valueSample.isEmpty) input.metadata.extent
      else input.metadata.extent.combine(value.metadata.extent)
    val outputMetadataExtent = input.metadata.copy(extent = outputExtent)
    val outputBounds = completeBounds(outputMetadataExtent, inputSample._1, inputTimes)
    val layerMetadata: TileLayerMetadata[Any] = input.metadata.copy(
      cellType = DoubleConstantNoDataCellType, extent = outputExtent, bounds = outputBounds
    )
    val outputMetadata = new OpenEORasterCubeMetadata(names)
    val inputProducts = Option(inputCube.openEOMetadata.inputProducts).getOrElse(Seq.empty)
    val replacementProducts = Option(valueCube.openEOMetadata.inputProducts).getOrElse(Seq.empty)
    val products = if (sameFootprint || valueSample.isEmpty) inputProducts
      else inputProducts ++ replacementProducts
    outputMetadata.inputProducts_$eq(products)
    new OpenEORasterCube[Any](joined, layerMetadata, outputMetadata)
  }

  private def asCube(value: Object, label: String): OpenEORasterCube[Any] = value match {
    case cube: OpenEORasterCube[_] => cube.asInstanceOf[OpenEORasterCube[Any]]
    case raw: ContextRDD[_, _, _] =>
      val wrapped = new OpenEOProcesses().wrapCube(
        raw.asInstanceOf[ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]]]
      )
      wrapped.openEOMetadata.bands_$eq(Seq("band_unnamed"))
      wrapped.asInstanceOf[OpenEORasterCube[Any]]
    case _ => throw new IllegalArgumentException(s"local_ee_unmask $label must be a raster cube")
  }

  private def booleanArgument(args: java.util.Map[String, Object], name: String, default: Boolean): Boolean = {
    if (!args.containsKey(name)) default
    else args.get(name) match {
      case value: java.lang.Boolean => value.booleanValue()
      case _ => throw new IllegalArgumentException(s"$name must be a boolean")
    }
  }

  private def isSameKeyKind(left: Any, right: Any): Boolean =
    (left, right) match {
      case (_: SpatialKey, _: SpatialKey) => true
      case (_: SpaceTimeKey, _: SpaceTimeKey) => true
      case _ => false
    }

  private def sameKeyKind(left: Any, right: Any): Boolean = isSameKeyKind(left, right)

  private def observedTimes(rdd: RDD[(Any, MultibandTile)], key: Any): Array[Long] = key match {
    case _: SpatialKey => Array.emptyLongArray
    case _: SpaceTimeKey =>
      val found = rdd.map(_._1.asInstanceOf[SpaceTimeKey].instant)
        .distinct().take(MaxTimeKeys + 1).sorted
      require(found.nonEmpty && found.length <= MaxTimeKeys,
        s"local_ee_unmask supports at most $MaxTimeKeys explicit time keys")
      found
    case other => throw new IllegalArgumentException(s"unsupported key type: ${other.getClass.getName}")
  }

  private def requireUniqueKeys(rdd: RDD[(Any, MultibandTile)], label: String): Unit = {
    val duplicate = rdd.map(_._1 -> 1L).reduceByKey(_ + _).filter(_._2 > 1L).take(1)
    require(duplicate.isEmpty, s"local_ee_unmask $label cube contains duplicate tile keys")
  }

  private def inLayout(key: Any, cols: Int, rows: Int): Boolean = {
    val spatial = key match {
      case value: SpatialKey => value
      case value: SpaceTimeKey => value.spatialKey
      case _ => return false
    }
    spatial.col >= 0 && spatial.row >= 0 && spatial.col < cols && spatial.row < rows
  }

  private final class Grid(val minCol: Int, val minRow: Int, val maxCol: Int, val maxRow: Int)
      extends Serializable {
    def contains(key: Any): Boolean = key match {
      case spatial: SpatialKey => contains(spatial)
      case temporal: SpaceTimeKey => contains(temporal.spatialKey)
      case _ => false
    }
    private def contains(key: SpatialKey): Boolean = key.col >= minCol && key.col <= maxCol &&
      key.row >= minRow && key.row <= maxRow
  }

  private def finiteGrid(metadata: TileLayerMetadata[Any]): Grid = {
    require(!metadata.bounds.isEmpty, "metadata has EmptyBounds")
    val extent = metadata.extent
    require(!extent.isEmpty && Seq(extent.xmin, extent.ymin, extent.xmax, extent.ymax).forall(_.isFinite),
      "metadata extent must be finite and non-empty")
    val tileBounds = metadata.tileBounds
    val layout = metadata.layout.tileLayout
    val minCol = math.max(0, tileBounds.colMin)
    val minRow = math.max(0, tileBounds.rowMin)
    val maxCol = math.min(layout.layoutCols - 1, tileBounds.colMax)
    val maxRow = math.min(layout.layoutRows - 1, tileBounds.rowMax)
    require(minCol <= maxCol && minRow <= maxRow, "metadata extent is outside its finite layout")
    val keys = metadata.bounds.get
    val minSpatial = spatialKey(keys.minKey)
    val maxSpatial = spatialKey(keys.maxKey)
    require(minSpatial.col >= minCol && minSpatial.row >= minRow &&
      maxSpatial.col <= maxCol && maxSpatial.row <= maxRow,
      "metadata key bounds extend outside its finite extent")
    new Grid(minCol, minRow, maxCol, maxRow)
  }

  private def completeBounds(metadata: TileLayerMetadata[Any], sample: Any, times: Array[Long]): Bounds[Any] = {
    val grid = finiteGrid(metadata)
    sample match {
      case _: SpatialKey => KeyBounds[Any](SpatialKey(grid.minCol, grid.minRow), SpatialKey(grid.maxCol, grid.maxRow))
      case _: SpaceTimeKey => KeyBounds[Any](SpaceTimeKey(grid.minCol, grid.minRow, times.head),
        SpaceTimeKey(grid.maxCol, grid.maxRow, times.last))
      case other => throw new IllegalArgumentException(s"unsupported key type: ${other.getClass.getName}")
    }
  }

  private def spatialKey(key: Any): SpatialKey = key match {
    case spatial: SpatialKey => spatial
    case temporal: SpaceTimeKey => temporal.spatialKey
    case other => throw new IllegalArgumentException(s"unsupported key type: ${other.getClass.getName}")
  }

  private def mergeTile(
    left: Option[MultibandTile], right: Option[MultibandTile], cols: Int, rows: Int
  ): Tile = {
    def band(tile: MultibandTile): Tile = {
      require(tile.bandCount == 1 && tile.cols == cols && tile.rows == rows,
        "unmask tiles must have one band and match the declared cell grid")
      val source = tile.band(0)
      val values = Array.ofDim[Double](cols * rows)
      var row = 0
      while (row < rows) {
        var col = 0
        while (col < cols) {
          values(row * cols + col) = source.getDouble(col, row)
          col += 1
        }
        row += 1
      }
      DoubleArrayTile(values, cols, rows, DoubleConstantNoDataCellType)
    }
    (left, right) match {
      case (Some(a), Some(b)) =>
        val original = band(a)
        val fallback = band(b)
        val values = Array.ofDim[Double](cols * rows)
        var row = 0
        while (row < rows) {
          var col = 0
          while (col < cols) {
            val originalValue = original.getDouble(col, row)
            values(row * cols + col) = if (!originalValue.isNaN) originalValue
              else fallback.getDouble(col, row)
            col += 1
          }
          row += 1
        }
        DoubleArrayTile(values, cols, rows, DoubleConstantNoDataCellType)
      case (Some(a), None) => band(a)
      case (None, Some(b)) => band(b)
      case _ => throw new IllegalStateException("fullOuterJoin produced an empty key")
    }
  }
}

/** ServiceLoader entry point; the task-level builder adds this provider explicitly. */
final class LocalEeMaskCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeMaskCubeProcesses()
}
