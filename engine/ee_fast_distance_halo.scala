package local.ee.reduce

import geotrellis.layer.{SpaceTimeKey, SpatialKey}
import geotrellis.raster.{DoubleConstantNoDataCellType, IntArrayTile, IntConstantNoDataCellType, Tile}

/** Crops observed tiles into bounded, possibly multi-hop distance windows. */
private[reduce] object LocalEeFastDistanceHalo {
  final case class Key(col: Int, row: Int, instant: Long, temporal: Boolean) extends Serializable

  final case class SpatialBounds(minCol: Int, minRow: Int, maxCol: Int, maxRow: Int) extends Serializable {
    require(minCol <= maxCol && minRow <= maxRow, "fast distance spatial key bounds must be ordered")
  }

  sealed trait Piece extends Serializable
  case object Center extends Piece
  final case class Fragment(
    offsetCol: Int, offsetRow: Int, width: Int, height: Int, values: Array[Boolean]
  ) extends Piece

  def fromAny(value: Any, kind: String): Key = (kind, value) match {
    case ("spatial", key: SpatialKey) => Key(key.col, key.row, 0L, temporal = false)
    case ("temporal", key: SpaceTimeKey) => Key(key.col, key.row, key.instant, temporal = true)
    case _ => throw new IllegalArgumentException("fast distance key type does not match raster metadata")
  }

  def toAny(key: Key): Any =
    if (key.temporal) SpaceTimeKey(key.col, key.row, key.instant)
    else SpatialKey(key.col, key.row)

  /** Converts only one actual tile; NaN is masked and every finite nonzero value is a target. */
  def targetsFromTile(tile: Tile, cols: Int, rows: Int): Array[Boolean] = {
    require(tile != null && cols > 0 && rows > 0 && tile.cols == cols && tile.rows == rows,
      "fast distance source tile dimensions do not match metadata")
    val cells = Math.multiplyExact(cols.toLong, rows.toLong)
    require(cells <= LocalEeFastDistanceBudget.MaxTileDecodedCells,
      "fast distance source tile exceeds the decoded-cell limit")
    val doubleTile = tile.convert(DoubleConstantNoDataCellType)
    val targets = new Array[Boolean](cells.toInt)
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        val value = doubleTile.getDouble(col, row)
        require(value.isNaN || value.isFinite, "fast distance source pixels must be finite or NoData")
        targets(row * cols + col) = !value.isNaN && value != 0.0d
        col += 1
      }
      row += 1
    }
    targets
  }

  /**
    * Emits a center marker and true-target crops only for observed centers.
    * Coordinates are global pixel coordinates; timestamp is copied unchanged.
    */
  def emitFragments(
    sourceKey: Key,
    sourceTargets: Array[Boolean],
    centers: Set[Key],
    cols: Int,
    rows: Int,
    bounds: SpatialBounds,
    spec: LocalEeFastDistanceSpec.Value,
    plan: LocalEeFastDistanceBudget.Plan
  ): Iterator[(Key, Piece)] = {
    require(sourceTargets != null && centers != null && sourceTargets.length.toLong ==
      Math.multiplyExact(cols.toLong, rows.toLong), "fast distance target tile has the wrong shape")
    require(cols == plan.cols && rows == plan.rows && spec.neighborhood == plan.neighborhood,
      "fast distance fragment plan does not match tile dimensions and spec")
    require(centers.size.toLong == plan.keyCount && centers.contains(sourceKey),
      "fast distance source key is not in the bounded observed-center set")
    require(sourceKey.col >= bounds.minCol && sourceKey.col <= bounds.maxCol &&
      sourceKey.row >= bounds.minRow && sourceKey.row <= bounds.maxRow,
      "fast distance source key lies outside its bounded spatial extent")

    val firstCol = math.max(bounds.minCol.toLong, sourceKey.col.toLong - plan.hopCols.toLong)
    val lastCol = math.min(bounds.maxCol.toLong, sourceKey.col.toLong + plan.hopCols.toLong)
    val firstRow = math.max(bounds.minRow.toLong, sourceKey.row.toLong - plan.hopRows.toLong)
    val lastRow = math.min(bounds.maxRow.toLong, sourceKey.row.toLong + plan.hopRows.toLong)
    val sourceLeft = Math.multiplyExact(sourceKey.col.toLong, cols.toLong)
    val sourceTop = Math.multiplyExact(sourceKey.row.toLong, rows.toLong)
    val sourceRight = Math.addExact(sourceLeft, cols.toLong)
    val sourceBottom = Math.addExact(sourceTop, rows.toLong)

    new Iterator[(Key, Piece)] {
      private var markerPending = true
      private var nextCol = firstCol
      private var nextRow = firstRow
      private var candidatesSeen = 0L
      private var fragmentCount = 0L
      private var scannedFragmentCells = 0L
      private var copiedFragmentCells = 0L
      private var ready: Option[(Key, Piece)] = None

      override def hasNext: Boolean = {
        if (markerPending || ready.nonEmpty) true
        else {
          seekNext()
          ready.nonEmpty
        }
      }

      override def next(): (Key, Piece) = {
        if (markerPending) {
          markerPending = false
          sourceKey -> Center
        } else {
          if (!hasNext) throw new NoSuchElementException("next on empty fast distance fragment iterator")
          val result = ready.get
          ready = None
          result
        }
      }

      private def seekNext(): Unit = {
        while (ready.isEmpty && nextRow <= lastRow) {
          val col = nextCol
          val row = nextRow
          if (nextCol == lastCol) {
            nextCol = firstCol
            nextRow += 1L
          } else nextCol += 1L

          candidatesSeen = Math.addExact(candidatesSeen, 1L)
          require(candidatesSeen <= plan.candidateFanout,
            "fast distance candidate-key iterator exceeded its preflight cap")
          val destination = Key(col.toInt, row.toInt, sourceKey.instant, sourceKey.temporal)
          if (centers.contains(destination)) {
            makeFragment(destination).foreach(piece => ready = Some(destination -> piece))
          }
        }
      }

      private def makeFragment(destination: Key): Option[Fragment] = {
        val destinationLeft = Math.subtractExact(
          Math.multiplyExact(destination.col.toLong, cols.toLong), spec.neighborhood.toLong)
        val destinationTop = Math.subtractExact(
          Math.multiplyExact(destination.row.toLong, rows.toLong), spec.neighborhood.toLong)
        val destinationRight = Math.addExact(destinationLeft, plan.windowCols.toLong)
        val destinationBottom = Math.addExact(destinationTop, plan.windowRows.toLong)
        val left = math.max(sourceLeft, destinationLeft)
        val top = math.max(sourceTop, destinationTop)
        val right = math.min(sourceRight, destinationRight)
        val bottom = math.min(sourceBottom, destinationBottom)
        if (left >= right || top >= bottom) None
        else {
          val width = Math.toIntExact(right - left)
          val height = Math.toIntExact(bottom - top)
          val area = Math.multiplyExact(width.toLong, height.toLong)
          scannedFragmentCells = Math.addExact(scannedFragmentCells, area)
          require(scannedFragmentCells <= plan.fragmentCellsPerTile,
            "fast distance fragment scan exceeded its preflight cell cap")

          val sourceCol = Math.toIntExact(left - sourceLeft)
          val sourceRow = Math.toIntExact(top - sourceTop)
          var hasTarget = false
          var y = 0
          while (y < height && !hasTarget) {
            var x = 0
            while (x < width && !hasTarget) {
              hasTarget = sourceTargets((sourceRow + y) * cols + sourceCol + x)
              x += 1
            }
            y += 1
          }
          if (!hasTarget) None
          else {
            require(fragmentCount < plan.maxFragmentsPerTile,
              "fast distance fragment iterator exceeded its preflight fragment cap")
            copiedFragmentCells = Math.addExact(copiedFragmentCells, area)
            require(copiedFragmentCells <= plan.fragmentCellsPerTile,
              "fast distance fragment copy exceeded its preflight cell cap")
            fragmentCount += 1L
            val values = new Array[Boolean](area.toInt)
            y = 0
            while (y < height) {
              var x = 0
              while (x < width) {
                values(y * width + x) = sourceTargets((sourceRow + y) * cols + sourceCol + x)
                x += 1
              }
              y += 1
            }
            val offsetCol = Math.toIntExact(left - destinationLeft)
            val offsetRow = Math.toIntExact(top - destinationTop)
            Some(Fragment(offsetCol, offsetRow, width, height, values))
          }
        }
      }
    }
  }

  /** Drops markerless ghost groups, assembles a bounded mask, and returns a saturated Int32 tile. */
  def assemble(
    pieces: Iterable[Piece],
    cols: Int,
    rows: Int,
    spec: LocalEeFastDistanceSpec.Value,
    plan: LocalEeFastDistanceBudget.Plan
  ): Option[Tile] = {
    require(pieces != null && cols == plan.cols && rows == plan.rows &&
      spec.neighborhood == plan.neighborhood, "fast distance assembly plan does not match its inputs")
    var centers = 0
    var fragments = 0L
    var fragmentCells = 0L
    val firstPass = pieces.iterator
    while (firstPass.hasNext) {
      firstPass.next() match {
        case Center =>
          centers += 1
          require(centers <= 1, "fast distance group contains duplicate center markers")
        case fragment: Fragment =>
          validateFragment(fragment, plan)
          fragments = Math.addExact(fragments, 1L)
          fragmentCells = Math.addExact(fragmentCells,
            Math.multiplyExact(fragment.width.toLong, fragment.height.toLong))
          require(fragments <= plan.maxFragmentsPerGroup,
            "fast distance group exceeds its preflight fragment-count cap")
          require(fragmentCells <= plan.maxFragmentCellsPerGroup,
            "fast distance group exceeds its preflight fragment-cell cap")
      }
    }
    if (centers == 0) return None

    val targets = new Array[Boolean](plan.windowCells.toInt)
    val secondPass = pieces.iterator
    while (secondPass.hasNext) secondPass.next() match {
      case Center => ()
      case fragment: Fragment =>
        var row = 0
        while (row < fragment.height) {
          var col = 0
          while (col < fragment.width) {
            if (fragment.values(row * fragment.width + col)) {
              val target = (fragment.offsetRow + row) * plan.windowCols + fragment.offsetCol + col
              targets(target) = true
            }
            col += 1
          }
          row += 1
        }
    }

    val distances = LocalEeFastDistanceTransform.apply(
      targets, plan.windowCols, plan.windowRows, spec.metric)
    require(distances.length == plan.windowCells.toInt,
      "fast distance transform returned an unexpected number of cells")
    val output = new Array[Int](Math.multiplyExact(cols.toLong, rows.toLong).toInt)
    var row = 0
    while (row < rows) {
      var col = 0
      while (col < cols) {
        val distance = distances((row + spec.neighborhood) * plan.windowCols + col + spec.neighborhood)
        require(distance >= 0L, "fast distance transform returned a negative distance")
        output(row * cols + col) = if (distance == LocalEeFastDistanceTransform.NoTargetDistance ||
          distance > spec.cap.toLong) spec.cap else distance.toInt
        col += 1
      }
      row += 1
    }
    Some(IntArrayTile(output, cols, rows, IntConstantNoDataCellType))
  }

  private def validateFragment(fragment: Fragment, plan: LocalEeFastDistanceBudget.Plan): Unit = {
    require(fragment.values != null && fragment.width > 0 && fragment.height > 0 &&
      fragment.offsetCol >= 0 && fragment.offsetRow >= 0 &&
      fragment.offsetCol.toLong + fragment.width.toLong <= plan.windowCols.toLong &&
      fragment.offsetRow.toLong + fragment.height.toLong <= plan.windowRows.toLong &&
      fragment.values.length.toLong == Math.multiplyExact(fragment.width.toLong, fragment.height.toLong),
      "fast distance fragment has invalid dimensions or offsets")
  }
}
