package local.ee.reduce

import geotrellis.proj4.{LatLng, Transform}

/** Pixel-center grid and cached WGS84 ECEF coordinates for the local tangent-chord policy. */
private[reduce] object LocalEeTerrainMetric {
  final case class Grid(
    xmin: Double, ymax: Double, cellWidth: Double, cellHeight: Double,
    columns: Long, rows: Long
  ) extends Serializable {
    require(Seq(xmin, ymax, cellWidth, cellHeight).forall(_.isFinite) &&
      cellWidth > 0.0d && cellHeight > 0.0d && columns > 0L && rows > 0L,
      "local_ee_terrain source layout must have finite positive cell spacing")
    require(columns <= (1L << 52) && rows <= (1L << 52),
      "local_ee_terrain pixel-center half-cell coordinates exceed exact binary64 indexing")
  }

  private val SemiMajor = 6378137.0d
  private val Flattening = 1.0d / 298.257223563d
  private val EccentricitySquared = Flattening * (2.0d - Flattening)
  private val PolarCosineMinimum = 1.0e-12d
  private val MinChordMeters = math.ulp(SemiMajor)

  def fromCrs(crs: geotrellis.proj4.CRS): (Double, Double) => (Double, Double) = {
    require(crs != null, "local_ee_terrain source CRS is required")
    val transform = Transform(crs, LatLng)
    (x: Double, y: Double) => transform(x, y)
  }

  /** Stores only the one-pixel halo; each required source-grid center is projected once per tile. */
  final class CoordinateCache(
    grid: Grid, tileCol: Int, tileRow: Int, tileCols: Int, tileRows: Int,
    nativeToWgs84: (Double, Double) => (Double, Double)
  ) {
    require(grid != null && nativeToWgs84 != null && tileCols > 0 && tileRows > 0,
      "local_ee_terrain coordinate cache arguments are required")
    private val cacheCols = Math.addExact(tileCols, 2)
    private val cacheRows = Math.addExact(tileRows, 2)
    private val cacheSize = Math.multiplyExact(cacheCols, cacheRows)
    private val tileOriginCol = Math.multiplyExact(tileCol.toLong, tileCols.toLong)
    private val tileOriginRow = Math.multiplyExact(tileRow.toLong, tileRows.toLong)
    private val firstCol = Math.subtractExact(tileOriginCol, 1L)
    private val firstRow = Math.subtractExact(tileOriginRow, 1L)
    private val ecefX = new Array[Double](cacheSize)
    private val ecefY = new Array[Double](cacheSize)
    private val ecefZ = new Array[Double](cacheSize)
    private val longitude = new Array[Double](cacheSize)
    private val latitude = new Array[Double](cacheSize)
    private val loaded = new Array[Byte](cacheSize)
    private var projectedCenters = 0L

    def transformCalls: Long = projectedCenters
    def allocatedBytes: Long = Math.multiplyExact(cacheSize.toLong, 41L)
    def allocatedArrays: Int = 6

    /** Fill east/north displacement coefficients for east-west and south-north differences. */
    def matrixAt(globalCol: Long, globalRow: Long, matrix: Array[Double]): Unit = {
      require(matrix != null && matrix.length >= 4,
        "local_ee_terrain metric scratch must contain four coefficients")
      val eastIndex = point(Math.addExact(globalCol, 1L), globalRow)
      val westIndex = point(Math.subtractExact(globalCol, 1L), globalRow)
      val northIndex = point(globalCol, Math.subtractExact(globalRow, 1L))
      val southIndex = point(globalCol, Math.addExact(globalRow, 1L))
      val centerIndex = point(globalCol, globalRow)
      val lon = longitude(centerIndex)
      val lat = latitude(centerIndex)
      val sinLon = math.sin(lon)
      val cosLon = math.cos(lon)
      val sinLat = math.sin(lat)
      val cosLat = math.cos(lat)

      val ewX = ecefX(eastIndex) - ecefX(westIndex)
      val ewY = ecefY(eastIndex) - ecefY(westIndex)
      val ewZ = ecefZ(eastIndex) - ecefZ(westIndex)
      val snX = ecefX(southIndex) - ecefX(northIndex)
      val snY = ecefY(southIndex) - ecefY(northIndex)
      val snZ = ecefZ(southIndex) - ecefZ(northIndex)
      val eastX = -sinLon
      val eastY = cosLon
      val northX = -sinLat * cosLon
      val northY = -sinLat * sinLon
      matrix(0) = ewX * eastX + ewY * eastY
      matrix(1) = ewX * northX + ewY * northY + ewZ * cosLat
      matrix(2) = snX * eastX + snY * eastY
      matrix(3) = snX * northX + snY * northY + snZ * cosLat
    }

    private def point(col: Long, row: Long): Int = {
      require(col >= 0L && col < grid.columns && row >= 0L && row < grid.rows,
        "local_ee_terrain metric requested a center outside the actual layout")
      val localCol = Math.toIntExact(Math.subtractExact(col, firstCol))
      val localRow = Math.toIntExact(Math.subtractExact(row, firstRow))
      require(localCol >= 0 && localCol < cacheCols && localRow >= 0 && localRow < cacheRows,
        "local_ee_terrain one-pixel coordinate halo is incomplete")
      val index = Math.addExact(Math.multiplyExact(localRow, cacheCols), localCol)
      if (loaded(index) == 0) project(col, row, index)
      index
    }

    private def project(col: Long, row: Long, index: Int): Unit = {
      val x = grid.xmin + (col.toDouble + 0.5d) * grid.cellWidth
      val y = grid.ymax - (row.toDouble + 0.5d) * grid.cellHeight
      require(x.isFinite && y.isFinite,
        "local_ee_terrain source pixel center is not representable")
      val converted = try nativeToWgs84(x, y) catch {
        case error: Exception =>
          throw new IllegalArgumentException("local_ee_terrain source pixel center cannot transform to WGS84", error)
      }
      val lonDegrees = converted._1
      val latDegrees = converted._2
      require(lonDegrees.isFinite && latDegrees.isFinite &&
        lonDegrees >= -180.0d && lonDegrees <= 180.0d &&
        latDegrees > -90.0d && latDegrees < 90.0d,
        "local_ee_terrain source pixel center did not transform to valid WGS84 coordinates")
      val lon = math.toRadians(lonDegrees)
      val lat = math.toRadians(latDegrees)
      val sinLat = math.sin(lat)
      val cosLat = math.cos(lat)
      require(math.abs(cosLat) > PolarCosineMinimum,
        "local_ee_terrain local compass basis is undefined at the poles")
      val sinLon = math.sin(lon)
      val cosLon = math.cos(lon)
      val primeVertical = SemiMajor / math.sqrt(1.0d - EccentricitySquared * sinLat * sinLat)
      val xEcef = primeVertical * cosLat * cosLon
      val yEcef = primeVertical * cosLat * sinLon
      val zEcef = primeVertical * (1.0d - EccentricitySquared) * sinLat
      require(xEcef.isFinite && yEcef.isFinite && zEcef.isFinite,
        "local_ee_terrain WGS84 ECEF coordinate is non-finite")
      ecefX(index) = xEcef
      ecefY(index) = yEcef
      ecefZ(index) = zEcef
      longitude(index) = lon
      latitude(index) = lat
      loaded(index) = 1
      projectedCenters = Math.addExact(projectedCenters, 1L)
    }
  }

  /** Reject collapsed or nearly singular local coordinate bases before deriving any slope. */
  def validateMatrix(matrix: Array[Double]): Double = {
    require(matrix != null && matrix.length >= 4 &&
      matrix(0).isFinite && matrix(1).isFinite && matrix(2).isFinite && matrix(3).isFinite,
      "local_ee_terrain local metric contains a non-finite displacement")
    val scale = math.max(math.max(math.abs(matrix(0)), math.abs(matrix(1))),
      math.max(math.abs(matrix(2)), math.abs(matrix(3))))
    require(scale >= MinChordMeters,
      "local_ee_terrain source pixel spacing is below resolvable WGS84 ECEF precision")
    val a = matrix(0) / scale
    val b = matrix(1) / scale
    val c = matrix(2) / scale
    val d = matrix(3) / scale
    val determinant = a * d - b * c
    require(determinant.isFinite && math.abs(determinant) > 1.0e-12d,
      "local_ee_terrain local east/north metric is degenerate or singular")
    scale
  }
}
