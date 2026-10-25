#include "s2_internal.h"

#include <cmath>
#include <limits>
#include <utility>

namespace local_ee_s2 {
namespace {

constexpr size_t kMaxInputDoubles = 2 + 3 * kMaxInputShapes +
                                    kMaxInputParts +
                                    2 * kMaxInputPositions;

bool ReadCount(double value, size_t maximum, size_t* count) {
  if (!std::isfinite(value) || value < 0 || value > maximum ||
      std::floor(value) != value) {
    return false;
  }
  *count = static_cast<size_t>(value);
  return true;
}

bool Fail(std::string* error, const char* message) {
  *error = message;
  return false;
}

bool AddChecked(size_t amount, size_t* total) {
  if (amount > std::numeric_limits<size_t>::max() - *total) return false;
  *total += amount;
  return true;
}

bool MultiplyChecked(size_t left, size_t right, size_t* product) {
  if (left != 0 && right > std::numeric_limits<size_t>::max() / left) {
    return false;
  }
  *product = left * right;
  return true;
}

}  // namespace

bool ParseWire(const double* data, size_t size, ParsedGeometry* parsed,
               std::string* error) {
  if (data == nullptr || parsed == nullptr || error == nullptr) {
    return Fail(error, "wire input or parser output is null");
  }
  if (size < 2 || size > kMaxInputDoubles) {
    return Fail(error, "wire size is outside the v1 input limit");
  }
  if (data[0] != 1.0) return Fail(error, "unsupported geometry wire version");

  size_t shape_count = 0;
  if (!ReadCount(data[1], kMaxInputShapes, &shape_count)) {
    return Fail(error, "shape count is invalid or exceeds 1000");
  }

  ParsedGeometry value;
  value.shapes.reserve(shape_count);
  size_t cursor = 2;
  for (size_t shape_index = 0; shape_index < shape_count; ++shape_index) {
    if (cursor > size || size - cursor < 3) {
      return Fail(error, "truncated geometry shape header");
    }
    size_t kind_value = 0;
    size_t even_odd_value = 0;
    size_t part_count = 0;
    if (!ReadCount(data[cursor], 2, &kind_value)) {
      return Fail(error, "shape kind is invalid");
    }
    if (!ReadCount(data[cursor + 1], 1, &even_odd_value)) {
      return Fail(error, "evenOdd flag is invalid");
    }
    if (!ReadCount(data[cursor + 2], kMaxInputParts, &part_count)) {
      return Fail(error, "part count is invalid or exceeds 10000");
    }
    cursor += 3;

    ShapeView shape;
    shape.kind = static_cast<ShapeKind>(kind_value);
    shape.even_odd = even_odd_value != 0;
    if (shape.kind != ShapeKind::kPolygon && shape.even_odd) {
      return Fail(error, "evenOdd is only supported for polygons");
    }
    if (shape.kind == ShapeKind::kPoints || shape.kind == ShapeKind::kLine) {
      if (part_count != 1) {
        return Fail(error, "point and line shapes require exactly one part");
      }
    }
    if (value.part_count > kMaxInputParts - part_count) {
      return Fail(error, "geometry has more than 10000 parts");
    }
    value.part_count += part_count;
    shape.parts.reserve(part_count);
    for (size_t part_index = 0; part_index < part_count; ++part_index) {
      if (cursor >= size) return Fail(error, "truncated geometry part count");
      size_t vertex_count = 0;
      if (!ReadCount(data[cursor], kMaxInputPositions, &vertex_count)) {
        return Fail(error, "part vertex count is invalid or exceeds 10000");
      }
      ++cursor;
      if (value.position_count > kMaxInputPositions - vertex_count) {
        return Fail(error, "geometry has more than 10000 positions");
      }
      if (vertex_count > (size - cursor) / 2) {
        return Fail(error, "truncated geometry coordinates");
      }
      PartView part{data + cursor, vertex_count};
      shape.parts.push_back(part);
      cursor += 2 * vertex_count;
      shape.position_count += vertex_count;
      value.position_count += vertex_count;
      if (shape.kind == ShapeKind::kLine && vertex_count == 1) {
        return Fail(error, "a non-empty line requires at least two positions");
      }
      if (shape.kind == ShapeKind::kPolygon && vertex_count != 0 &&
          vertex_count < 3) {
        return Fail(error, "polygon loops require at least three positions");
      }
      if (shape.kind == ShapeKind::kLine && vertex_count > 1) {
        shape.edge_count += vertex_count - 1;
      } else if (shape.kind == ShapeKind::kPolygon && vertex_count > 0) {
        shape.edge_count += vertex_count;
      }
    }
    if (shape.kind == ShapeKind::kPolygon) {
      const bool full_sentinel = shape.parts.size() == 1 &&
                                 shape.parts[0].vertex_count == 0 &&
                                 !shape.even_odd;
      for (const PartView& part : shape.parts) {
        if (part.vertex_count == 0 && !full_sentinel) {
          return Fail(error,
                      "empty polygon loops are invalid; use the full sentinel "
                      "only for full sphere");
        }
      }
      if (full_sentinel || !shape.parts.empty()) ++value.active_shape_count;
    } else if (shape.kind == ShapeKind::kPoints) {
      if (shape.position_count != 0) ++value.active_shape_count;
    } else if (!shape.parts.empty() && shape.parts[0].vertex_count >= 2) {
      ++value.active_shape_count;
    }
    value.edge_count += shape.edge_count;
    value.shapes.push_back(std::move(shape));
  }
  if (cursor != size) return Fail(error, "geometry wire has trailing values");

  // All structural sizes are known and range checked before reading any
  // coordinate values or constructing S2 objects.
  for (const ShapeView& shape : value.shapes) {
    for (const PartView& part : shape.parts) {
      for (size_t i = 0; i < part.vertex_count; ++i) {
        const double longitude = part.coordinates[2 * i];
        const double latitude = part.coordinates[2 * i + 1];
        if (!std::isfinite(longitude) || !std::isfinite(latitude)) {
          return Fail(error, "geometry coordinates must be finite");
        }
        if (longitude < -180 || longitude > 180 || latitude < -90 ||
            latitude > 90) {
          return Fail(error, "longitude or latitude is outside EPSG:4326 range");
        }
      }
    }
  }
  *parsed = std::move(value);
  return true;
}

bool CheckCallBudget(const ParsedGeometry& left, const ParsedGeometry* right,
                     size_t* work_out, std::string* error) {
  const size_t positions = left.position_count +
                           (right == nullptr ? 0 : right->position_count);
  const size_t shapes = left.shapes.size() +
                        (right == nullptr ? 0 : right->shapes.size());
  const size_t parts = left.part_count +
                       (right == nullptr ? 0 : right->part_count);
  const size_t edges = left.edge_count +
                       (right == nullptr ? 0 : right->edge_count);
  const size_t active = left.active_shape_count +
                        (right == nullptr ? 0 : right->active_shape_count);
  if (positions > kMaxInputPositions) {
    return Fail(error, "combined geometry has more than 10000 positions");
  }
  if (shapes > kMaxInputShapes) {
    return Fail(error, "combined geometry has more than 1000 shapes");
  }
  if (parts > kMaxInputParts) {
    return Fail(error, "combined geometry has more than 10000 parts");
  }
  size_t base = positions;
  if (!AddChecked(edges, &base) || !AddChecked(1, &base)) {
    return Fail(error, "geometry work estimate overflowed");
  }
  size_t base_square = 0;
  size_t active_stages = active;
  size_t position_square = 0;
  size_t work = 0;
  if (!MultiplyChecked(base, base, &base_square) ||
      !AddChecked(1, &active_stages) ||
      !MultiplyChecked(base_square, active_stages, &work) ||
      !MultiplyChecked(positions, positions, &position_square) ||
      !AddChecked(position_square, &work)) {
    return Fail(error, "geometry work estimate overflowed");
  }
  size_t overhead = 0;
  if (!MultiplyChecked(edges, 4, &overhead) || !AddChecked(overhead, &work) ||
      !MultiplyChecked(active, 4, &overhead) || !AddChecked(overhead, &work) ||
      !AddChecked(parts, &work)) {
    return Fail(error, "geometry work estimate overflowed");
  }
  if (work > kMaxWork) {
    return Fail(error, "geometry operation exceeds the 50000-work limit");
  }
  if (work_out != nullptr) *work_out = work;
  return true;
}

}  // namespace local_ee_s2
