package local.ee.image.sample

import geotrellis.layer.SpatialKey
import geotrellis.raster.{DoubleConstantNoDataCellType, MultibandTile}
import local.ee.sample.{LocalEeSampleKernel => SampleKernel}
import org.locationtech.jts.geom.{Coordinate, Geometry, GeometryFactory}

import scala.collection.mutable

/** Pixel-center Image.sample kernel; it does not depend on RDD ordering or tile presence. */
object LocalEeImageSampleKernel {
  final case class Row(feature: Int, row: Long, col: Long, x: Double, y: Double,
                       values: Vector[Option[Double]]) extends Serializable

  private val MaxGridKeys = 100000L
  private val MaxRows = 1000
  private val MaxResponseBytes = 1000000
  private val GeometryFactory = new GeometryFactory()
  private val Golden = java.lang.Long.parseUnsignedLong("9e3779b97f4a7c15", 16)
  private val RowSalt = java.lang.Long.parseUnsignedLong("d1b54a32d192ed03", 16)
  private val MixA = java.lang.Long.parseUnsignedLong("bf58476d1ce4e5b9", 16)
  private val MixB = java.lang.Long.parseUnsignedLong("94d049bb133111eb", 16)

  /** Bound metadata-key generation by the ROI's candidate tile rectangle. */
  def candidateKeys(
    feature: SampleKernel.FeatureGeometry, grid: SampleKernel.Grid,
    minKey: SpatialKey, maxKey: SpatialKey
  ): Vector[SpatialKey] = {
    require(feature != null && grid != null && minKey != null && maxKey != null,
      "image sample grid arguments must be present")
    require(minKey.col >= 0 && minKey.row >= 0 && minKey.col <= maxKey.col && minKey.row <= maxKey.row,
      "image sample metadata tile bounds are invalid")
    val tileKeys = feature.geometry.getGeometryType match {
      case "Point" | "MultiPoint" =>
        val keys = mutable.HashSet.empty[SpatialKey]
        feature.pointCells.iterator.foreach { cell =>
          val key = SpatialKey((cell.col / grid.tileCols).toInt, (cell.row / grid.tileRows).toInt)
          if (key.col >= minKey.col && key.col <= maxKey.col &&
              key.row >= minKey.row && key.row <= maxKey.row) {
            keys += key
            require(keys.size.toLong <= MaxGridKeys,
              s"image sample candidate grid exceeds $MaxGridKeys keys")
          }
        }
        keys.toVector.sortBy(key => (key.row, key.col))
      case "Polygon" | "MultiPolygon" =>
        val bounds = feature.geometry.getEnvelopeInternal
        val cols = centerRange((bounds.getMinX - grid.xmin) / grid.cellWidth,
          (bounds.getMaxX - grid.xmin) / grid.cellWidth, grid.columns)
        val rows = centerRange((grid.ymax - bounds.getMaxY) / grid.cellHeight,
          (grid.ymax - bounds.getMinY) / grid.cellHeight, grid.rows)
        (cols, rows) match {
          case (Some((firstCol, lastCol)), Some((firstRow, lastRow))) =>
            val firstTileCol = math.max(minKey.col.toLong, firstCol / grid.tileCols.toLong)
            val lastTileCol = math.min(maxKey.col.toLong, lastCol / grid.tileCols.toLong)
            val firstTileRow = math.max(minKey.row.toLong, firstRow / grid.tileRows.toLong)
            val lastTileRow = math.min(maxKey.row.toLong, lastRow / grid.tileRows.toLong)
            if (firstTileCol > lastTileCol || firstTileRow > lastTileRow) Vector.empty
            else {
              val count = Math.multiplyExact(lastTileCol - firstTileCol + 1L,
                lastTileRow - firstTileRow + 1L)
              require(count <= MaxGridKeys, s"image sample candidate grid exceeds $MaxGridKeys keys")
              val result = Vector.newBuilder[SpatialKey]
              var row = firstTileRow
              while (row <= lastTileRow) {
                var col = firstTileCol
                while (col <= lastTileCol) {
                  result += SpatialKey(col.toInt, row.toInt)
                  col += 1L
                }
                row += 1L
              }
              result.result()
            }
          case _ => Vector.empty
        }
      case other => throw new IllegalArgumentException(s"unsupported image sample region: $other")
    }
    require(tileKeys.size.toLong <= MaxGridKeys, s"image sample candidate grid exceeds $MaxGridKeys keys")
    tileKeys
  }

  /** Grid cells whose centers are covered by the ROI; polygon boundaries are included. */
  def cellsInTile(
    key: SpatialKey, grid: SampleKernel.Grid, feature: SampleKernel.FeatureGeometry
  ): Iterator[SampleKernel.Cell] = {
    validateKey(key, grid)
    feature.geometry.getGeometryType match {
      case "Point" | "MultiPoint" =>
        val firstCol = key.col.toLong * grid.tileCols
        val firstRow = key.row.toLong * grid.tileRows
        feature.pointCells.iterator.filter(cell => cell.row >= firstRow &&
          cell.row < firstRow + grid.tileRows && cell.col >= firstCol &&
          cell.col < firstCol + grid.tileCols)
      case "Polygon" | "MultiPolygon" =>
        val firstCol = key.col.toLong * grid.tileCols
        val firstRow = key.row.toLong * grid.tileRows
        Iterator.range(0, grid.tileRows).flatMap { localRow =>
          Iterator.range(0, grid.tileCols).filter { localCol =>
            val center = grid.center(firstRow + localRow, firstCol + localCol)
            feature.geometry.covers(GeometryFactory.createPoint(new Coordinate(center._1, center._2)))
          }.map(localCol => SampleKernel.Cell(firstRow + localRow, firstCol + localCol))
        }
      case other => throw new IllegalArgumentException(s"unsupported image sample region: $other")
    }
  }

  /** The exact unsigned SplitMix64 grid hash, with global row/column coordinates. */
  def gridRandom(seed: Int, col: Long, row: Long): Double = {
    val hash = mix(seed.toLong ^ mix(col + Golden) ^ mix(row + RowSalt))
    (hash >>> 11).toDouble * (1.0 / 9007199254740992.0)
  }

  def sampleTileIterator(
    tile: Option[MultibandTile], key: SpatialKey, grid: SampleKernel.Grid,
    feature: SampleKernel.FeatureGeometry, options: LocalEeImageSampleOptions.Value,
    bandCount: Int, population: Long, nativeToWgs84: (Double, Double) => (Double, Double)
  ): Iterator[Row] = {
    require(tile != null && options != null && population >= 0 && bandCount >= 1 && bandCount <= 64 &&
      nativeToWgs84 != null,
      "image sample tile arguments are invalid")
    val bands = tile.map { value =>
      require(value.cols == grid.tileCols && value.rows == grid.tileRows &&
        value.bandCount == bandCount,
        "image sample tile shape does not match metadata")
      Array.tabulate(value.bandCount)(index => value.band(index).convert(DoubleConstantNoDataCellType))
    }
    cellsInTile(key, grid, feature).filter(cell => selected(cell, options, population)).flatMap { cell =>
      val localCol = (cell.col - key.col.toLong * grid.tileCols).toInt
      val localRow = (cell.row - key.row.toLong * grid.tileRows).toInt
      val values: Vector[Option[Double]] = bands match {
        case None => Vector.fill(bandCount)(None)
        case Some(sourceBands) => sourceBands.indices.map { band =>
          val value = sourceBands(band).getDouble(localCol, localRow)
          require(value.isNaN || value.isFinite, "sampled valid image pixels must be finite")
          if (value.isNaN) None else Some(value)
        }.toVector
      }
      if (options.dropNulls && values.exists(_.isEmpty)) Iterator.empty
      else {
        val center = grid.center(cell.row, cell.col)
        val wgs84 = nativeToWgs84(center._1, center._2)
        require(wgs84._1.isFinite && wgs84._2.isFinite &&
          wgs84._1 >= -180.0 && wgs84._1 <= 180.0 && wgs84._2 >= -90.0 && wgs84._2 <= 90.0,
          "sampled image pixel center did not transform to finite WGS84 coordinates")
        Iterator.single(Row(0, cell.row, cell.col, wgs84._1, wgs84._2, values))
      }
    }
  }

  def rowsJson(rows: Seq[Row]): String = {
    require(rows != null && rows.size <= MaxRows, s"image sample result exceeds the $MaxRows-row limit")
    val ordered = rows.sortBy(row => (row.feature, row.row, row.col))
    val out = new StringBuilder("[")
    ordered.zipWithIndex.foreach { case (row, index) =>
      if (index > 0) out.append(',')
      out.append("{\"feature\":").append(row.feature).append(",\"row\":").append(row.row)
        .append(",\"col\":").append(row.col).append(",\"x\":").append(number(row.x))
        .append(",\"y\":").append(number(row.y)).append(",\"values\":[")
      row.values.zipWithIndex.foreach { case (value, band) =>
        if (band > 0) out.append(',')
        value match {
          case Some(numberValue) => out.append(number(numberValue))
          case None => out.append("null")
        }
      }
      out.append("]}")
    }
    out.append(']')
    val json = out.toString()
    require(json.getBytes(java.nio.charset.StandardCharsets.UTF_8).length <= MaxResponseBytes,
      "image sample response exceeds 1 MB")
    json
  }

  private def selected(cell: SampleKernel.Cell, options: LocalEeImageSampleOptions.Value,
                       population: Long): Boolean = options.factor match {
    case Some(factor) => gridRandom(options.seed, cell.col, cell.row) < factor
    case None => options.numPixels match {
      case Some(_) if population == 0L => false
      case Some(count) => gridRandom(options.seed, cell.col, cell.row) <
        math.min(1.0, count.toDouble / population.toDouble)
      case None => true
    }
  }

  private def centerRange(low: Double, high: Double, count: Long): Option[(Long, Long)] = {
    val first = math.ceil(low - 0.5)
    val last = math.floor(high - 0.5)
    if (!first.isFinite || !last.isFinite || first > count - 1.0 || last < 0.0) None
    else {
      val boundedFirst = math.max(0.0, first).toLong
      val boundedLast = math.min(count - 1.0, last).toLong
      if (boundedFirst <= boundedLast) Some((boundedFirst, boundedLast)) else None
    }
  }

  private def validateKey(key: SpatialKey, grid: SampleKernel.Grid): Unit = {
    require(key != null && key.col >= 0 && key.row >= 0 &&
      (key.col.toLong + 1L) * grid.tileCols <= grid.columns &&
      (key.row.toLong + 1L) * grid.tileRows <= grid.rows,
      "image sample key lies outside the finite grid")
  }

  private def mix(value: Long): Long = {
    var z = value
    z = (z ^ (z >>> 30)) * MixA
    z = (z ^ (z >>> 27)) * MixB
    z ^ (z >>> 31)
  }

  private def number(value: Double): String = {
    require(value.isFinite, "image sample response numbers must be finite")
    java.lang.Double.toString(value)
  }
}
