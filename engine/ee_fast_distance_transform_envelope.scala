package local.ee.reduce

/** One-dimensional squared-distance lower-envelope passes used by the grid transform. */
private[reduce] object LocalEeFastDistanceTransformEnvelope {
  val NoTargetDistance: Long = Long.MaxValue / 4L

  /** Lower envelope for binary costs (zero at target sites, infinity elsewhere). */
  def transformBinaryLine(
    targets: Array[Boolean], inputStart: Int, inputStride: Int, length: Int,
    output: Array[Long], outputStart: Int, outputStride: Int,
    sites: Array[Int], starts: Array[Int]
  ): Unit = {
    // Envelope invariant: sites are increasing; starts(i) is the first integer
    // coordinate owned by sites(i), so each site's active interval is exact.
    var last = -1
    var q = 0
    while (q < length) {
      if (targets(inputStart + q * inputStride)) {
        if (last < 0) {
          last = 0
          sites(0) = q
          starts(0) = 0
        } else {
          // For equal zero offsets, q first ties/beats p at ceil((p + q) / 2).
          var first = (q.toLong + sites(last).toLong + 1L) / 2L
          while (last >= 0 && first <= starts(last).toLong) {
            last -= 1
            if (last >= 0) first = (q.toLong + sites(last).toLong + 1L) / 2L
          }
          if (last < 0) {
            last = 0
            sites(0) = q
            starts(0) = 0
          } else {
            last += 1
            sites(last) = q
            starts(last) = first.toInt
          }
        }
      }
      q += 1
    }

    if (last < 0) {
      var x = 0
      while (x < length) {
        output(outputStart + x * outputStride) = NoTargetDistance
        x += 1
      }
    } else {
      var active = 0
      var x = 0
      while (x < length) {
        while (active < last && starts(active + 1) <= x) active += 1
        val delta = x.toLong - sites(active).toLong
        output(outputStart + x * outputStride) = delta * delta
        x += 1
      }
    }
  }

  /** Lower envelope for finite one-dimensional costs plus a squared offset. */
  def transformCostLine(
    values: Array[Long], length: Int, output: Array[Long], outputStart: Int, outputStride: Int,
    sites: Array[Int], starts: Array[Int]
  ): Unit = {
    // Keep only parabolas with a nonempty interval on this finite integer line.
    // Their ordered starts partition the coordinates at which each is minimal.
    var last = -1
    var q = 0
    while (q < length) {
      if (values(q) != NoTargetDistance) {
        if (last < 0) {
          last = 0
          sites(0) = q
          starts(0) = 0
        } else {
          var first = firstNoWorseInteger(values(q), q, values(sites(last)), sites(last))
          while (last >= 0 && first <= starts(last).toLong) {
            last -= 1
            if (last >= 0) {
              first = firstNoWorseInteger(values(q), q, values(sites(last)), sites(last))
            }
          }
          if (last < 0) {
            last = 0
            sites(0) = q
            starts(0) = 0
          } else if (first < length.toLong) {
            last += 1
            sites(last) = q
            starts(last) = first.toInt
          }
          // A candidate whose first winning coordinate is outside this line
          // cannot affect any output coordinate and is safely discarded.
        }
      }
      q += 1
    }

    if (last < 0) {
      var x = 0
      while (x < length) {
        output(outputStart + x * outputStride) = NoTargetDistance
        x += 1
      }
    } else {
      var active = 0
      var x = 0
      while (x < length) {
        while (active < last && starts(active + 1) <= x) active += 1
        val site = sites(active)
        val delta = x.toLong - site.toLong
        output(outputStart + x * outputStride) = values(site) + delta * delta
        x += 1
      }
    }
  }

  /**
    * First integer x where q's parabola is no greater than p's, for q > p.
    * Rearranging the two squared costs gives
    * 2(q-p)x >= f(q)+q^2-f(p)-p^2; integer ceil division keeps ties exact.
    */
  private def firstNoWorseInteger(fq: Long, q: Int, fp: Long, p: Int): Long = {
    val qLong = q.toLong
    val pLong = p.toLong
    val numerator = fq + qLong * qLong - fp - pLong * pLong
    val denominator = 2L * (qLong - pLong)
    val quotient = Math.floorDiv(numerator, denominator)
    if (Math.floorMod(numerator, denominator) == 0L) quotient else quotient + 1L
  }
}
