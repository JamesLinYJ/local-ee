#include "s2_internal.h"

#include <cmath>
#include <memory>
#include <utility>

#include "s2/s2debug.h"
#include "s2/s2latlng.h"
#include "s2/s2point_vector_shape.h"

namespace local_ee_s2 {

Coordinate CanonicalizeCoordinate(Coordinate value) {
  if (value.latitude == 90 || value.latitude == -90) value.longitude = 0;
  if (value.longitude == 180) value.longitude = -180;
  if (value.longitude == 0) value.longitude = 0;
  if (value.latitude == 0) value.latitude = 0;
  return value;
}

S2Point ToPoint(Coordinate value) {
  value = CanonicalizeCoordinate(value);
  return S2LatLng::FromDegrees(value.latitude, value.longitude).ToPoint();
}

namespace {

Coordinate ReadCoordinate(const PartView& part, size_t index) {
  return {part.coordinates[index * 2], part.coordinates[index * 2 + 1]};
}

bool SamePoint(Coordinate left, Coordinate right) {
  left = CanonicalizeCoordinate(left);
  right = CanonicalizeCoordinate(right);
  return left.longitude == right.longitude && left.latitude == right.latitude;
}

bool Antipodal(Coordinate left, Coordinate right) {
  if (left.latitude == 90 && right.latitude == -90) return true;
  if (left.latitude == -90 && right.latitude == 90) return true;
  if (left.latitude != -right.latitude) return false;
  double delta = std::fabs(left.longitude - right.longitude);
  if (delta > 180) delta = 360 - delta;
  return delta == 180;
}

bool ValidateLine(const PartView& part, std::vector<S2Point>* points,
                  std::string* error) {
  points->reserve(part.vertex_count);
  for (size_t i = 0; i < part.vertex_count; ++i) {
    const Coordinate coordinate = ReadCoordinate(part, i);
    if (i != 0) {
      const Coordinate previous = ReadCoordinate(part, i - 1);
      if (SamePoint(previous, coordinate)) {
        *error = "line has adjacent duplicate vertices";
        return false;
      }
      if (Antipodal(previous, coordinate)) {
        *error = "line has an antipodal edge";
        return false;
      }
    }
    points->push_back(ToPoint(coordinate));
  }
  return true;
}

bool BuildPolygon(const ShapeView& shape, S2MemoryTracker* tracker,
                  std::unique_ptr<S2Polygon>* polygon, std::string* error) {
  const bool full_sentinel = shape.parts.size() == 1 &&
                             shape.parts[0].vertex_count == 0 &&
                             !shape.even_odd;
  if (full_sentinel) {
    *polygon = std::make_unique<S2Polygon>(S2Polygon::MakeFull());
    return true;
  }
  if (shape.parts.empty()) return true;

  std::vector<std::unique_ptr<S2Loop>> loops;
  loops.reserve(shape.parts.size());
  for (const PartView& part : shape.parts) {
    size_t count = part.vertex_count;
    if (count > 3 && SamePoint(ReadCoordinate(part, 0),
                               ReadCoordinate(part, count - 1))) {
      --count;  // GeoJSON rings may repeat their first coordinate at the end.
    }
    if (count < 3) {
      *error = "polygon loop has fewer than three distinct positions";
      return false;
    }
    std::vector<S2Point> vertices;
    vertices.reserve(count);
    for (size_t i = 0; i < count; ++i) {
      const Coordinate coordinate = ReadCoordinate(part, i);
      for (size_t j = 0; j < i; ++j) {
        if (SamePoint(ReadCoordinate(part, j), coordinate)) {
          *error = "polygon loop has duplicate vertices";
          return false;
        }
      }
      const Coordinate next = ReadCoordinate(part, (i + 1) % count);
      if (Antipodal(coordinate, next)) {
        *error = "polygon loop has an antipodal edge";
        return false;
      }
      vertices.push_back(ToPoint(coordinate));
    }
    auto loop = std::make_unique<S2Loop>(vertices, S2Debug::DISABLE);
    S2Error loop_error;
    if (loop->FindValidationError(&loop_error)) {
      *error = std::string("invalid polygon loop: ") +
               std::string(loop_error.message());
      return false;
    }
    if (shape.even_odd) loop->Normalize();
    loops.push_back(std::move(loop));
  }

  auto result = std::make_unique<S2Polygon>();
  result->set_s2debug_override(S2Debug::DISABLE);
  if (shape.even_odd) {
    result->InitNested(std::move(loops));
  } else {
    result->InitOriented(std::move(loops));
  }
  S2Error polygon_error;
  if (result->FindValidationError(&polygon_error)) {
    *error = std::string("invalid polygon topology: ") +
             std::string(polygon_error.message());
    return false;
  }
  *polygon = std::move(result);
  (void)tracker;  // S2 polygon construction is bounded by the preflight caps.
  return true;
}

bool BuildSingleShape(const ShapeView& shape, S2MemoryTracker* tracker,
                      MutableS2ShapeIndex* index, std::string* error) {
  index->set_memory_tracker(tracker);
  if (shape.kind == ShapeKind::kPoints) {
    const PartView& part = shape.parts[0];
    if (part.vertex_count == 0) return true;
    std::vector<S2Point> points;
    points.reserve(part.vertex_count);
    for (size_t i = 0; i < part.vertex_count; ++i) {
      points.push_back(ToPoint(ReadCoordinate(part, i)));
    }
    index->Add(std::make_unique<S2PointVectorShape>(std::move(points)));
    return true;
  }
  if (shape.kind == ShapeKind::kLine) {
    const PartView& part = shape.parts[0];
    if (part.vertex_count < 2) return true;
    std::vector<S2Point> points;
    if (!ValidateLine(part, &points, error)) return false;
    auto line = std::make_unique<S2Polyline>(points, S2Debug::DISABLE);
    S2Error line_error;
    if (line->FindValidationError(&line_error)) {
      *error = std::string("invalid line: ") +
               std::string(line_error.message());
      return false;
    }
    std::unique_ptr<const S2Polyline> owned_line = std::move(line);
    index->Add(std::make_unique<S2Polyline::OwningShape>(std::move(owned_line)));
    return true;
  }

  std::unique_ptr<S2Polygon> polygon;
  if (!BuildPolygon(shape, tracker, &polygon, error)) return false;
  if (polygon == nullptr || polygon->is_empty()) return true;
  std::unique_ptr<const S2Polygon> owned_polygon = std::move(polygon);
  index->Add(std::make_unique<S2Polygon::OwningShape>(std::move(owned_polygon)));
  return true;
}

}  // namespace

bool BuildShapeIndex(const ParsedGeometry& parsed, S2MemoryTracker* tracker,
                     MutableS2ShapeIndex* index, std::string* error) {
  index->set_memory_tracker(tracker);
  for (const ShapeView& shape : parsed.shapes) {
    MutableS2ShapeIndex single;
    if (!BuildSingleShape(shape, tracker, &single, error)) return false;
    if (single.num_shape_ids() == 0) continue;
    if (index->num_shape_ids() == 0) {
      *index = std::move(single);
      index->set_memory_tracker(tracker);
      continue;
    }
    GeometryOutput merged;
    if (!RunOverlay(5, *index, single, tracker, &merged, error)) return false;
    MutableS2ShapeIndex next;
    if (!AddOutputToIndex(&merged, tracker, &next, error)) return false;
    *index = std::move(next);
    index->set_memory_tracker(tracker);
  }
  return true;
}

}  // namespace local_ee_s2
