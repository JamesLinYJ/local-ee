#include "s2_internal.h"

#include <limits>
#include <map>
#include <string>
#include <tuple>
#include <utility>

#include "s2/s2latlng.h"

namespace local_ee_s2 {
namespace {

using CoordinateRegistry = std::map<PointKey, Coordinate>;

void AddSourceCoordinates(const ParsedGeometry& parsed,
                          CoordinateRegistry* registry) {
  for (const ShapeView& shape : parsed.shapes) {
    for (const PartView& part : shape.parts) {
      for (size_t i = 0; i < part.vertex_count; ++i) {
        Coordinate coordinate{part.coordinates[2 * i],
                             part.coordinates[2 * i + 1]};
        coordinate = CanonicalizeCoordinate(coordinate);
        const PointKey key = KeyForPoint(ToPoint(coordinate));
        const auto inserted = registry->emplace(key, coordinate);
        if (!inserted.second &&
            std::tie(coordinate.longitude, coordinate.latitude) <
                std::tie(inserted.first->second.longitude,
                         inserted.first->second.latitude)) {
          inserted.first->second = coordinate;
        }
      }
    }
  }
}

bool AddSize(size_t amount, size_t* total) {
  if (amount > std::numeric_limits<size_t>::max() - *total) return false;
  *total += amount;
  return true;
}

bool AddCoordinates(size_t vertices, size_t* total) {
  if (vertices > std::numeric_limits<size_t>::max() / 2) return false;
  return AddSize(vertices * 2, total);
}

void WritePoint(const S2Point& point,
                const CoordinateRegistry& source_coordinates, double* output,
                size_t* cursor) {
  // Reuse exact source coordinates for unchanged S2 vertices. A newly
  // constructed intersection generally has no longitude/latitude double pair
  // that reprojects to the same three binary64 S2 coordinates, so its wire
  // coordinate is the nearest S2LatLng representation and may not lie exactly
  // on its source arcs when parsed again. Likewise, two coordinate tuples that
  // lie on the same ideal great circle need not produce exactly coplanar
  // binary64 S2Points. Do not add epsilon matching here: that would merge
  // distinct exact input points and change predicate results.
  const auto source = source_coordinates.find(KeyForPoint(point));
  if (source != source_coordinates.end()) {
    output[(*cursor)++] = source->second.longitude;
    output[(*cursor)++] = source->second.latitude;
    return;
  }
  const S2LatLng latlng(point);
  output[(*cursor)++] = latlng.lng().degrees();
  output[(*cursor)++] = latlng.lat().degrees();
}

}  // namespace

size_t EstimateWireSize(const GeometryOutput& result, bool* overflow) {
  *overflow = false;
  size_t size = 2;  // version and shape count
  size_t shape_count = 0;
  size_t position_count = 0;
  size_t part_count = 0;
  if (!result.points.empty()) ++shape_count;
  for (const auto& line : result.polylines) {
    if (line != nullptr && line->num_vertices() >= 2) ++shape_count;
  }
  if (!result.polygon.is_empty()) ++shape_count;
  if (shape_count > kMaxOutputShapes) {
    *overflow = true;
    return 0;
  }
  if (!AddSize(3 * shape_count, &size)) {
    *overflow = true;
    return 0;
  }
  if (!result.points.empty()) {
    if (!AddSize(1, &size) ||
        !AddCoordinates(result.points.size(), &size) ||
        !AddSize(result.points.size(), &position_count) ||
        !AddSize(1, &part_count)) {
      *overflow = true;
      return 0;
    }
  }
  for (const auto& line : result.polylines) {
    if (line == nullptr || line->num_vertices() < 2) continue;
    const size_t vertices = static_cast<size_t>(line->num_vertices());
    if (!AddSize(1, &size) ||
        !AddCoordinates(vertices, &size) ||
        !AddSize(vertices, &position_count) || !AddSize(1, &part_count)) {
      *overflow = true;
      return 0;
    }
  }
  if (!result.polygon.is_empty()) {
    const size_t loops = static_cast<size_t>(result.polygon.num_loops());
    if (!AddSize(loops, &size)) {
      *overflow = true;
      return 0;
    }
    if (!AddSize(loops, &part_count)) {
      *overflow = true;
      return 0;
    }
    if (!result.polygon.is_full()) {
      for (int loop_index = 0; loop_index < result.polygon.num_loops();
           ++loop_index) {
        const size_t vertices = static_cast<size_t>(
            result.polygon.loop(loop_index)->num_vertices());
        // Polygon rings are closed on the wire for the Python GeoJSON reader.
        if (vertices == std::numeric_limits<size_t>::max() ||
            !AddSize(vertices + 1, &position_count) ||
            !AddCoordinates(vertices + 1, &size)) {
          *overflow = true;
          return 0;
        }
      }
    } else if (loops != 1) {
      *overflow = true;
      return 0;
    }
  }
  if (position_count > kMaxOutputPositions ||
      part_count > kMaxOutputParts) {
    *overflow = true;
    return 0;
  }
  return size;
}

bool PackOutput(const GeometryOutput& result, const ParsedGeometry& left,
                const ParsedGeometry* right, double* output,
                size_t output_capacity, size_t* output_size,
                std::string* error) {
  if (output_size == nullptr || error == nullptr) {
    if (error != nullptr) *error = "output state is null";
    return false;
  }
  bool overflow = false;
  const size_t required = EstimateWireSize(result, &overflow);
  if (overflow || required > kMaxOutputDoubles) {
    *error = "geometry result exceeds an output shape, position, part, or "
             "wire bound";
    return false;
  }
  if (required > output_capacity || output == nullptr) {
    *error = "geometry output buffer is too small";
    return false;
  }

  CoordinateRegistry source_coordinates;
  AddSourceCoordinates(left, &source_coordinates);
  if (right != nullptr) AddSourceCoordinates(*right, &source_coordinates);

  size_t shape_count = 0;
  if (!result.points.empty()) ++shape_count;
  for (const auto& line : result.polylines) {
    if (line != nullptr && line->num_vertices() >= 2) ++shape_count;
  }
  if (!result.polygon.is_empty()) ++shape_count;

  size_t cursor = 0;
  output[cursor++] = 1.0;
  output[cursor++] = static_cast<double>(shape_count);
  if (!result.points.empty()) {
    output[cursor++] = 0.0;
    output[cursor++] = 0.0;
    output[cursor++] = 1.0;
    output[cursor++] = static_cast<double>(result.points.size());
    for (const S2Point& point : result.points) {
      WritePoint(point, source_coordinates, output, &cursor);
    }
  }
  for (const auto& line : result.polylines) {
    if (line == nullptr || line->num_vertices() < 2) continue;
    output[cursor++] = 1.0;
    output[cursor++] = 0.0;
    output[cursor++] = 1.0;
    output[cursor++] = static_cast<double>(line->num_vertices());
    for (int i = 0; i < line->num_vertices(); ++i) {
      WritePoint(line->vertex(i), source_coordinates, output, &cursor);
    }
  }
  if (!result.polygon.is_empty()) {
    output[cursor++] = 2.0;
    output[cursor++] = 0.0;
    output[cursor++] = static_cast<double>(result.polygon.num_loops());
    for (int loop_index = 0; loop_index < result.polygon.num_loops();
         ++loop_index) {
      const S2Loop* loop = result.polygon.loop(loop_index);
      const int vertex_count = result.polygon.is_full() ? 0 :
                               loop->num_vertices() + 1;
      output[cursor++] = static_cast<double>(vertex_count);
      for (int vertex = 0; vertex < vertex_count; ++vertex) {
        WritePoint(loop->oriented_vertex(vertex), source_coordinates, output,
                   &cursor);
      }
    }
  }
  if (cursor != required) {
    *error = "internal geometry output size mismatch";
    return false;
  }
  *output_size = cursor;
  return true;
}

}  // namespace local_ee_s2
