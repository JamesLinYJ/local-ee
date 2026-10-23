package local.ee.reduce

/** Conservative preflight for the distributed Boolean-fragment distance path. */
private[reduce] object LocalEeFastDistanceBudget {
  final case class Plan(
    keyCount: Long,
    cols: Int,
    rows: Int,
    neighborhood: Int,
    windowCols: Int,
    windowRows: Int,
    windowCells: Long,
    lineScratchCells: Long,
    hopCols: Int,
    hopRows: Int,
    candidateFanout: Long,
    maxFragmentsPerTile: Long,
    fragmentCellsPerTile: Long,
    aggregateSourceCells: Long,
    aggregateConversionCells: Long,
    aggregateTargetCells: Long,
    aggregateOutputCells: Long,
    aggregateWindowCells: Long,
    aggregateFragmentCells: Long,
    aggregateScratchCells: Long,
    aggregateDecodedCells: Long,
    perTileDecodedCells: Long,
    perTileWork: Long,
    totalWork: Long
  ) extends Serializable {
    val maxFragmentsPerGroup: Long = maxFragmentsPerTile
    val maxFragmentCellsPerGroup: Long = windowCells
  }

  val MaxSourceKeys = 100000L
  val MaxDecodedCells = 100000000L
  val MaxTileDecodedCells = 10000000L
  val MaxPerTileWork = 100000000L
  val MaxAggregateWork = 1000000000L

  // Counts cover all live raster-shaped arrays, the Long output transform, its
  // line-envelope/column scratch, and worst-case copies sent through the shuffle.
  // Work units cover repeated fragment scans, assembly, the exact linear transform,
  // cropping, and candidate-key probes.
  private val FragmentScanAndCopyPerCell = 2L
  private val TransformWorkPerCell = 64L

  def plan(
    keyCount: Long, cols: Int, rows: Int, spec: LocalEeFastDistanceSpec.Value
  ): Plan = {
    require(keyCount > 0L && keyCount <= MaxSourceKeys,
      s"local_ee_fast_distance supports 1 to $MaxSourceKeys source tile keys")
    require(cols > 0 && rows > 0, "local_ee_fast_distance tile dimensions must be positive")

    val tileCells = Math.multiplyExact(cols.toLong, rows.toLong)
    require(tileCells <= MaxTileDecodedCells,
      s"local_ee_fast_distance tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    val aggregateSourceCells = Math.multiplyExact(keyCount, tileCells)
    require(aggregateSourceCells <= MaxDecodedCells,
      s"local_ee_fast_distance exceeds the $MaxDecodedCells aggregate source-cell limit")

    val halo = spec.neighborhood.toLong
    val bufferColsLong = Math.addExact(cols.toLong, Math.multiplyExact(2L, halo))
    val bufferRowsLong = Math.addExact(rows.toLong, Math.multiplyExact(2L, halo))
    require(bufferColsLong <= Int.MaxValue && bufferRowsLong <= Int.MaxValue,
      "local_ee_fast_distance halo dimensions exceed the supported integer range")
    val windowCols = bufferColsLong.toInt
    val windowRows = bufferRowsLong.toInt
    val windowCells = Math.multiplyExact(bufferColsLong, bufferRowsLong)
    require(windowCells <= MaxTileDecodedCells,
      s"local_ee_fast_distance buffered tile exceeds the $MaxTileDecodedCells decoded-cell limit")
    val aggregateWindowCells = Math.multiplyExact(keyCount, windowCells)
    require(aggregateWindowCells <= MaxDecodedCells,
      s"local_ee_fast_distance exceeds the $MaxDecodedCells aggregate buffered-cell limit")

    val hopCols = ceilDiv(halo, cols.toLong)
    val hopRows = ceilDiv(halo, rows.toLong)
    val candidateFanout = Math.multiplyExact(
      Math.addExact(Math.multiplyExact(2L, hopCols), 1L),
      Math.addExact(Math.multiplyExact(2L, hopRows), 1L))
    val maxFragmentsPerTile = math.min(candidateFanout, keyCount)
    val fragmentCellsPerTile = Math.multiplyExact(tileCells, maxFragmentsPerTile)
    require(fragmentCellsPerTile <= MaxTileDecodedCells,
      s"local_ee_fast_distance source fragments exceed the $MaxTileDecodedCells per-tile decoded-cell limit")
    val aggregateFragmentCells = Math.multiplyExact(keyCount, fragmentCellsPerTile)
    require(aggregateFragmentCells <= MaxDecodedCells,
      s"local_ee_fast_distance exceeds the $MaxDecodedCells aggregate fragment-cell limit")

    val aggregateTargetCells = aggregateSourceCells
    val aggregateConversionCells = aggregateSourceCells
    val aggregateOutputCells = aggregateSourceCells
    val lineScratchCells = Math.addExact(
      Math.multiplyExact(2L, math.max(bufferColsLong, bufferRowsLong)), bufferRowsLong)
    val aggregateScratchCells = Math.multiplyExact(keyCount,
      Math.addExact(windowCells, lineScratchCells))
    val aggregateDecodedCells = Math.addExact(
      Math.addExact(Math.addExact(Math.addExact(aggregateSourceCells, aggregateConversionCells), aggregateTargetCells),
        aggregateOutputCells),
      Math.addExact(Math.addExact(aggregateWindowCells, aggregateFragmentCells), aggregateScratchCells))
    require(aggregateDecodedCells <= MaxDecodedCells,
      s"local_ee_fast_distance allocations exceed the $MaxDecodedCells aggregate decoded-cell limit")

    val perTileWorkingCells = Math.addExact(
      Math.addExact(Math.addExact(Math.multiplyExact(4L, tileCells), Math.multiplyExact(2L, windowCells)),
        fragmentCellsPerTile), lineScratchCells)
    require(perTileWorkingCells <= MaxTileDecodedCells,
      s"local_ee_fast_distance working tile exceeds the $MaxTileDecodedCells decoded-cell limit")

    val fragmentWork = Math.multiplyExact(FragmentScanAndCopyPerCell, fragmentCellsPerTile)
    val perTileWork = Math.addExact(
      Math.addExact(Math.multiplyExact(3L, tileCells), candidateFanout),
      Math.addExact(fragmentWork,
        Math.addExact(windowCells, Math.addExact(fragmentCellsPerTile,
          Math.multiplyExact(TransformWorkPerCell, windowCells)))))
    require(perTileWork <= MaxPerTileWork,
      s"local_ee_fast_distance exceeds the $MaxPerTileWork per-tile work limit ($perTileWork)")
    val totalWork = Math.addExact(Math.multiplyExact(keyCount, perTileWork), keyCount)
    require(totalWork <= MaxAggregateWork,
      s"local_ee_fast_distance exceeds the $MaxAggregateWork aggregate work limit ($totalWork)")

    Plan(keyCount, cols, rows, spec.neighborhood, windowCols, windowRows, windowCells, lineScratchCells,
      hopCols.toInt, hopRows.toInt, candidateFanout, maxFragmentsPerTile, fragmentCellsPerTile,
      aggregateSourceCells, aggregateConversionCells, aggregateTargetCells, aggregateOutputCells,
      aggregateWindowCells, aggregateFragmentCells,
      aggregateScratchCells, aggregateDecodedCells, perTileWorkingCells, perTileWork, totalWork)
  }

  private def ceilDiv(value: Long, divisor: Long): Long =
    Math.floorDiv(Math.addExact(value, divisor - 1L), divisor)
}
