package local.ee.sample

import geotrellis.layer.SpatialKey
import geotrellis.proj4.{CRS, LatLng, Transform}
import geotrellis.raster.{DoubleConstantNoDataCellType, MultibandTile}
import org.locationtech.jts.geom.{Envelope, Geometry, GeometryFactory}
import org.locationtech.jts.geom.CoordinateSequenceFilter
import org.locationtech.jts.io.WKTReader

import scala.collection.mutable

/** Immutable source-grid and projected feature records shared by the SPI and standalone probe. */
object LocalEeSampleKernel {
  final case class Grid(
    xmin: Double, ymin: Double, xmax: Double, ymax: Double,
    columns: Long, rows: Long, tileCols: Int, tileRows: Int
  ) extends Serializable {
    require(Seq(xmin, ymin, xmax, ymax).forall(_.isFinite) && xmin < xmax && ymin < ymax,
      "sampling grid extent must be finite and non-empty")
    require(columns > 0 && rows > 0 && tileCols > 0 && tileRows > 0,
      "sampling grid dimensions must be positive")
    val cellWidth: Double = (xmax - xmin) / columns.toDouble
    val cellHeight: Double = (ymax - ymin) / rows.toDouble
    require(cellWidth.isFinite && cellWidth > 0 && cellHeight.isFinite && cellHeight > 0,
      "sampling grid cell size must be finite and positive")
    require(columns <= 9007199254740992L && rows <= 9007199254740992L,
      "sampling grid dimensions exceed exact binary64 integer coordinates")

    def cellForPoint(x: Double, y: Double): Option[Cell] = {
      if (!x.isFinite || !y.isFinite || x < xmin || x >= xmax || y <= ymin || y > ymax) None
      else {
        val col = math.floor((x - xmin) / cellWidth).toLong
        val row = math.floor((ymax - y) / cellHeight).toLong
        if (col >= 0 && col < columns && row >= 0 && row < rows) Some(Cell(row, col)) else None
      }
    }

    def center(row: Long, col: Long): (Double, Double) =
      (xmin + (col.toDouble + 0.5) * cellWidth, ymax - (row.toDouble + 0.5) * cellHeight)
  }

  final case class Cell(row: Long, col: Long) extends Serializable
  final case class FeatureGeometry(index: Int, geometry: Geometry, pointCells: Vector[Cell]) extends Serializable
  final case class SampleRow(feature: Int, row: Long, col: Long,
                             x: Double, y: Double, values: Vector[Double]) extends Serializable

  private val MaxFeatures = 1000
  private val MaxPositions = 10000
  private val MaxWktBytes = 1000000L
  private val MaxResponseBytes = 1000000
  private val MaxRows = 1000
  private val GeometryFactory = new GeometryFactory()

  /** Parse only planar WGS84 point/multipoint/polygon/multipolygon WKT, then project to source CRS. */
  def parseAndProjectWkts(wkts: java.util.List[String], target: CRS): Vector[Geometry] = {
    require(wkts != null && wkts.size() <= MaxFeatures,
      s"sampling supports at most $MaxFeatures WKT regions")
    require(target != null, "sampling source CRS is required")
    var bytes = 0L
    var positions = 0L
    val toSource = Transform(LatLng, target)
    val reader = new WKTReader(GeometryFactory)
    val result = Vector.newBuilder[Geometry]
    var index = 0
    while (index < wkts.size()) {
      val wkt = wkts.get(index)
      require(wkt != null && wkt.nonEmpty, s"sampling region $index must be a nonempty WKT string")
      bytes = Math.addExact(bytes, wkt.getBytes(java.nio.charset.StandardCharsets.UTF_8).length.toLong)
      require(bytes <= MaxWktBytes, "sampling WKT payload exceeds 1 MB")
      val geometry = try reader.read(wkt) catch {
        case error: Exception => throw new IllegalArgumentException(s"sampling region $index has invalid WKT", error)
      }
      val kind = geometry.getGeometryType
      require(Set("Point", "MultiPoint", "Polygon", "MultiPolygon")(kind),
        s"sampling region $index must be Point, MultiPoint, Polygon or MultiPolygon")
      require(!geometry.isEmpty && geometry.isValid, s"sampling region $index must be nonempty and topologically valid")
      positions = Math.addExact(positions, geometry.getNumPoints.toLong)
      require(positions <= MaxPositions, s"sampling regions exceed the $MaxPositions-coordinate limit")
      validatePlanarWgs84(geometry, index)
      val projected = projectGeometry(geometry, toSource)
      require(!projected.isEmpty && projected.isValid,
        s"sampling region $index is invalid after source-CRS reprojection")
      result += projected
      index += 1
    }
    result.result()
  }

  /** Attach stable original indices and precompute point-to-cell selection, including MultiPoint deduplication. */
  def prepareFeatures(geometries: Seq[Geometry], grid: Grid): Vector[FeatureGeometry] =
    geometries.zipWithIndex.map { case (geometry, index) =>
      val points = geometry.getGeometryType match {
        case "Point" | "MultiPoint" =>
          val cells = Vector.newBuilder[Cell]
          val seen = mutable.HashSet.empty[Cell]
          var part = 0
          while (part < geometry.getNumGeometries) {
            val point = geometry.getGeometryN(part).getCoordinate
            grid.cellForPoint(point.x, point.y).foreach { cell => if (seen.add(cell)) cells += cell }
            part += 1
          }
          cells.result().sortBy(cell => (cell.row, cell.col))
        case "Polygon" | "MultiPolygon" => Vector.empty
        case other => throw new IllegalArgumentException(s"unsupported sampling geometry type: $other")
      }
      FeatureGeometry(index, geometry, points)
    }.toVector

  /** Closed envelope overlap intentionally keeps point-on-tile-edge candidates for floor selection. */
  def tileMayIntersect(key: SpatialKey, grid: Grid, features: Seq[FeatureGeometry]): Boolean = {
    require(key != null && key.col >= 0 && key.row >= 0,
      "sampling tile key must be nonnegative")
    val firstCol = Math.multiplyExact(key.col.toLong, grid.tileCols.toLong)
    val firstRow = Math.multiplyExact(key.row.toLong, grid.tileRows.toLong)
    require(firstCol + grid.tileCols <= grid.columns && firstRow + grid.tileRows <= grid.rows,
      "sampling tile key lies outside the finite grid")
    val tileBounds = new Envelope(
      grid.xmin + firstCol.toDouble * grid.cellWidth,
      grid.xmin + (firstCol + grid.tileCols).toDouble * grid.cellWidth,
      grid.ymax - (firstRow + grid.tileRows).toDouble * grid.cellHeight,
      grid.ymax - firstRow.toDouble * grid.cellHeight)
    features.exists(_.geometry.getEnvelopeInternal.intersects(tileBounds))
  }

  /**
    * Sample one real GeoTrellis tile. Rows are in global layout coordinates. The caller supplies
    * the source-to-WGS84 cell-center transform so this pure tile kernel needs no Spark context.
    */
  def sampleTile(
    tile: MultibandTile,
    key: SpatialKey,
    grid: Grid,
    features: Seq[FeatureGeometry],
    nativeToWgs84: (Double, Double) => (Double, Double)
  ): Vector[SampleRow] = {
    require(tile != null && key != null && grid != null && features != null && nativeToWgs84 != null,
      "sampling tile arguments must be present")
    require(tile.cols == grid.tileCols && tile.rows == grid.tileRows && tile.bandCount >= 1 && tile.bandCount <= 64,
      "sampling tile dimensions or band count do not match metadata")
    val firstCol = Math.multiplyExact(key.col.toLong, tile.cols.toLong)
    val firstRow = Math.multiplyExact(key.row.toLong, tile.rows.toLong)
    require(key.col >= 0 && key.row >= 0 && firstCol + tile.cols <= grid.columns && firstRow + tile.rows <= grid.rows,
      "sampling tile key lies outside the finite grid")
    require(features.length <= MaxFeatures && features.indices.forall(i => features(i).index >= 0),
      "sampling feature set exceeds its bounded contract")
    val bands = Array.tabulate(tile.bandCount)(index => tile.band(index).convert(DoubleConstantNoDataCellType))
    val output = mutable.ArrayBuffer.empty[SampleRow]
    val centers = mutable.HashMap.empty[Cell, (Double, Double)]

    def emit(feature: FeatureGeometry, localRow: Int, localCol: Int): Unit = {
      val globalRow = firstRow + localRow
      val globalCol = firstCol + localCol
      val values = new Array[Double](bands.length)
      var hasNoData = false
      var band = 0
      while (band < bands.length) {
        val value = bands(band).getDouble(localCol, localRow)
        require(value.isNaN || value.isFinite, "sampled valid pixels must be finite")
        if (value.isNaN) hasNoData = true
        values(band) = value
        band += 1
      }
      if (!hasNoData) {
        val cell = Cell(globalRow, globalCol)
        val (nativeX, nativeY) = centers.getOrElseUpdate(cell, {
          val (x, y) = grid.center(globalRow, globalCol)
          val converted = nativeToWgs84(x, y)
          require(converted._1.isFinite && converted._2.isFinite &&
            converted._1 >= -180.0 && converted._1 <= 180.0 && converted._2 >= -90.0 && converted._2 <= 90.0,
            "sampled cell center did not transform to finite WGS84 coordinates")
          converted
        })
        output += SampleRow(feature.index, globalRow, globalCol, nativeX, nativeY, values.toVector)
        require(output.length <= MaxRows, s"sampling result exceeds the $MaxRows-row limit")
      }
    }

    features.foreach { feature =>
      feature.geometry.getGeometryType match {
        case "Point" | "MultiPoint" =>
          feature.pointCells.foreach { cell =>
            if (cell.row >= firstRow && cell.row < firstRow + tile.rows &&
              cell.col >= firstCol && cell.col < firstCol + tile.cols) {
              emit(feature, (cell.row - firstRow).toInt, (cell.col - firstCol).toInt)
            }
          }
        case "Polygon" | "MultiPolygon" =>
          val bounds = new Envelope(
            grid.xmin + firstCol.toDouble * grid.cellWidth,
            grid.xmin + (firstCol + tile.cols).toDouble * grid.cellWidth,
            grid.ymax - (firstRow + tile.rows).toDouble * grid.cellHeight,
            grid.ymax - firstRow.toDouble * grid.cellHeight)
          if (feature.geometry.getEnvelopeInternal.intersects(bounds)) {
            var row = 0
            while (row < tile.rows) {
              var col = 0
              while (col < tile.cols) {
                val globalRow = firstRow + row
                val globalCol = firstCol + col
                val left = grid.xmin + globalCol.toDouble * grid.cellWidth
                val right = left + grid.cellWidth
                val top = grid.ymax - globalRow.toDouble * grid.cellHeight
                val bottom = top - grid.cellHeight
                val cellPolygon = GeometryFactory.toGeometry(new Envelope(left, right, bottom, top))
                if (feature.geometry.intersects(cellPolygon) && feature.geometry.intersection(cellPolygon).getArea > 0.0)
                  emit(feature, row, col)
                col += 1
              }
              row += 1
            }
          }
        case other => throw new IllegalArgumentException(s"unsupported sampling geometry type: $other")
      }
    }
    output.toVector.sortBy(row => (row.feature, row.row, row.col))
  }

  /** JSON is a top-level array because every row has a fixed, string-free schema. */
  def rowsJson(rows: Seq[SampleRow]): String = {
    require(rows != null && rows.size <= MaxRows, s"sampling result exceeds the $MaxRows-row limit")
    val ordered = rows.sortBy(row => (row.feature, row.row, row.col))
    val out = new StringBuilder("[")
    var index = 0
    while (index < ordered.length) {
      if (index > 0) out.append(',')
      val row = ordered(index)
      out.append("{\"feature\":").append(row.feature)
        .append(",\"row\":").append(row.row)
        .append(",\"col\":").append(row.col)
        .append(",\"x\":").append(jsonNumber(row.x))
        .append(",\"y\":").append(jsonNumber(row.y))
        .append(",\"values\":[")
      var band = 0
      while (band < row.values.length) {
        if (band > 0) out.append(',')
        out.append(jsonNumber(row.values(band)))
        band += 1
      }
      out.append("]}")
      index += 1
    }
    out.append(']')
    val json = out.toString()
    require(json.getBytes(java.nio.charset.StandardCharsets.UTF_8).length <= MaxResponseBytes,
      "sampling response exceeds 1 MB")
    json
  }

  private def validatePlanarWgs84(geometry: Geometry, index: Int): Unit = {
    var hasExtraOrdinate = false
    geometry.apply(new CoordinateSequenceFilter {
      override def filter(sequence: org.locationtech.jts.geom.CoordinateSequence, coordinateIndex: Int): Unit = {
        var ordinate = 2
        while (ordinate < sequence.getDimension) {
          if (!sequence.getOrdinate(coordinateIndex, ordinate).isNaN) hasExtraOrdinate = true
          ordinate += 1
        }
      }
      override def isDone: Boolean = false
      override def isGeometryChanged: Boolean = false
    })
    require(!hasExtraOrdinate, s"sampling region $index must use planar 2D WGS84 coordinates")
    geometry.getCoordinates.foreach { coordinate =>
      require(coordinate.x.isFinite && coordinate.y.isFinite &&
        coordinate.x >= -180.0 && coordinate.x <= 180.0 &&
        coordinate.y >= -90.0 && coordinate.y <= 90.0,
        s"sampling region $index coordinates must be finite WGS84 longitude/latitude")
    }
  }

  private def projectGeometry(
    geometry: Geometry,
    transform: (Double, Double) => (Double, Double)
  ): Geometry = {
    val projected = geometry.copy()
    projected.apply(new CoordinateSequenceFilter {
      override def filter(sequence: org.locationtech.jts.geom.CoordinateSequence, coordinateIndex: Int): Unit = {
        val (x, y) = transform(sequence.getX(coordinateIndex), sequence.getY(coordinateIndex))
        require(x.isFinite && y.isFinite, "sampling geometry reprojection produced a non-finite coordinate")
        sequence.setOrdinate(coordinateIndex, 0, x)
        sequence.setOrdinate(coordinateIndex, 1, y)
      }
      override def isDone: Boolean = false
      override def isGeometryChanged: Boolean = true
    })
    projected.geometryChanged()
    projected
  }

  private def jsonNumber(value: Double): String = {
    require(value.isFinite, "sampling JSON numbers must be finite")
    java.lang.Double.toString(value)
  }
}
