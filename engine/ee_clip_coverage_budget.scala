package local.ee.reduce

import org.locationtech.jts.geom.{Coordinate, Geometry, GeometryCollection, LineString, MultiPolygon, Polygon}
import scala.collection.mutable

/** Bounded admission shared by the production adapter and the local native probe.
  * Work units are a local operation proxy, not a formal CPU-time guarantee.
  */
private[reduce] object LocalEeClipCoverageBudget {
  val MaxCoverageWork = 67108864L
  val MaxBoundaryVisits = 1000000L
  val MaxBoundaryCells = 1000000L
  private val MaxGeometryParts = 1000000L
  private val MaxTileKeys = 100000L
  private val MaxTileCells = 10000000L
  private val MaxDecodedCells = 100000000L
  private val MaxGeometryDepth = 64

  final case class Admission(
    geometry: Geometry,
    treeDepth: Long,
    boundarySegments: Long,
    boundaryVisits: Long,
    uniqueBoundaryCells: Long,
    boundaryCells: BigInt,
    projectionWork: BigInt,
    perTileGeometryWork: BigInt,
    queryWork: BigInt,
    overlayWork: BigInt,
    totalWork: BigInt
  ) extends Serializable

  /** Reserve all spec-driven projection and per-key geometry work before projected JTS allocation. */
  def admit(
    positions: Int,
    plan: LocalEeClipCoverageGeometry.Plan,
    grid: LocalEeClipCoverageGeometry.Grid,
    keyCount: Long,
    observedTimeCount: Long,
    tileCells: Long,
    decodedCells: Long
  )(buildGeometry: () => Geometry): Admission = {
    require(plan != null && grid != null && buildGeometry != null,
      "clip coverage budget inputs must be present")
    require(positions > 0 && keyCount > 0L && keyCount <= MaxTileKeys &&
      observedTimeCount >= 1L && observedTimeCount <= keyCount &&
      tileCells > 0L && tileCells <= MaxTileCells && decodedCells > 0L &&
      decodedCells <= MaxDecodedCells &&
      BigInt(tileCells) == BigInt(grid.tileCols) * BigInt(grid.tileRows) &&
      BigInt(decodedCells) == BigInt(tileCells) * BigInt(keyCount),
      "clip coverage budget dimensions must be positive")
    require(plan.segments > 0L && plan.subdivisionNodes >= plan.segments &&
      plan.boundaryCellUpperBoundPerTile >= 0,
      "clip coverage plan is invalid")

    val treeDepth = ceilLog2(plan.segments.max(2L))
    val projectionWork = BigInt(plan.subdivisionNodes) * 8L +
      BigInt(positions) * 4L + BigInt(plan.segments) * (treeDepth + 4L)
    val perTileGeometryWork = BigInt(keyCount) * BigInt(plan.segments) * (treeDepth + 8L)
    val constructionWork = projectionWork + perTileGeometryWork
    val queryWork = BigInt(decodedCells) * (treeDepth + 8L)
    val preGeometryWork = constructionWork + queryWork
    require(preGeometryWork <= BigInt(MaxCoverageWork),
      s"local_ee_clip_coverage exceeds the $MaxCoverageWork bounded geometry-construction work budget")

    // This is synchronous driver work. Its projected vertices are bounded by the already charged
    // geodesic plan; no cube or RDD is captured by this callback.
    val geometry = buildGeometry()
    require(geometry != null, "clip coverage projected geometry is missing")
    val traced = traceBoundaryCells(geometry, grid, BigInt(MaxCoverageWork) - preGeometryWork)
    // The plan bound is also global-layout clipped; min preserves its zero for full-layout cover.
    val conservativeCandidates = BigInt(traced.uniqueCells)
      .min(plan.boundaryCellUpperBoundPerTile)
    val observations = BigInt(observedTimeCount)
    val boundaryCells = (conservativeCandidates * observations).min(BigInt(decodedCells))
    val overlayWork = boundaryCells * BigInt(plan.segments) * (20L + treeDepth)
    val boundaryTraceWork = BigInt(traced.visits) + BigInt(traced.segments) + BigInt(traced.parts)
    val totalWork = preGeometryWork + overlayWork + boundaryTraceWork
    require(totalWork <= BigInt(MaxCoverageWork),
      s"local_ee_clip_coverage exceeds the $MaxCoverageWork conservative geometry/pixel work budget")

    Admission(geometry, treeDepth, traced.segments, traced.visits, traced.uniqueCells,
      boundaryCells, projectionWork, perTileGeometryWork, queryWork, overlayWork, totalWork)
  }

  private final case class Trace(segments: Long, visits: Long, uniqueCells: Long, parts: Long)
  private final case class Range(first: Long, last: Long) {
    val size: BigInt = BigInt(last) - BigInt(first) + 1
  }

  /** Deduplicate closed-cell bbox candidates in global layout pixel coordinates. */
  private def traceBoundaryCells(
    geometry: Geometry, grid: LocalEeClipCoverageGeometry.Grid, traceBudget: BigInt
  ): Trace = {
    require(traceBudget >= 0, "clip coverage boundary trace has no remaining work budget")
    val cells = mutable.HashSet.empty[(Long, Long)]
    var segments = 0L
    var visits = 0L
    var parts = 0L
    var traceWork = BigInt(0)

    def reserveTraceWork(amount: BigInt): Unit = {
      require(amount >= 0 && traceWork + amount <= traceBudget,
        "clip coverage boundary tracing exceeds the remaining conservative work budget")
      traceWork += amount
    }

    def reservePart(): Unit = {
      parts = Math.addExact(parts, 1L)
      require(parts <= MaxGeometryParts,
        s"clip coverage boundary geometry exceeds the $MaxGeometryParts-part limit")
      reserveTraceWork(BigInt(1))
    }

    def addSegment(start: Coordinate, end: Coordinate): Unit = {
      require(start != null && end != null && start.x.isFinite && start.y.isFinite &&
        end.x.isFinite && end.y.isFinite,
        "clip coverage projected boundary contains non-finite coordinates")
      val columns = indexRange(math.min(start.x, end.x), math.max(start.x, end.x), grid.columns)
      val rows = indexRange(math.min(start.y, end.y), math.max(start.y, end.y), grid.rows)
      for (columnRange <- columns; rowRange <- rows) {
        val bboxVisits = columnRange.size * rowRange.size
        val nextVisits = BigInt(visits) + bboxVisits
        require(nextVisits <= BigInt(MaxBoundaryVisits),
          s"clip coverage boundary tracing exceeds the $MaxBoundaryVisits-bbox-visit limit")
        // Reserve before any cell loop or set insertion, including long diagonal bboxes.
        reserveTraceWork(bboxVisits)
        // The immediately preceding MaxBoundaryVisits check proves this conversion is safe.
        visits = nextVisits.toLong
        var row = rowRange.first
        while (row <= rowRange.last) {
          var col = columnRange.first
          while (col <= columnRange.last) {
            val cell = (col, row)
            if (!cells.contains(cell)) {
              require(cells.size.toLong < MaxBoundaryCells,
                s"clip coverage boundary tracing exceeds the $MaxBoundaryCells-unique-cell limit")
              cells.add(cell)
            }
            col += 1L
          }
          row += 1L
        }
      }
    }

    def addRing(ring: LineString): Unit = {
      reservePart()
      val points = ring.getNumPoints
      require(points >= 4, "clip coverage projected polygon ring is too short")
      val ringSegments = points.toLong - 1L
      val nextSegments = Math.addExact(segments, ringSegments)
      require(nextSegments <= MaxBoundaryVisits,
        s"clip coverage boundary geometry exceeds the $MaxBoundaryVisits-segment limit")
      // Reserve the full ring walk before visiting any projected coordinate pair.
      reserveTraceWork(BigInt(ringSegments))
      segments = nextSegments
      var index = 1
      while (index < points) {
        addSegment(ring.getCoordinateN(index - 1), ring.getCoordinateN(index))
        index += 1
      }
    }

    def visit(current: Geometry, depth: Int): Unit = {
      if (current == null) throw new IllegalArgumentException("clip coverage boundary component is missing")
      require(depth <= MaxGeometryDepth,
        s"clip coverage boundary geometry exceeds the $MaxGeometryDepth-level nesting limit")
      if (current.isEmpty) return
      current match {
        case polygon: Polygon =>
          reservePart()
          addRing(polygon.getExteriorRing)
          val holes = polygon.getNumInteriorRing
          require(BigInt(parts) + BigInt(holes) <= BigInt(MaxGeometryParts) &&
            traceWork + BigInt(holes) <= traceBudget,
            "clip coverage polygon holes exceed the remaining boundary budget")
          var hole = 0
          while (hole < holes) {
            addRing(polygon.getInteriorRingN(hole))
            hole += 1
          }
        case multi: MultiPolygon =>
          reservePart()
          val count = multi.getNumGeometries
          require(BigInt(parts) + BigInt(count) <= BigInt(MaxGeometryParts),
            s"clip coverage boundary geometry exceeds the $MaxGeometryParts-part limit")
          require(traceWork + BigInt(count) <= traceBudget,
            "clip coverage boundary tracing exceeds the remaining conservative work budget")
          var index = 0
          while (index < count) {
            visit(multi.getGeometryN(index), depth + 1)
            index += 1
          }
        case collection: GeometryCollection =>
          reservePart()
          val count = collection.getNumGeometries
          require(BigInt(parts) + BigInt(count) <= BigInt(MaxGeometryParts),
            s"clip coverage boundary geometry exceeds the $MaxGeometryParts-part limit")
          require(traceWork + BigInt(count) <= traceBudget,
            "clip coverage boundary tracing exceeds the remaining conservative work budget")
          var index = 0
          while (index < count) {
            visit(collection.getGeometryN(index), depth + 1)
            index += 1
          }
        case _ =>
          throw new IllegalArgumentException(
            "clip coverage projected boundary must contain polygonal components only")
      }
    }

    if (geometry.isEmpty) Trace(0L, 0L, 0L, 0L)
    else {
      visit(geometry, 0)
      Trace(segments, visits, cells.size.toLong, parts)
    }
  }

  /** Closed-cell bounds include both neighbors when a boundary coordinate is an integer. */
  private def indexRange(minimum: Double, maximum: Double, dimension: Long): Option[Range] = {
    require(minimum.isFinite && maximum.isFinite && minimum <= maximum,
      "clip coverage boundary bbox is invalid")
    val limit = dimension.toDouble
    if (maximum < 0.0 || minimum > limit) None
    else {
      val clippedMinimum = math.max(0.0, minimum)
      val clippedMaximum = math.min(limit, maximum)
      val first = math.max(0L, (math.ceil(clippedMinimum) - 1.0).toLong)
      val last = math.min(dimension - 1L, math.floor(clippedMaximum).toLong)
      if (first <= last) Some(Range(first, last)) else None
    }
  }

  private def ceilLog2(value: Long): Long = {
    var remaining = value - 1L
    var result = 0L
    while (remaining > 0L) {
      remaining = remaining >>> 1
      result += 1L
    }
    result
  }
}
