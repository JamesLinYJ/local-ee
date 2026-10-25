#include "s2_internal.h"

#include <algorithm>
#include <cmath>
#include <memory>
#include <tuple>
#include <utility>
#include <vector>

#include "s2/s1angle.h"
#include "s2/s2latlng.h"
#include "s2/s2loop.h"
#include "s2/s2point_vector_shape.h"

namespace local_ee_s2 {
namespace {

bool Fail(std::string* error, const char* message) {
  if (error != nullptr) *error = message;
  return false;
}

bool IsActive(const ShapeView& shape) {
  switch (shape.kind) {
    case ShapeKind::kPoints:
      return shape.position_count != 0;
    case ShapeKind::kLine:
      return shape.edge_count != 0;
    case ShapeKind::kPolygon:
      return !shape.parts.empty();
  }
  return false;
}

int HighestDimension(const ParsedGeometry& parsed) {
  int dimension = -1;
  for (const ShapeView& shape : parsed.shapes) {
    if (IsActive(shape)) {
      dimension = std::max(dimension, static_cast<int>(shape.kind));
    }
  }
  return dimension;
}

double PolygonPerimeter(const S2Polygon& polygon) {
  double perimeter = 0;
  for (int loop_index = 0; loop_index < polygon.num_loops(); ++loop_index) {
    const S2Loop* loop = polygon.loop(loop_index);
    const int vertex_count = loop->num_vertices();
    for (int vertex_index = 0; vertex_index < vertex_count; ++vertex_index) {
      perimeter += S1Angle(
          loop->vertex(vertex_index),
          loop->vertex((vertex_index + 1) % vertex_count)).radians();
    }
  }
  return perimeter;
}

S2Point MeasureCentroidPointImpl(Coordinate coordinate) {
  coordinate = CanonicalizeCoordinate(coordinate);
  Coordinate antipode{coordinate.longitude >= 0
                           ? coordinate.longitude - 180
                           : coordinate.longitude + 180,
                       -coordinate.latitude};
  antipode = CanonicalizeCoordinate(antipode);

  // S2LatLng's trigonometric conversion can leave a tiny residual when two
  // exact antipodes are added (for example, 0 and 180 degrees longitude).
  // Pick one canonical representative and derive its antipode by exact
  // negation. This preserves small nonzero resultants without an epsilon.
  const auto preference = [](const Coordinate& value) {
    return std::make_tuple(std::fabs(value.longitude), value.longitude,
                           value.latitude);
  };
  const bool use_coordinate = preference(coordinate) <= preference(antipode);
  const Coordinate representative = use_coordinate ? coordinate : antipode;
  const S2Point point = ToPoint(representative);
  return use_coordinate ? point : -point;
}

}  // namespace

S2Point MeasureCentroidPoint(Coordinate coordinate) {
  return MeasureCentroidPointImpl(coordinate);
}

bool RunMeasures(const ParsedGeometry& parsed, S2MemoryTracker* tracker,
                 double output[8], std::string* error) {
  if (tracker == nullptr || output == nullptr || error == nullptr) {
    return Fail(error, "measurement state is null");
  }

  const int dimension = HighestDimension(parsed);
  double area = 0;
  double linear_length = 0;
  double polygon_perimeter = 0;
  S2Point centroid(0, 0, 0);

  // Retain each original shape as a separate index entry. This accounts for
  // S2 index allocations without overlaying or deduplicating components.
  MutableS2ShapeIndex components;
  components.set_memory_tracker(tracker);
  for (const ShapeView& shape : parsed.shapes) {
    if (!IsActive(shape)) continue;
    if (shape.kind == ShapeKind::kPoints) {
      const PartView& part = shape.parts[0];
      std::vector<S2Point> points;
      points.reserve(part.vertex_count);
      for (size_t i = 0; i < part.vertex_count; ++i) {
        const double longitude = part.coordinates[2 * i];
        const double latitude = part.coordinates[2 * i + 1];
        const S2Point point = MeasureCentroidPoint({longitude, latitude});
        points.push_back(point);
        if (dimension == 0) centroid += point;
      }
      components.Add(std::make_unique<S2PointVectorShape>(std::move(points)));
      continue;
    }

    if (shape.kind == ShapeKind::kLine) {
      const PartView& part = shape.parts[0];
      std::unique_ptr<S2Polyline> line;
      if (!BuildLineComponentForCentroid(part, &line, error)) return false;
      linear_length += line->GetLength().radians();
      if (dimension == 1) centroid += line->GetCentroid();
      std::unique_ptr<const S2Polyline> owned_line = std::move(line);
      components.Add(std::make_unique<S2Polyline::OwningShape>(
          std::move(owned_line)));
      continue;
    }

    std::unique_ptr<S2Polygon> polygon;
    if (!BuildPolygonComponentForCentroid(shape, tracker, &polygon, error)) {
      return false;
    }
    if (polygon == nullptr) continue;
    area += polygon->GetArea();
    polygon_perimeter += PolygonPerimeter(*polygon);
    if (dimension == 2) centroid += polygon->GetCentroid();
    std::unique_ptr<const S2Polygon> owned_polygon = std::move(polygon);
    components.Add(std::make_unique<S2Polygon::OwningShape>(
        std::move(owned_polygon)));
  }

  if (!std::isfinite(area) || !std::isfinite(linear_length) ||
      !std::isfinite(polygon_perimeter) || !std::isfinite(centroid.x()) ||
      !std::isfinite(centroid.y()) || !std::isfinite(centroid.z())) {
    return Fail(error, "spherical measurement result is nonfinite");
  }

  output[0] = 1.0;
  output[1] = static_cast<double>(dimension);
  output[2] = area;
  output[3] = linear_length;
  output[4] = polygon_perimeter;
  output[5] = centroid.x();
  output[6] = centroid.y();
  output[7] = centroid.z();
  return true;
}

}  // namespace local_ee_s2
