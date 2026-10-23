package local.ee.reduce

/** Exact finite-grid distance transforms for a binary target mask.
  *
  * The caller defines target validity and converts each valid nonzero source
  * cell to `true`. Distances are returned in row-major order as squared pixel
  * distances for `squared_euclidean`, or ordinary pixel distances for the
  * other metrics. `NoTargetDistance` marks every cell when the mask has no
  * targets.
  */
private[reduce] object LocalEeFastDistanceTransform {
  private val MaxCells = 10000000L
  val NoTargetDistance: Long = LocalEeFastDistanceTransformEnvelope.NoTargetDistance

  def apply(
    targets: Array[Boolean],
    width: Int,
    height: Int,
    metric: String
  ): Array[Long] = metric match {
    case "squared_euclidean" => squaredEuclidean(targets, width, height)
    case "manhattan" => manhattan(targets, width, height)
    case "chebyshev" => chebyshev(targets, width, height)
    case _ => throw new IllegalArgumentException("unsupported fast distance metric")
  }

  def squaredEuclidean(targets: Array[Boolean], width: Int, height: Int): Array[Long] = {
    val cells = validate(targets, width, height)
    val distances = new Array[Long](cells)
    val maxDimension = math.max(width, height)
    val sites = new Array[Int](maxDimension)
    val starts = new Array[Int](maxDimension)

    // A one-dimensional rectangle needs only the binary transform. This also
    // avoids a second line-sized Long buffer for very long, thin inputs.
    if (width == 1 || height == 1) {
      val length = math.max(width, height)
      LocalEeFastDistanceTransformEnvelope.transformBinaryLine(
        targets, 0, 1, length, distances, 0, 1, sites, starts)
      return distances
    }

    // Squared Euclidean cost is separable: first minimize horizontal squared
    // distance for each row, then minimize vertical squared distance per column.
    var row = 0
    while (row < height) {
      val rowStart = row * width
      LocalEeFastDistanceTransformEnvelope.transformBinaryLine(
        targets, rowStart, 1, width, distances, rowStart, 1, sites, starts)
      row += 1
    }

    val columnValues = new Array[Long](height)
    var col = 0
    while (col < width) {
      row = 0
      while (row < height) {
        columnValues(row) = distances(row * width + col)
        row += 1
      }
      LocalEeFastDistanceTransformEnvelope.transformCostLine(
        columnValues, height, distances, col, width, sites, starts)
      col += 1
    }
    distances
  }

  def manhattan(targets: Array[Boolean], width: Int, height: Int): Array[Long] = {
    val cells = validate(targets, width, height)
    val distances = new Array[Long](cells)
    var index = 0
    while (index < cells) {
      distances(index) = if (targets(index)) 0L else NoTargetDistance
      index += 1
    }

    // For L1, each axis contributes an absolute-value cost. Two directional
    // scans per axis compute the exact minimum without a search radius.
    var row = 0
    while (row < height) {
      val base = row * width
      var col = 1
      while (col < width) {
        val candidate = plusOne(distances(base + col - 1))
        if (candidate < distances(base + col)) distances(base + col) = candidate
        col += 1
      }
      col = width - 2
      while (col >= 0) {
        val candidate = plusOne(distances(base + col + 1))
        if (candidate < distances(base + col)) distances(base + col) = candidate
        col -= 1
      }
      row += 1
    }

    var col = 0
    while (col < width) {
      row = 1
      while (row < height) {
        val index = row * width + col
        val candidate = plusOne(distances(index - width))
        if (candidate < distances(index)) distances(index) = candidate
        row += 1
      }
      row = height - 2
      while (row >= 0) {
        val index = row * width + col
        val candidate = plusOne(distances(index + width))
        if (candidate < distances(index)) distances(index) = candidate
        row -= 1
      }
      col += 1
    }
    distances
  }

  def chebyshev(targets: Array[Boolean], width: Int, height: Int): Array[Long] = {
    val cells = validate(targets, width, height)
    val distances = new Array[Long](cells)
    var index = 0
    while (index < cells) {
      distances(index) = if (targets(index)) 0L else NoTargetDistance
      index += 1
    }

    // In a forward row-major scan, left and the three cells above are already
    // optimal predecessors. The reverse scan uses right and the three below.
    // These are exactly the eight unit-cost moves of the Chebyshev grid metric.
    var row = 0
    while (row < height) {
      var col = 0
      while (col < width) {
        val current = row * width + col
        var best = distances(current)
        if (col > 0) best = math.min(best, plusOne(distances(current - 1)))
        if (row > 0) {
          val above = current - width
          best = math.min(best, plusOne(distances(above)))
          if (col > 0) best = math.min(best, plusOne(distances(above - 1)))
          if (col + 1 < width) best = math.min(best, plusOne(distances(above + 1)))
        }
        distances(current) = best
        col += 1
      }
      row += 1
    }

    row = height - 1
    while (row >= 0) {
      var col = width - 1
      while (col >= 0) {
        val current = row * width + col
        var best = distances(current)
        if (col + 1 < width) best = math.min(best, plusOne(distances(current + 1)))
        if (row + 1 < height) {
          val below = current + width
          best = math.min(best, plusOne(distances(below)))
          if (col > 0) best = math.min(best, plusOne(distances(below - 1)))
          if (col + 1 < width) best = math.min(best, plusOne(distances(below + 1)))
        }
        distances(current) = best
        col -= 1
      }
      row -= 1
    }
    distances
  }

  private def validate(targets: Array[Boolean], width: Int, height: Int): Int = {
    require(width > 0 && height > 0, "distance grid dimensions must be positive")
    val cellCount = Math.multiplyExact(width.toLong, height.toLong)
    require(cellCount <= MaxCells, "distance grid exceeds the 10,000,000 cell limit")
    require(targets != null, "distance target mask must not be null")
    require(targets.length.toLong == cellCount, "distance target mask length must equal width times height")
    cellCount.toInt
  }

  private def plusOne(distance: Long): Long =
    if (distance == NoTargetDistance) NoTargetDistance else distance + 1L
}
