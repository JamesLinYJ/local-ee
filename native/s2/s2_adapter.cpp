#include "s2_adapter.h"

#include "s2_internal.h"

#include <cstdio>
#include <exception>
#include <new>
#include <string>

#include "s2/s2boolean_operation.h"

namespace local_ee_s2 {
namespace {

enum Status {
  kOk = 0,
  kInvalidCall = 1,
  kInvalidWire = 2,
  kInvalidGeometry = 3,
  kResourceLimit = 4,
  kOutputLimit = 5,
  kInternalError = 6,
};

void StoreError(char* output, size_t capacity, const std::string& message) {
  if (output == nullptr || capacity == 0) return;
  std::snprintf(output, capacity, "%s", message.c_str());
  output[capacity - 1] = '\0';
}

bool HasMemoryError(const S2MemoryTracker& tracker) {
  return tracker.error().code() == S2Error::RESOURCE_EXHAUSTED;
}

bool EvaluatePredicate(int op, const S2ShapeIndex& left,
                       const S2ShapeIndex& right, S2MemoryTracker* tracker,
                       bool* value, std::string* error) {
  S2BooleanOperation::Options options;
  options.set_polygon_model(S2BooleanOperation::PolygonModel::CLOSED);
  options.set_polyline_model(S2BooleanOperation::PolylineModel::CLOSED);
  options.set_memory_tracker(tracker);

  switch (op) {
    case 0:
      *value = S2BooleanOperation::Contains(left, right, options);
      break;
    case 1:
      *value = S2BooleanOperation::Contains(right, left, options);
      break;
    case 2:
      *value = S2BooleanOperation::Intersects(left, right, options);
      break;
    case 3:
      *value = !S2BooleanOperation::Intersects(left, right, options);
      break;
    default:
      *error = "predicate operation code is invalid";
      return false;
  }
  if (HasMemoryError(*tracker)) {
    *error = "S2 memory tracker exceeded the 64 MiB limit";
    return false;
  }
  return true;
}

bool MakeIndex(const ParsedGeometry& parsed, S2MemoryTracker* tracker,
               MutableS2ShapeIndex* index, S2LatLngRect* bounds,
               std::string* error) {
  if (BuildShapeIndex(parsed, tracker, index, bounds, error)) return true;
  if (HasMemoryError(*tracker)) {
    *error = "S2 memory tracker exceeded the 64 MiB limit";
  }
  return false;
}

int Run(int op, const double* left_data, size_t left_size,
        const double* right_data, size_t right_size, double* output,
        size_t output_capacity, size_t* output_size, std::string* error) {
  if (op < 0 || op > 9) {
    *error = "operation code must be in the range 0 through 9";
    return kInvalidCall;
  }
  if (output_size == nullptr) {
    *error = "output_size is required";
    return kInvalidCall;
  }
  *output_size = 0;
  if (output_capacity > kMaxOutputDoubles) {
    *error = "output_capacity exceeds 65536 doubles";
    return kInvalidCall;
  }
  if (output_capacity != 0 && output == nullptr) {
    *error = "output pointer is null for nonzero capacity";
    return kInvalidCall;
  }
  const bool validate_only = op == 8;
  const bool bounds_only = op == 9;
  const bool unary = validate_only || bounds_only;
  if (bounds_only && (output_capacity < 8 || output == nullptr)) {
    *error = "bounds result requires eight output doubles";
    return kOutputLimit;
  }
  if (!unary && (right_data == nullptr || right_size < 2)) {
    *error = "right geometry is required for this operation";
    return kInvalidCall;
  }

  ParsedGeometry left_wire;
  if (!ParseWire(left_data, left_size, &left_wire, error)) {
    return kInvalidWire;
  }
  ParsedGeometry right_wire;
  if (!unary && !ParseWire(right_data, right_size, &right_wire, error)) {
    return kInvalidWire;
  }
  if (!CheckCallBudget(left_wire, unary ? nullptr : &right_wire, error)) {
    return kResourceLimit;
  }

  S2MemoryTracker tracker;
  tracker.set_limit_bytes(kMaxTrackedBytes);
  MutableS2ShapeIndex left_index;
  S2LatLngRect left_bounds;
  if (!MakeIndex(left_wire, &tracker, &left_index,
                 bounds_only ? &left_bounds : nullptr, error)) {
    return HasMemoryError(tracker) ? kResourceLimit : kInvalidGeometry;
  }
  if (validate_only) {
    if (output_capacity < 1 || output == nullptr) {
      *error = "validation result requires one output double";
      return kOutputLimit;
    }
    output[0] = 1.0;
    *output_size = 1;
    return kOk;
  }
  if (bounds_only) {
    if (HasMemoryError(tracker)) {
      *error = "S2 memory tracker exceeded the 64 MiB limit";
      return kResourceLimit;
    }
    if (!PackBounds(left_bounds, output, error)) return kInvalidGeometry;
    *output_size = 8;
    return kOk;
  }

  MutableS2ShapeIndex right_index;
  if (!MakeIndex(right_wire, &tracker, &right_index, nullptr, error)) {
    return HasMemoryError(tracker) ? kResourceLimit : kInvalidGeometry;
  }
  GeometryOutput result;
  if (op <= 3) {
    bool value = false;
    if (!EvaluatePredicate(op, left_index, right_index, &tracker, &value,
                           error)) {
      return HasMemoryError(tracker) ? kResourceLimit : kInvalidGeometry;
    }
    if (output_capacity < 1 || output == nullptr) {
      *error = "predicate result requires one output double";
      return kOutputLimit;
    }
    output[0] = value ? 1.0 : 0.0;
    *output_size = 1;
    return kOk;
  }

  if (!RunOverlay(op, left_index, right_index, &tracker, &result, error)) {
    if (HasMemoryError(tracker)) {
      *error = "S2 memory tracker exceeded the 64 MiB limit";
      return kResourceLimit;
    }
    return kInvalidGeometry;
  }
  if (!PackOutput(result, left_wire, &right_wire, output, output_capacity,
                  output_size, error)) {
    return kOutputLimit;
  }
  return kOk;
}

}  // namespace
}  // namespace local_ee_s2

extern "C" LOCAL_EE_S2_EXPORT int local_ee_s2_run(
    int op, const double* left, size_t left_size, const double* right,
    size_t right_size, double* output, size_t output_capacity,
    size_t* output_size, char* error, size_t error_capacity) {
  if (output_size != nullptr) *output_size = 0;
  if (error != nullptr && error_capacity != 0) error[0] = '\0';
  if (output_size == nullptr) {
    local_ee_s2::StoreError(error, error_capacity, "output_size is required");
    return local_ee_s2::kInvalidCall;
  }
  try {
    std::string message;
    const int status = local_ee_s2::Run(
        op, left, left_size, right, right_size, output, output_capacity,
        output_size, &message);
    if (status != local_ee_s2::kOk) {
      *output_size = 0;
      local_ee_s2::StoreError(error, error_capacity, message);
    }
    return status;
  } catch (const std::bad_alloc&) {
    *output_size = 0;
    local_ee_s2::StoreError(error, error_capacity,
                            "native geometry allocation failed");
    return local_ee_s2::kResourceLimit;
  } catch (const std::exception&) {
    *output_size = 0;
    local_ee_s2::StoreError(error, error_capacity,
                            "native geometry operation failed");
    return local_ee_s2::kInternalError;
  } catch (...) {
    *output_size = 0;
    local_ee_s2::StoreError(error, error_capacity,
                            "native geometry operation failed");
    return local_ee_s2::kInternalError;
  }
}
