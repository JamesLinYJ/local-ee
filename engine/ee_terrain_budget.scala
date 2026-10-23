package local.ee.reduce

/** Spark-free count and byte estimates for one-pixel four-connected terrain support. */
private[reduce] object LocalEeTerrainBudget {
  final case class Plan(
    keyCount: Long,
    tileCells: Long,
    bufferedCells: Long,
    maxTransformCalls: Long,
    transformResultObjects: Long,
    explicitArrayCount: Long,
    explicitArrayBytes: Long,
    perTileWork: Long,
    totalWork: Long
  ) extends Serializable

  val MaxSourceKeys = 100000L
  val MaxDecodedCells = 100000000L
  val MaxTileDecodedCells = 10000000L
  val MaxPerTileWork = 100000000L
  val MaxTerrainWork = 1000000000L

  // Per halo center charges six zero-initialized cache arrays, affine center construction,
  // one CRS transform, WGS84 validation, ECEF/trigonometric conversion, and cache writes.
  private val CoordinateCellWork = 64L
  // Per output cell charges the full input-validation scan, center/four-neighbor reads,
  // five cache lookups, local tangent-basis construction, displacement matrix and solve,
  // independently scaled central differences, and the selected numeric renderer.
  private val OutputWorkPerCell = 256L
  private val CoordinateBytesPerCell = 5L * 8L + 1L
  private val ArraysPerTile = 9L

  def plan(keyCount: Long, cols: Int, rows: Int): Plan = {
    require(keyCount > 0L && keyCount <= MaxSourceKeys,
      s"local_ee_terrain supports 1 to $MaxSourceKeys source tile keys")
    require(cols > 0 && rows > 0, "local_ee_terrain tile dimensions must be positive")
    val tileCells = Math.multiplyExact(cols.toLong, rows.toLong)
    require(tileCells <= MaxTileDecodedCells,
      s"local_ee_terrain tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    require(keyCount <= MaxDecodedCells / tileCells,
      s"local_ee_terrain exceeds the $MaxDecodedCells aggregate decoded-cell limit")
    require(1 < math.min(cols, rows),
      "local_ee_terrain one-pixel radius must be smaller than the smaller tile dimension")

    val bufferedCols = Math.addExact(cols.toLong, 2L)
    val bufferedRows = Math.addExact(rows.toLong, 2L)
    val bufferedCells = Math.multiplyExact(bufferedCols, bufferedRows)
    require(bufferedCells <= MaxTileDecodedCells,
      s"local_ee_terrain buffered tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    require(keyCount <= MaxDecodedCells / bufferedCells,
      s"local_ee_terrain exceeds the $MaxDecodedCells aggregate buffered-cell limit")

    val perTileWork = Math.addExact(
      Math.multiplyExact(tileCells, OutputWorkPerCell),
      Math.multiplyExact(bufferedCells, CoordinateCellWork))
    require(perTileWork <= MaxPerTileWork,
      s"local_ee_terrain exceeds the $MaxPerTileWork per-tile work limit")
    val totalWork = Math.multiplyExact(perTileWork, keyCount)
    require(totalWork <= MaxTerrainWork,
      s"local_ee_terrain exceeds the $MaxTerrainWork total transform-and-kernel work limit")

    val transformCalls = Math.multiplyExact(bufferedCells, keyCount)
    // Transform(crs, LatLng) returns one specialized binary64 coordinate tuple per point.
    val transformObjects = transformCalls
    val arrayCount = Math.multiplyExact(ArraysPerTile, keyCount)
    val tileOutputBytes = Math.multiplyExact(tileCells, 8L)
    val coordinateBytes = Math.multiplyExact(bufferedCells, CoordinateBytesPerCell)
    // Includes the 12-value metric/gradient scratch array and the one-element tile wrapper array.
    val explicitArrayBytes = Math.multiplyExact(
      Math.addExact(Math.addExact(tileOutputBytes, coordinateBytes), 104L), keyCount)
    Plan(keyCount, tileCells, bufferedCells, transformCalls, transformObjects,
      arrayCount, explicitArrayBytes,
      perTileWork, totalWork)
  }
}
