package local.ee.reduce

import geotrellis.proj4.{CRS, LatLng, Transform}
import org.locationtech.jts.geom.{Coordinate, Geometry, GeometryFactory, LinearRing, Polygon}
import scala.collection.mutable.ArrayBuffer

/** Spherical minor-arc tessellation and projected polygon preparation in pixel coordinates. */
private[reduce] object LocalEeClipCoverageGeometry {
  final case class Grid(
    xmin: Double, ymin: Double, xmax: Double, ymax: Double,
    columns: Long, rows: Long, tileCols: Int, tileRows: Int
  ) extends Serializable {
    require(Seq(xmin, ymin, xmax, ymax).forall(_.isFinite) && xmin < xmax && ymin < ymax,
      "clip coverage requires a finite non-empty source layout extent")
    require(columns > 0L && rows > 0L && tileCols > 0 && tileRows > 0,
      "clip coverage source layout dimensions must be positive")
    require(columns <= 4503599627370496L && rows <= 4503599627370496L,
      "clip coverage source layout exceeds exact binary64 pixel coordinates")
    val cellWidth: Double = (xmax - xmin) / columns.toDouble
    val cellHeight: Double = (ymax - ymin) / rows.toDouble
    require((xmax - xmin).isFinite && (ymax - ymin).isFinite &&
      cellWidth.isFinite && cellWidth > 0.0 && cellHeight.isFinite && cellHeight > 0.0,
      "clip coverage source pixel dimensions must be finite and positive")
  }

  final case class Plan(segments: Long, subdivisionNodes: Long,
                        boundaryCellUpperBoundPerTile: BigInt) extends Serializable
  final case class Projected(geometry: Geometry, segments: Long) extends Serializable

  val MaxSegments = 200000L
  private val MaxNodes = MaxSegments * 2L + LocalEeClipCoverageSpec.MaxPositions.toLong
  private val MaxDepth = 32
  private val MaxAngularStep = math.toRadians(0.25)
  private val MaxChordDeviationPixels = 1e-6
  private val ExactPixelLimit = 4503599627370496.0 // 2^52
  private val WebMercatorLatitudeLimit = 85.0511287798066
  private val GeometryFactory = new GeometryFactory()

  /** Keep positive-area overlays, accept true lower-dimensional contact, and reject lost area. */
  def positiveAreaOrEmpty(subject: Geometry, clip: Geometry, intersection: Geometry, label: String): Geometry = {
    require(subject != null && clip != null && intersection != null,
      s"$label intersection inputs must be present")
    if (intersection.isEmpty || intersection.getDimension < 2) {
      val interiorsOverlap = subject.relate(clip).get(
        org.locationtech.jts.geom.Location.INTERIOR,
        org.locationtech.jts.geom.Location.INTERIOR) == org.locationtech.jts.geom.Dimension.A
      require(!interiorsOverlap, s"$label intersection lost a positive-area polygon")
      GeometryFactory.createMultiPolygon(Array.empty[Polygon])
    } else {
      require(intersection.isValid, s"$label intersection is topologically invalid")
      val area = intersection.getArea
      require(area.isFinite && area > 0.0, s"$label intersection has unresolved positive-area precision")
      intersection
    }
  }

  private final case class Vec(x: Double, y: Double, z: Double)
  private final case class Arc(
    start: Vec, end: Vec, tangent: Vec, angle: Double,
    meridianLongitude: Option[Double], equator: Boolean
  ) {
    def at(fraction: Double): Vec = {
      if (fraction == 0.0) start
      else if (fraction == 1.0) end
      else {
        val cosine = math.cos(angle * fraction)
        val sine = math.sin(angle * fraction)
        normalize(Vec(start.x * cosine + tangent.x * sine,
          start.y * cosine + tangent.y * sine, start.z * cosine + tangent.z * sine))
      }
    }
  }
  private final case class Context(target: CRS, epsg: Int, grid: Grid, transform: (Double, Double) => (Double, Double))

  /** Count all projected subdivision work without constructing the JTS geometry. */
  def plan(spec: LocalEeClipCoverageSpec.Value, target: CRS, epsg: Int, grid: Grid): Plan = {
    val context = contextFor(target, epsg, grid)
    var segments = 0L
    var nodes = 0L
    var boundaryCells = BigInt(0)
    spec.polygons.foreach(_.foreach { ring =>
      var index = 0
      while (index + 1 < ring.length) {
        val arc = makeArc(ring(index), ring(index + 1))
        validateArcDomain(arc, ring(index), ring(index + 1), context)
        // Use the caller's exact endpoint bits; vector→lon/lat reconstruction would move
        // shared vertices by a few ulps and can erase a very small boundary overlap.
        val start = projectPosition(ring(index), context)
        val end = projectPosition(ring(index + 1), context)
        val result = countArc(arc, 0.0, 1.0, start, end, 0, context, nodes)
        segments = Math.addExact(segments, result._1)
        nodes = result._2
        boundaryCells += result._3
        require(segments <= MaxSegments,
          s"clip coverage densification exceeds the $MaxSegments-segment limit")
        index += 1
      }
    })
    require(segments > 0L, "clip coverage geometry has no geodesic segments")
    Plan(segments, nodes, boundaryCells)
  }

  /** Build valid projected Polygon/MultiPolygon geometry, clipped to the actual source layout. */
  def project(
    spec: LocalEeClipCoverageSpec.Value, target: CRS, epsg: Int, grid: Grid, plan: Plan
  ): Projected = {
    val context = contextFor(target, epsg, grid)
    var emittedSegments = 0L
    var visitedNodes = 0L
    val polygons = spec.polygons.map { rings =>
      val projectedRings = rings.map { ring =>
        val coordinates = new ArrayBuffer[Coordinate]()
        coordinates += projectPosition(ring.head, context)
        var index = 0
        while (index + 1 < ring.length) {
          val arc = makeArc(ring(index), ring(index + 1))
          validateArcDomain(arc, ring(index), ring(index + 1), context)
          val start = projectPosition(ring(index), context)
          val end = projectPosition(ring(index + 1), context)
          val result = appendArc(arc, 0.0, 1.0, start, end, 0, context,
            coordinates, visitedNodes)
          emittedSegments = Math.addExact(emittedSegments, result._1)
          visitedNodes = result._2
          index += 1
        }
        val ringCoordinates = coordinates.toArray
        require(ringCoordinates.length >= 4 && ringCoordinates.head.equals2D(ringCoordinates.last),
          "clip coverage projected ring did not close")
        GeometryFactory.createLinearRing(ringCoordinates)
      }
      val shell: LinearRing = projectedRings.head
      val holes = projectedRings.drop(1).toArray
      val polygon: Polygon = GeometryFactory.createPolygon(shell, holes)
      require(!polygon.isEmpty && polygon.isValid && polygon.getArea > 0.0,
        "clip coverage polygon is degenerate or topologically invalid after projection")
      polygon
    }
    require(emittedSegments == plan.segments && visitedNodes == plan.subdivisionNodes,
      "clip coverage projection work changed between preflight and geometry construction")
    val multi = GeometryFactory.createMultiPolygon(polygons.toArray)
    require(multi.isValid, "clip coverage multipolygon topology is invalid after projection")
    val layout = GeometryFactory.toGeometry(new org.locationtech.jts.geom.Envelope(
      0.0, grid.columns.toDouble, 0.0, grid.rows.toDouble))
    val clipped = multi.intersection(layout)
    val positiveArea = positiveAreaOrEmpty(multi, layout, clipped, "clip coverage projected layout")
    Projected(positiveArea, plan.segments)
  }

  private def contextFor(target: CRS, epsg: Int, grid: Grid): Context = {
    require(target != null && grid != null, "clip coverage source CRS and grid are required")
    val transform = try Transform(LatLng, target) catch {
      case error: Exception => throw new IllegalArgumentException("clip coverage source CRS transform is unsupported", error)
    }
    Context(target, epsg, grid, (lon, lat) => transform(lon, lat))
  }

  private def countArc(
    arc: Arc, t0: Double, t1: Double, p0: Coordinate, p1: Coordinate, depth: Int,
    context: Context, priorNodes: Long
  ): (Long, Long, BigInt) = {
    val nodes = Math.addExact(priorNodes, 1L)
    require(nodes <= MaxNodes, "clip coverage subdivision exceeded its bounded node budget")
    val (middle, q1, q3, deviation) = samples(arc, t0, t1, p0, p1, context)
    val angle = arc.angle * (t1 - t0)
    if (angle <= MaxAngularStep && deviation <= MaxChordDeviationPixels)
      (1L, nodes, boundaryCellsForSegment(p0, p1, context.grid))
    else {
      require(depth < MaxDepth, "clip coverage geodesic subdivision could not meet the pixel chord tolerance")
      val tm = (t0 + t1) * 0.5
      val left = countArc(arc, t0, tm, p0, middle, depth + 1, context, nodes)
      countArc(arc, tm, t1, middle, p1, depth + 1, context, left._2) match {
        case (rightSegments, finalNodes, rightBoundary) =>
          (Math.addExact(left._1, rightSegments), finalNodes, left._3 + rightBoundary)
      }
    }
  }

  /** Upper-bound grid cells touched by one chord, clipped to the actual layout first. */
  private def boundaryCellsForSegment(start: Coordinate, end: Coordinate, grid: Grid): BigInt = {
    val dx = end.x - start.x
    val dy = end.y - start.y
    var first = 0.0
    var last = 1.0
    def clip(p: Double, q: Double): Boolean = {
      if (p == 0.0) q >= 0.0
      else {
        val ratio = q / p
        if (p < 0.0) {
          if (ratio > last) false
          else { if (ratio > first) first = ratio; true }
        } else {
          if (ratio < first) false
          else { if (ratio < last) last = ratio; true }
        }
      }
    }
    val intersects = clip(-dx, start.x) && clip(dx, grid.columns.toDouble - start.x) &&
      clip(-dy, start.y) && clip(dy, grid.rows.toDouble - start.y) && first <= last
    if (!intersects) BigInt(0)
    else {
      val span = last - first
      val columns = math.ceil(math.abs(dx * span)).toLong
      val rows = math.ceil(math.abs(dy * span)).toLong
      // A chord on grid lines can touch both adjacent cell rows/columns and a corner can touch four.
      BigInt(columns + rows + 2L) * 2L
    }
  }

  private def appendArc(
    arc: Arc, t0: Double, t1: Double, p0: Coordinate, p1: Coordinate, depth: Int,
    context: Context, coordinates: ArrayBuffer[Coordinate], priorNodes: Long
  ): (Long, Long) = {
    val nodes = Math.addExact(priorNodes, 1L)
    require(nodes <= MaxNodes, "clip coverage subdivision exceeded its bounded node budget")
    val (middle, _, _, deviation) = samples(arc, t0, t1, p0, p1, context)
    val angle = arc.angle * (t1 - t0)
    if (angle <= MaxAngularStep && deviation <= MaxChordDeviationPixels) {
      coordinates += p1
      (1L, nodes)
    } else {
      require(depth < MaxDepth, "clip coverage geodesic subdivision could not meet the pixel chord tolerance")
      val tm = (t0 + t1) * 0.5
      val left = appendArc(arc, t0, tm, p0, middle, depth + 1, context, coordinates, nodes)
      val right = appendArc(arc, tm, t1, middle, p1, depth + 1, context, coordinates, left._2)
      (Math.addExact(left._1, right._1), right._2)
    }
  }

  /** q1, midpoint and q3 compare projected geodesic samples to the projected endpoint chord. */
  private def samples(
    arc: Arc, t0: Double, t1: Double, p0: Coordinate, p1: Coordinate, context: Context
  ): (Coordinate, Coordinate, Coordinate, Double) = {
    val span = t1 - t0
    val q1 = projectPosition(positionAt(arc, t0 + span * 0.25), context)
    val middle = projectPosition(positionAt(arc, t0 + span * 0.5), context)
    val q3 = projectPosition(positionAt(arc, t0 + span * 0.75), context)
    val deviation = math.max(chordDeviation(q1, p0, p1, 0.25),
      math.max(chordDeviation(middle, p0, p1, 0.5), chordDeviation(q3, p0, p1, 0.75)))
    (middle, q1, q3, deviation)
  }

  private def chordDeviation(point: Coordinate, start: Coordinate, end: Coordinate, fraction: Double): Double = {
    val expectedX = start.x + (end.x - start.x) * fraction
    val expectedY = start.y + (end.y - start.y) * fraction
    val result = math.hypot(point.x - expectedX, point.y - expectedY)
    require(result.isFinite, "clip coverage projected chord deviation is non-finite")
    result
  }

  private def projectPosition(position: LocalEeClipCoverageSpec.Position, context: Context): Coordinate = {
    val lon = position.lon
    val lat = position.lat
    validatePositionDomain(lon, lat, context.epsg)
    val projected = try context.transform(lon, lat) catch {
      case error: Exception => throw new IllegalArgumentException("clip coverage coordinate is outside the source CRS transform domain", error)
    }
    require(projected._1.isFinite && projected._2.isFinite,
      "clip coverage coordinate did not transform to finite source-CRS coordinates")
    val x = (projected._1 - context.grid.xmin) / context.grid.cellWidth
    val y = (context.grid.ymax - projected._2) / context.grid.cellHeight
    require(x.isFinite && y.isFinite && math.abs(x) <= ExactPixelLimit && math.abs(y) <= ExactPixelLimit,
      "clip coverage projected coordinates exceed exact binary64 source-pixel coordinates")
    // This is a conservative arithmetic-resolution guard, not a formal transform/error bound.
    val xUncertainty = (math.ulp(projected._1) + math.ulp(context.grid.xmin)) / context.grid.cellWidth + math.ulp(x)
    val yUncertainty = (math.ulp(projected._2) + math.ulp(context.grid.ymax)) / context.grid.cellHeight + math.ulp(y)
    require(xUncertainty.isFinite && yUncertainty.isFinite &&
      xUncertainty < MaxChordDeviationPixels / 8.0 &&
      yUncertainty < MaxChordDeviationPixels / 8.0,
      "clip coverage grid precision is too coarse for the pixel chord tolerance")
    new Coordinate(x, y)
  }

  private def validatePositionDomain(lon: Double, lat: Double, epsg: Int): Unit = {
    require(lon.isFinite && lat.isFinite && lon >= -180.0 && lon <= 180.0 &&
      lat > -90.0 && lat < 90.0,
      "clip coverage positions must remain finite non-polar WGS84 longitude/latitude")
    epsg match {
    case 4326 => ()
    case 3857 => require(math.abs(lat) <= WebMercatorLatitudeLimit,
      "clip coverage geometry exceeds the EPSG:3857 latitude domain")
    case code if code >= 32601 && code <= 32660 =>
      require(lat >= 0.0 && lat <= 84.0, "clip coverage geometry is outside the northern UTM latitude domain")
      validateUtmLongitude(lon, code % 100)
    case code if code >= 32701 && code <= 32760 =>
      require(lat >= -80.0 && lat <= 0.0, "clip coverage geometry is outside the southern UTM latitude domain")
      validateUtmLongitude(lon, code % 100)
    case _ => throw new IllegalArgumentException("clip coverage source CRS is not supported")
    }
  }

  private def validateUtmLongitude(lon: Double, zone: Int): Unit = {
    val centralMeridian = zone * 6.0 - 183.0
    // Deliberately supports the normal three-degree zone, not Norway/Svalbard exceptions.
    require(math.abs(lon - centralMeridian) <= 3.0 + 1e-12,
      "clip coverage geometry is outside the source UTM zone longitude domain")
  }

  private def validateArcDomain(arc: Arc, start: LocalEeClipCoverageSpec.Position,
                                end: LocalEeClipCoverageSpec.Position, context: Context): Unit = {
    validatePositionDomain(start.lon, start.lat, context.epsg)
    validatePositionDomain(end.lon, end.lat, context.epsg)
    // Latitude extrema of a spherical arc occur at endpoints or where dz/dt = 0.
    val base = math.atan2(arc.tangent.z, arc.start.z)
    var turn = -2
    while (turn <= 2) {
      val t = base + turn * math.Pi
      if (t > 0.0 && t < arc.angle) {
        val position = positionAt(arc, t / arc.angle)
        validatePositionDomain(position.lon, position.lat, context.epsg)
      }
      turn += 1
    }
  }

  private def makeArc(start: LocalEeClipCoverageSpec.Position, end: LocalEeClipCoverageSpec.Position): Arc = {
    val a = toVec(start)
    val b = toVec(end)
    val dot = math.max(-1.0, math.min(1.0, a.x * b.x + a.y * b.y + a.z * b.z))
    val crossX = a.y * b.z - a.z * b.y
    val crossY = a.z * b.x - a.x * b.z
    val crossZ = a.x * b.y - a.y * b.x
    val angle = math.atan2(math.sqrt(crossX * crossX + crossY * crossY + crossZ * crossZ), dot)
    // This explicit binary64/resource guard does not define a mathematical degeneracy threshold.
    require(angle > 1e-14 && math.Pi - angle > 1e-12,
      "clip coverage edges must be nondegenerate minor great-circle arcs")
    val sin = math.sin(angle)
    val tangent = normalize(Vec((b.x - a.x * math.cos(angle)) / sin,
      (b.y - a.y * math.cos(angle)) / sin, (b.z - a.z * math.cos(angle)) / sin))
    Arc(a, b, tangent, angle,
      if (start.lon == end.lon) Some(start.lon) else None,
      start.lat == 0.0 && end.lat == 0.0)
  }

  /** Retain exact geodesic loci where binary64 vector-to-angle conversion would wobble. */
  private def positionAt(arc: Arc, fraction: Double): LocalEeClipCoverageSpec.Position = {
    val value = arc.at(fraction)
    val longitude = arc.meridianLongitude.getOrElse(math.toDegrees(math.atan2(value.y, value.x)))
    val latitude = if (arc.equator) 0.0
      else math.toDegrees(math.asin(math.max(-1.0, math.min(1.0, value.z))))
    LocalEeClipCoverageSpec.Position(longitude, latitude)
  }

  private def toVec(position: LocalEeClipCoverageSpec.Position): Vec = {
    val lon = math.toRadians(position.lon)
    val lat = math.toRadians(position.lat)
    val cosLat = math.cos(lat)
    Vec(cosLat * math.cos(lon), cosLat * math.sin(lon), math.sin(lat))
  }

  private def normalize(value: Vec): Vec = {
    val length = math.sqrt(value.x * value.x + value.y * value.y + value.z * value.z)
    require(length.isFinite && length > 0.0, "clip coverage spherical interpolation became degenerate")
    Vec(value.x / length, value.y / length, value.z / length)
  }
}
