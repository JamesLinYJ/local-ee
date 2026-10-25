#ifndef LOCAL_EE_S2_INTERNAL_H_
#define LOCAL_EE_S2_INTERNAL_H_

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <array>
#include <memory>
#include <string>
#include <vector>

#include "s2/mutable_s2shape_index.h"
#include "s2/s2latlng_rect.h"
#include "s2/s2memory_tracker.h"
#include "s2/s2point.h"
#include "s2/s2lax_polygon_shape.h"
#include "s2/s2polygon.h"
#include "s2/s2polyline.h"
#include "s2/s2shape_index.h"

namespace local_ee_s2 {

using PointKey = std::array<uint64_t, 3>;

inline PointKey KeyForPoint(const S2Point& point) {
  static_assert(sizeof(double) == sizeof(uint64_t),
                "S2 coordinate key requires 64-bit doubles");
  const double components[] = {point.x(), point.y(), point.z()};
  PointKey key;
  for (size_t i = 0; i < key.size(); ++i) {
    std::memcpy(&key[i], &components[i], sizeof(key[i]));
  }
  return key;
}

constexpr size_t kMaxInputPositions = 10000;
constexpr size_t kMaxInputShapes = 1000;
constexpr size_t kMaxInputParts = 10000;
constexpr size_t kMaxWork = 50000;
constexpr size_t kMaxOutputPositions = 10000;
constexpr size_t kMaxOutputShapes = 1000;
constexpr size_t kMaxOutputParts = 10000;
constexpr size_t kMaxOutputDoubles = 65536;
constexpr int64_t kMaxTrackedBytes = 64LL * 1024 * 1024;

enum class ShapeKind : int { kPoints = 0, kLine = 1, kPolygon = 2 };

struct Coordinate {
  double longitude;
  double latitude;
};

Coordinate CanonicalizeCoordinate(Coordinate value);
S2Point ToPoint(Coordinate value);
S2Point MeasureCentroidPoint(Coordinate value);

struct PartView {
  const double* coordinates = nullptr;
  size_t vertex_count = 0;
};

struct ShapeView {
  ShapeKind kind = ShapeKind::kPoints;
  bool even_odd = false;
  std::vector<PartView> parts;
  size_t position_count = 0;
  size_t edge_count = 0;
};

struct ParsedGeometry {
  std::vector<ShapeView> shapes;
  size_t position_count = 0;
  size_t edge_count = 0;
  size_t active_shape_count = 0;
  size_t part_count = 0;
};

struct GeometryOutput {
  std::vector<S2Point> points;
  std::vector<std::unique_ptr<S2Polyline>> polylines;
  S2Polygon polygon;
};

bool ParseWire(const double* data, size_t size, ParsedGeometry* parsed,
               std::string* error);
bool CheckCallBudget(const ParsedGeometry& left, const ParsedGeometry* right,
                     size_t* work_out, std::string* error);

bool BuildShapeIndex(const ParsedGeometry& parsed, S2MemoryTracker* tracker,
                     MutableS2ShapeIndex* index, S2LatLngRect* bounds,
                     std::string* error);
bool BuildLineComponent(const PartView& part,
                        std::unique_ptr<S2Polyline>* polyline,
                        std::string* error);
bool BuildPolygonComponent(const ShapeView& shape, S2MemoryTracker* tracker,
                           std::unique_ptr<S2Polygon>* polygon,
                           std::string* error);
bool BuildLineComponentForCentroid(const PartView& part,
                                   std::unique_ptr<S2Polyline>* polyline,
                                   std::string* error);
bool BuildPolygonComponentForCentroid(
    const ShapeView& shape, S2MemoryTracker* tracker,
    std::unique_ptr<S2Polygon>* polygon, std::string* error);
bool RunMeasures(const ParsedGeometry& parsed, S2MemoryTracker* tracker,
                 double output[8], std::string* error);
S2LatLngRect BoundsForPoints(const std::vector<S2Point>& points);
S2LatLngRect BoundsForOutput(const GeometryOutput& output);
bool PackBounds(const S2LatLngRect& bounds, double* output,
                std::string* error);
bool AddOutputToIndex(GeometryOutput* output, S2MemoryTracker* tracker,
                      MutableS2ShapeIndex* index, std::string* error);
bool ExtractLaxPolygon(const S2LaxPolygonShape& lax_polygon,
                       GeometryOutput* output, std::string* error);
bool RunOverlay(int op, const S2ShapeIndex& left, const S2ShapeIndex& right,
                S2MemoryTracker* tracker, GeometryOutput* result,
                std::string* error);
bool PackOutput(const GeometryOutput& result, const ParsedGeometry& left,
                const ParsedGeometry* right, double* output,
                size_t output_capacity, size_t* output_size,
                std::string* error);
size_t EstimateWireSize(const GeometryOutput& result, bool* overflow);

}  // namespace local_ee_s2

#endif  // LOCAL_EE_S2_INTERNAL_H_
