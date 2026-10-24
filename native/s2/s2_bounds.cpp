#include "s2_internal.h"

#include <algorithm>
#include <cmath>
#include <tuple>
#include <utility>
#include <vector>

#include "s2/s2latlng.h"

namespace local_ee_s2 {
namespace {

constexpr double kPi = 3.141592653589793238462643383279502884;
constexpr double kRadiansToDegrees = 180.0 / kPi;

struct LinearInterval {
  double start;
  double end;
};

double CanonicalLongitude(double longitude) {
  return longitude == kPi ? -kPi : longitude;
}

// Wire preflight caps the scratch to at most 10,000 point intervals plus two
// intervals for each of at most 1,000 normalized regions: 12,000 records, or
// 187.5 KiB of LinearInterval storage. Output bounds are only accumulated after
// EstimateWireSize has enforced the normalized output caps.
class BoundsAccumulator {
 public:
  explicit BoundsAccumulator(size_t interval_capacity = 0) {
    intervals_.reserve(interval_capacity);
  }

  void AddPoint(const S2Point& point) {
    const double latitude = S2LatLng::Latitude(point).radians();
    const double longitude = S2LatLng::Longitude(point).radians();
    AddLatitude(latitude, latitude);
    AddLongitude(S1Interval::FromPoint(longitude));
  }

  void AddRegion(const S2LatLngRect& region) {
    if (region.is_empty()) return;
    AddLatitude(region.lat_lo().radians(), region.lat_hi().radians());
    AddLongitude(region.lng());
  }

  S2LatLngRect GetBounds() {
    if (!has_bounds_) return S2LatLngRect::Empty();
    if (full_longitude_ || intervals_.empty()) {
      return S2LatLngRect(R1Interval(south_, north_), S1Interval::Full())
          .PolarClosure();
    }

    std::sort(intervals_.begin(), intervals_.end(),
              [](const LinearInterval& left, const LinearInterval& right) {
                if (left.start != right.start) return left.start < right.start;
                return left.end < right.end;
              });
    size_t merged_count = 0;
    for (size_t i = 0; i < intervals_.size(); ++i) {
      const LinearInterval interval = intervals_[i];
      if (merged_count == 0 ||
          interval.start > intervals_[merged_count - 1].end) {
        intervals_[merged_count++] = interval;
      } else if (interval.end > intervals_[merged_count - 1].end) {
        intervals_[merged_count - 1].end = interval.end;
      }
    }
    intervals_.resize(merged_count);

    if (intervals_.size() == 1 && intervals_[0].start == -kPi &&
        intervals_[0].end == kPi) {
      return S2LatLngRect(R1Interval(south_, north_), S1Interval::Full())
          .PolarClosure();
    }

    double largest_gap = -1.0;
    double best_west_longitude = 0.0;
    double best_east_longitude = 0.0;
    double best_west_key = 0.0;
    double best_east_key = 0.0;
    auto consider_gap = [&](double gap, double west_longitude,
                            double east_longitude) {
      const double west_key = CanonicalLongitude(west_longitude);
      const double east_key = CanonicalLongitude(east_longitude);
      const bool canonical_tie =
          west_key == best_west_key && east_key == best_east_key;
      const bool canonical_less =
          std::tie(west_key, east_key) <
          std::tie(best_west_key, best_east_key);
      const bool raw_less =
          std::tie(west_longitude, east_longitude) <
          std::tie(best_west_longitude, best_east_longitude);
      if (gap > largest_gap ||
          (gap == largest_gap &&
           (canonical_less || (canonical_tie && raw_less)))) {
        largest_gap = gap;
        best_west_longitude = west_longitude;
        best_east_longitude = east_longitude;
        best_west_key = west_key;
        best_east_key = east_key;
      }
    };

    for (size_t i = 0; i + 1 < intervals_.size(); ++i) {
      consider_gap(intervals_[i + 1].start - intervals_[i].end,
                   intervals_[i + 1].start, intervals_[i].end);
    }
    // Measure the circular gap as the sum of its distances to the seam.
    // This avoids adding 2*pi to a value near -pi, which would discard low
    // longitude bits for very narrow intervals.
    const double circular_gap =
        (intervals_.front().start + kPi) + (kPi - intervals_.back().end);
    consider_gap(circular_gap, intervals_.front().start,
                 intervals_.back().end);

    if (largest_gap <= 0.0) {
      return S2LatLngRect(R1Interval(south_, north_), S1Interval::Full())
          .PolarClosure();
    }

    return S2LatLngRect(R1Interval(south_, north_),
                        S1Interval(best_west_longitude,
                                   best_east_longitude))
        .PolarClosure();
  }

 private:
  void AddLatitude(double south, double north) {
    if (!has_bounds_) {
      south_ = south;
      north_ = north;
      has_bounds_ = true;
    } else {
      south_ = std::min(south_, south);
      north_ = std::max(north_, north);
    }
  }

  void AddLongitude(const S1Interval& longitude) {
    if (full_longitude_ || longitude.is_empty()) return;
    if (longitude.is_full()) {
      full_longitude_ = true;
      return;
    }
    const double start = longitude.lo();
    const double end = longitude.hi();
    if (start <= end) {
      intervals_.push_back({start, end});
    } else {
      intervals_.push_back({-kPi, end});
      intervals_.push_back({start, kPi});
    }
  }

  std::vector<LinearInterval> intervals_;
  double south_ = 0.0;
  double north_ = 0.0;
  bool has_bounds_ = false;
  bool full_longitude_ = false;
};

}  // namespace

S2LatLngRect BoundsForPoints(const std::vector<S2Point>& points) {
  BoundsAccumulator bounds(points.size());
  for (const S2Point& point : points) bounds.AddPoint(point);
  return bounds.GetBounds();
}

S2LatLngRect BoundsForOutput(const GeometryOutput& output) {
  size_t region_count = 0;
  for (const std::unique_ptr<S2Polyline>& line : output.polylines) {
    if (line != nullptr) ++region_count;
  }
  if (!output.polygon.is_empty()) ++region_count;
  BoundsAccumulator bounds(output.points.size() + 2 * region_count);
  for (const S2Point& point : output.points) bounds.AddPoint(point);
  for (const std::unique_ptr<S2Polyline>& line : output.polylines) {
    if (line != nullptr) bounds.AddRegion(line->GetRectBound());
  }
  if (!output.polygon.is_empty()) bounds.AddRegion(output.polygon.GetRectBound());
  return bounds.GetBounds();
}

bool PackBounds(const S2LatLngRect& input, double* output,
                std::string* error) {
  const S2LatLngRect bounds = input.PolarClosure();
  if (!bounds.is_valid()) {
    *error = "S2 produced an invalid spherical envelope";
    return false;
  }
  output[0] = 1.0;
  if (bounds.is_empty()) {
    output[1] = 1.0;
    output[2] = 0.0;
    output[3] = 0.0;
    output[4] = 0.0;
    output[5] = 0.0;
    output[6] = 0.0;
    output[7] = 0.0;
    return true;
  }

  const bool full_longitude = bounds.lng().is_full();
  double west = full_longitude ? -180.0 : bounds.lng_lo().degrees();
  double east = full_longitude ? 180.0 : bounds.lng_hi().degrees();
  if (!full_longitude && west == 180.0) {
    west = -180.0;
    if (east == 180.0) east = -180.0;
  }
  const bool wrapped = !full_longitude && west > east;
  const double south = bounds.lat_lo().degrees();
  const double north = bounds.lat_hi().degrees();
  if (!std::isfinite(west) || !std::isfinite(east) ||
      !std::isfinite(south) || !std::isfinite(north) || west < -180.0 ||
      west > 180.0 || east < -180.0 || east > 180.0 || south < -90.0 ||
      north > 90.0 || south > north || (full_longitude && wrapped) ||
      (wrapped != (west > east))) {
    *error = "S2 produced out-of-range spherical envelope coordinates";
    return false;
  }

  output[1] = 0.0;
  output[2] = full_longitude ? 1.0 : 0.0;
  output[3] = wrapped ? 1.0 : 0.0;
  output[4] = west;
  output[5] = south;
  output[6] = east;
  output[7] = north;
  return true;
}

}  // namespace local_ee_s2
