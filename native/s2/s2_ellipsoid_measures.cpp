#include "s2_ellipsoid_measures.h"

#include <cmath>
#include <limits>
#include <map>
#include <memory>
#include <string>
#include <utility>

#include "s2_ellipsoid_math.h"
#include "s2_ellipsoid_math_internal.h"

namespace local_ee_s2 {
namespace {

using ellipsoid_internal::CompensatedSum;

constexpr size_t kGaussEvaluationsPerEdge = 56;

Coordinate ReadCoordinate(const PartView& part, size_t index) {
  return {part.coordinates[index * 2], part.coordinates[index * 2 + 1]};
}

bool SameCanonicalCoordinate(Coordinate left, Coordinate right) {
  left = CanonicalizeCoordinate(left);
  right = CanonicalizeCoordinate(right);
  return left.longitude == right.longitude && left.latitude == right.latitude;
}

bool AddSelectedEdges(size_t count, size_t* total) {
  if (count > std::numeric_limits<size_t>::max() - *total) return false;
  *total += count;
  return true;
}

bool Fail(std::string* error, const std::string& message) {
  if (error != nullptr) *error = message;
  return false;
}

bool BuildWgs84PolygonLoops(const ShapeView& shape, const S2Polygon& polygon,
                            Wgs84PolygonLoops* loops,
                            std::string* error) {
  if (loops == nullptr) return Fail(error, "WGS84 polygon loop output is null");
  loops->clear();
  if (polygon.is_full() || polygon.is_empty()) return true;

  std::map<PointKey, Coordinate> coordinate_by_key;
  for (const PartView& part : shape.parts) {
    size_t count = part.vertex_count;
    if (count > 3 &&
        SameCanonicalCoordinate(ReadCoordinate(part, 0),
                                ReadCoordinate(part, count - 1))) {
      --count;
    }
    for (size_t i = 0; i < count; ++i) {
      const Coordinate coordinate =
          CanonicalizeCoordinate(ReadCoordinate(part, i));
      const PointKey key = KeyForPoint(ToPoint(coordinate));
      const auto inserted = coordinate_by_key.emplace(key, coordinate);
      if (!inserted.second &&
          !SameCanonicalCoordinate(inserted.first->second, coordinate)) {
        return Fail(error,
                    "distinct WGS84 coordinates collide at S2 point resolution");
      }
    }
  }

  loops->reserve(static_cast<size_t>(polygon.num_loops()));
  for (int loop_index = 0; loop_index < polygon.num_loops(); ++loop_index) {
    const S2Loop* loop = polygon.loop(loop_index);
    std::vector<Coordinate> coordinates;
    coordinates.reserve(static_cast<size_t>(loop->num_vertices()));
    for (int vertex_index = 0; vertex_index < loop->num_vertices();
         ++vertex_index) {
      const auto found =
          coordinate_by_key.find(KeyForPoint(loop->vertex(vertex_index)));
      if (found == coordinate_by_key.end()) {
        return Fail(error,
                    "validated S2 loop vertex has no original WGS84 coordinate");
      }
      coordinates.push_back(found->second);
    }
    loops->push_back(std::move(coordinates));
  }
  return true;
}

}  // namespace

size_t EstimateWgs84MeasureWork(int op, const ParsedGeometry& parsed,
                                bool* overflow) {
  if (overflow == nullptr) return 0;
  *overflow = false;
  if (op != kWgs84AreaOperation && op != kWgs84LinearLengthOperation &&
      op != kWgs84PolygonPerimeterOperation) {
    *overflow = true;
    return 0;
  }
  size_t edges = 0;
  for (const ShapeView& shape : parsed.shapes) {
    if (op == kWgs84LinearLengthOperation && shape.kind == ShapeKind::kLine) {
      for (const PartView& part : shape.parts) {
        if (!AddSelectedEdges(part.vertex_count == 0 ? 0 : part.vertex_count - 1,
                              &edges)) {
          *overflow = true;
          return 0;
        }
      }
    } else if ((op == kWgs84AreaOperation ||
                op == kWgs84PolygonPerimeterOperation) &&
               shape.kind == ShapeKind::kPolygon) {
      const bool full_sentinel = shape.parts.size() == 1 &&
                                 shape.parts[0].vertex_count == 0 &&
                                 !shape.even_odd;
      if (full_sentinel) continue;
      for (const PartView& part : shape.parts) {
        size_t count = part.vertex_count;
        if (count > 3 &&
            SameCanonicalCoordinate(ReadCoordinate(part, 0),
                                    ReadCoordinate(part, count - 1))) {
          --count;
        }
        if (!AddSelectedEdges(count, &edges)) {
          *overflow = true;
          return 0;
        }
      }
    }
  }
  if (edges > std::numeric_limits<size_t>::max() /
                  kGaussEvaluationsPerEdge) {
    *overflow = true;
    return 0;
  }
  return edges * kGaussEvaluationsPerEdge;
}

bool RunEllipsoidMeasure(int op, const ParsedGeometry& parsed,
                         S2MemoryTracker* tracker, double output[2],
                         std::string* error) {
  if (tracker == nullptr || output == nullptr || error == nullptr) {
    return Fail(error, "WGS84 measurement state is null");
  }
  if (op != kWgs84AreaOperation && op != kWgs84LinearLengthOperation &&
      op != kWgs84PolygonPerimeterOperation) {
    return Fail(error, "unsupported WGS84 measurement operation");
  }

  CompensatedSum total;
  for (const ShapeView& shape : parsed.shapes) {
    if (shape.kind == ShapeKind::kPoints) continue;
    if (shape.kind == ShapeKind::kLine) {
      for (const PartView& part : shape.parts) {
        std::unique_ptr<S2Polyline> line;
        if (!BuildLineComponent(part, &line, error)) return false;
        if (op == kWgs84LinearLengthOperation && line != nullptr) {
          long double value = 0.0L;
          if (!MeasureWgs84LineLength(part, &value, error)) return false;
          total.Add(value);
        }
      }
      continue;
    }

    std::unique_ptr<S2Polygon> polygon;
    if (!BuildPolygonComponent(shape, tracker, &polygon, error)) return false;
    if (polygon == nullptr) continue;
    if (op == kWgs84AreaOperation) {
      Wgs84PolygonLoops loops;
      if (!BuildWgs84PolygonLoops(shape, *polygon, &loops, error)) return false;
      long double value = 0.0L;
      if (!MeasureWgs84PolygonArea(*polygon, loops, &value, error)) return false;
      total.Add(value);
    } else if (op == kWgs84PolygonPerimeterOperation) {
      Wgs84PolygonLoops loops;
      if (!BuildWgs84PolygonLoops(shape, *polygon, &loops, error)) return false;
      long double value = 0.0L;
      if (!MeasureWgs84PolygonPerimeter(*polygon, loops, &value, error)) {
        return false;
      }
      total.Add(value);
    }
  }

  const long double value = total.Value();
  if (!std::isfinite(value) || value < 0.0L ||
      value > std::numeric_limits<double>::max()) {
    return Fail(error, "WGS84 measurement result is nonfinite or out of range");
  }
  output[0] = 1.0;
  output[1] = static_cast<double>(value);
  return true;
}

}  // namespace local_ee_s2
