package local.ee.image.sample

import geotrellis.layer.{SpatialKey, TileLayerMetadata}
import geotrellis.proj4.{LatLng, Transform}
import geotrellis.raster.MultibandTile
import geotrellis.spark.ContextRDD
import org.apache.spark.rdd.RDD
import org.openeo.geotrelliscommon.{CubeProcessProvider, OpenEORasterCube, OpenEOProcess}
import local.ee.sample.LocalEeSampleKernel

import scala.jdk.CollectionConverters._

/** Bounded Image.sample adapter over a single finite spatial raster grid. */
final class LocalEeImageSampleCubeProcesses extends Serializable {
  private val MaxSampleWork = 67108864L
  private val MaxSourceKeys = 100000
  private val MaxDecodedCells = 100000000L
  private val MaxTileDecodedCells = 10000000L

  private final case class Input(
    cube: OpenEORasterCube[Any],
    source: ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]],
    names: Vector[String], grid: LocalEeSampleKernel.Grid,
    sourceMinKey: SpatialKey, sourceMaxKey: SpatialKey,
    finiteMinKey: SpatialKey, finiteMaxKey: SpatialKey, cols: Int, rows: Int
  )

  @OpenEOProcess(
    id = "local_ee_image_sample",
    description = "Sample actual finite image pixels using a bounded grid-stable selection.",
    returns = "string"
  )
  def localEeImageSample(data: Object, arguments: java.util.Map[String, Object]): Object = {
    require(arguments != null && arguments.size() == 2 && arguments.containsKey("regions") &&
      arguments.containsKey("options"),
      "local_ee_image_sample requires only regions and options arguments")
    val regions = arguments.get("regions") match {
      case values: java.util.List[_] => values.asScala.map {
        case value: String => value
        case _ => throw new IllegalArgumentException("regions must contain only WKT strings")
      }.toVector
      case _ => throw new IllegalArgumentException("regions must be a list of WKT strings")
    }
    require(regions.length == 1, "local_ee_image_sample requires exactly one region")
    val options = arguments.get("options") match {
      case value: String => LocalEeImageSampleOptions.parse(value)
      case _ => throw new IllegalArgumentException("image sample options must be a JSON string")
    }
    val input = validateInput(data)
    val sourceCrs = input.source.metadata.crs
    val grid = input.grid
    val bandCount = input.names.length
    val geometry = LocalEeSampleKernel.parseAndProjectWkts(regions.asJava, sourceCrs).head
    val feature = LocalEeSampleKernel.prepareFeatures(Seq(geometry), grid).head
    val candidateKeys = LocalEeImageSampleKernel.candidateKeys(
      feature, grid, input.finiteMinKey, input.finiteMaxKey)
    val tileWork = Math.multiplyExact(Math.multiplyExact(input.cols.toLong, input.rows.toLong), bandCount.toLong)
    require(tileWork == 0L || candidateKeys.size.toLong <= MaxSampleWork / tileWork,
      s"local_ee_image_sample exceeds the $MaxSampleWork candidate-pixel work budget")

    val source = validateSource(input)
    val partitions = math.max(1, math.min(candidateKeys.length.max(1), input.source.context.defaultParallelism))
    val keys: RDD[(SpatialKey, Boolean)] = input.source.context.parallelize(candidateKeys, partitions)
      .map(key => key -> true)
    val population = if (options.numPixels.contains(0) || candidateKeys.isEmpty) 0L
      else keys.keys.flatMap(key => LocalEeImageSampleKernel.cellsInTile(key, grid, feature)).count()
    val output = keys.leftOuterJoin(source).flatMap { case (key, (_, tile)) =>
      val toWgs84 = Transform(sourceCrs, LatLng)
      LocalEeImageSampleKernel.sampleTileIterator(tile, key, grid, feature, options,
        bandCount, population, (x, y) => {
          val point = toWgs84(x, y)
          (point._1, point._2)
        })
    }
    val rows = output.take(1001)
    require(rows.length <= 1000, "local_ee_image_sample result exceeds the 1000-row limit")
    LocalEeImageSampleKernel.rowsJson(rows.sortBy(row => (row.feature, row.row, row.col)).toVector)
  }

  private def validateInput(data: Object): Input = {
    val cube = data match {
      case value: OpenEORasterCube[_] => value.asInstanceOf[OpenEORasterCube[Any]]
      case _ => throw new IllegalArgumentException("local_ee_image_sample data must be an OpenEORasterCube")
    }
    val source = cube.asInstanceOf[ContextRDD[Any, MultibandTile, TileLayerMetadata[Any]]]
    val metadata = source.metadata
    val extent = metadata.extent
    val layout = metadata.layout
    require(!extent.isEmpty && Seq(extent.xmin, extent.ymin, extent.xmax, extent.ymax).forall(_.isFinite) &&
      layout.extent.contains(extent), "local_ee_image_sample requires finite source extent metadata")
    val tileLayout = layout.tileLayout
    val cols = tileLayout.tileCols
    val rows = tileLayout.tileRows
    require(cols > 0 && rows > 0 && tileLayout.layoutCols > 0 && tileLayout.layoutRows > 0,
      "local_ee_image_sample requires positive finite layout dimensions")
    val grid = LocalEeSampleKernel.Grid(layout.extent.xmin, layout.extent.ymin,
      layout.extent.xmax, layout.extent.ymax,
      Math.multiplyExact(tileLayout.layoutCols.toLong, cols.toLong),
      Math.multiplyExact(tileLayout.layoutRows.toLong, rows.toLong), cols, rows)
    val bounds = metadata.bounds.getOrElse(throw new IllegalArgumentException(
      "local_ee_image_sample requires finite source tile bounds, including for an empty tile RDD"))
    val (minimum, maximum) = (bounds.minKey, bounds.maxKey) match {
      case (first: SpatialKey, last: SpatialKey) => (first, last)
      case _ => throw new IllegalArgumentException("local_ee_image_sample requires spatial metadata without time")
    }
    val tileBounds = metadata.tileBounds
    val finiteMinCol = math.max(0, tileBounds.colMin)
    val finiteMinRow = math.max(0, tileBounds.rowMin)
    val finiteMaxCol = math.min(tileLayout.layoutCols - 1, tileBounds.colMax)
    val finiteMaxRow = math.min(tileLayout.layoutRows - 1, tileBounds.rowMax)
    require(finiteMinCol <= finiteMaxCol && finiteMinRow <= finiteMaxRow,
      "local_ee_image_sample metadata extent has no finite tile grid")
    require(minimum.col >= finiteMinCol && minimum.row >= finiteMinRow &&
      minimum.col <= maximum.col && minimum.row <= maximum.row &&
      maximum.col <= finiteMaxCol && maximum.row <= finiteMaxRow,
      "local_ee_image_sample metadata bounds lie outside the clipped finite tile bounds")
    val names = Option(cube.openEOMetadata.bands).map(_.toVector).getOrElse(Vector.empty)
    require(names.nonEmpty && names.length <= 64 && names.forall(name => name != null && name.nonEmpty) &&
      names.distinct.length == names.length,
      "local_ee_image_sample requires 1 to 64 uniquely named source bands")
    val tileCells = Math.multiplyExact(Math.multiplyExact(cols.toLong, rows.toLong), names.length.toLong)
    require(tileCells <= MaxTileDecodedCells,
      s"local_ee_image_sample tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    Input(cube, source, names, grid, minimum, maximum,
      SpatialKey(finiteMinCol, finiteMinRow), SpatialKey(finiteMaxCol, finiteMaxRow), cols, rows)
  }

  /** Validate every source tile before joining the finite key set; only keys reach the driver. */
  private def validateSource(input: Input): RDD[(SpatialKey, MultibandTile)] = {
    // Keep the Spark closure limited to simple serializable metadata values; Input also holds
    // the cube and ContextRDD and must stay on the driver.
    val sourceMinKey = input.sourceMinKey
    val sourceMaxKey = input.sourceMaxKey
    val layoutCols = input.source.metadata.layout.tileLayout.layoutCols
    val layoutRows = input.source.metadata.layout.tileLayout.layoutRows
    val bandCount = input.names.length
    val cols = input.cols
    val rows = input.rows
    val tileCells = Math.multiplyExact(Math.multiplyExact(cols.toLong, rows.toLong), bandCount.toLong)
    val maxSourceKeys = math.min(MaxSourceKeys.toLong, MaxDecodedCells / tileCells).toInt
    val checked = input.source.map { case (rawKey, tile) =>
      val key = rawKey match {
        case value: SpatialKey => value
        case _ => throw new IllegalArgumentException("local_ee_image_sample encountered a non-spatial tile key")
      }
      require(key.col >= sourceMinKey.col && key.col <= sourceMaxKey.col &&
        key.row >= sourceMinKey.row && key.row <= sourceMaxKey.row &&
        key.col >= 0 && key.row >= 0 && key.col < layoutCols && key.row < layoutRows,
        "local_ee_image_sample encountered a source key outside metadata bounds")
      require(tile != null && tile.bandCount == bandCount && tile.cols == cols && tile.rows == rows,
        "local_ee_image_sample tile band count or dimensions changed within the cube")
      key -> tile
    }
    val keyCount = checked.keys.take(maxSourceKeys + 1).length
    require(keyCount <= maxSourceKeys,
      s"local_ee_image_sample exceeds the $MaxDecodedCells aggregate decoded-cell budget")
    val duplicate = checked.keys.map(key => key -> 1L).reduceByKey(_ + _)
      .filter { case (_, count) => count > 1L }.take(1)
    require(duplicate.isEmpty, "local_ee_image_sample input contains duplicate source tile keys")
    checked
  }
}

/** ServiceLoader entry point for the atomic integer/raster adapter JAR. */
final class LocalEeImageSampleCubeProcessProvider extends CubeProcessProvider {
  override def getInstance(): Object = new LocalEeImageSampleCubeProcesses()
}
