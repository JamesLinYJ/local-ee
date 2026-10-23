package local.ee.reduce

/** Conservative work and decoded-cell limits for the bounded distance transform. */
private[reduce] object LocalEeDistanceBudget {
  final case class Plan(
    keyCount: Long, halo: Int, bufferedCells: Long, offsetCount: Int, perTileWork: Long
  ) extends Serializable

  val MaxSourceKeys = 100000L
  val MaxDecodedCells = 100000000L
  val MaxTileDecodedCells = 10000000L
  val MaxDistanceWork = 1000000000L
  val MaxPerTileWork = 100000000L
  private val ExactRadiusSetupWork = 4096L

  def plan(keyCount: Long, cols: Int, rows: Int, spec: LocalEeDistanceSpec.Value): Plan = {
    require(keyCount > 0L && keyCount <= MaxSourceKeys,
      s"local_ee_distance supports 1 to $MaxSourceKeys source tile keys")
    require(cols > 0 && rows > 0, "local_ee_distance tile dimensions must be positive")
    val tileCells = Math.multiplyExact(cols.toLong, rows.toLong)
    require(tileCells <= MaxTileDecodedCells,
      s"local_ee_distance tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    require(keyCount <= MaxDecodedCells / tileCells,
      s"local_ee_distance exceeds the $MaxDecodedCells aggregate decoded-cell limit")

    val halo = spec.halo
    require(halo == 0 || halo < math.min(cols, rows),
      "local_ee_distance positive halo must be smaller than the smaller tile dimension")
    val bufferCols = Math.addExact(cols.toLong, Math.multiplyExact(2L, halo.toLong))
    val bufferRows = Math.addExact(rows.toLong, Math.multiplyExact(2L, halo.toLong))
    val bufferedCells = Math.multiplyExact(bufferCols, bufferRows)
    require(bufferedCells <= MaxTileDecodedCells,
      s"local_ee_distance buffered tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    require(bufferedCells <= MaxDecodedCells / keyCount,
      s"local_ee_distance exceeds the $MaxDecodedCells aggregate buffered-cell limit")

    val offsets = spec.offsets.length.toLong
    val planCells = Math.multiplyExact(Math.addExact(Math.multiplyExact(2L, halo.toLong), 1L),
      Math.addExact(Math.multiplyExact(2L, halo.toLong), 1L))
    val sortBits = if (offsets <= 1L) 0L else 64L - java.lang.Long.numberOfLeadingZeros(offsets - 1L)
    // Cover square enumeration, exact radius comparisons and deterministic offset ordering.
    val offsetPlanWork = Math.addExact(ExactRadiusSetupWork, Math.addExact(Math.multiplyExact(planCells, 8L),
      Math.multiplyExact(offsets, sortBits + 1L))
    )
    // checked.count() validates once; the uncached halo action recomputes that
    // map. Charge both full read/copy passes plus output center checks/writes.
    // Upstream graph execution, IO and Spark retries are separate job limits.
    val copyAndScanWork = Math.multiplyExact(tileCells, Math.addExact(offsets, 6L))
    val perTileWork = Math.addExact(Math.addExact(offsetPlanWork, copyAndScanWork), bufferedCells)
    require(perTileWork <= MaxPerTileWork,
      s"local_ee_distance exceeds the $MaxPerTileWork per-tile work limit ($perTileWork)")
    require(perTileWork <= MaxDistanceWork / keyCount,
      s"local_ee_distance exceeds the $MaxDistanceWork total work limit")
    Plan(keyCount, halo, bufferedCells, spec.offsets.length, perTileWork)
  }
}
