#include "s2_ellipsoid_math_internal.h"

#include <cmath>
#include <string>
#include <vector>

namespace local_ee_s2 {
namespace ellipsoid_internal {
namespace {

struct LocalPoint {
  long double dot;
  long double east;
  long double north;
};

bool SameCoordinate(Coordinate left, Coordinate right) {
  left = CanonicalizeCoordinate(left);
  right = CanonicalizeCoordinate(right);
  return left.longitude == right.longitude &&
         left.latitude == right.latitude;
}

long double WrappedLongitudeDifferenceDegrees(Coordinate start,
                                              Coordinate end) {
  long double degrees = static_cast<long double>(end.longitude) -
                        static_cast<long double>(start.longitude);
  if (degrees > 180.0L) {
    degrees = (static_cast<long double>(end.longitude) - 180.0L) -
              (static_cast<long double>(start.longitude) + 180.0L);
  } else if (degrees < -180.0L) {
    degrees = (180.0L - static_cast<long double>(start.longitude)) +
              (static_cast<long double>(end.longitude) + 180.0L);
  }
  return degrees;
}

LocalPoint RelativePoint(Coordinate anchor, Coordinate point) {
  const long double radians = Pi() / 180.0L;
  const long double anchor_latitude =
      static_cast<long double>(anchor.latitude) * radians;
  const long double point_latitude =
      static_cast<long double>(point.latitude) * radians;
  const long double delta_latitude =
      (static_cast<long double>(point.latitude) -
       static_cast<long double>(anchor.latitude)) * radians;
  const long double delta_longitude_degrees =
      WrappedLongitudeDifferenceDegrees(anchor, point);
  const long double delta_longitude =
      delta_longitude_degrees * Pi() / 180.0L;
  const long double one_minus_cos_lon =
      delta_longitude_degrees == 0.0L
          ? 0.0L
          : std::fabs(delta_longitude_degrees) == 180.0L
                ? 2.0L
                : 2.0L * std::sin(delta_longitude / 2.0L) *
                      std::sin(delta_longitude / 2.0L);
  const long double sin_delta_longitude =
      delta_longitude_degrees == 0.0L ||
              std::fabs(delta_longitude_degrees) == 180.0L
          ? 0.0L
          : std::sin(delta_longitude);
  const long double sin_anchor =
      anchor.latitude == 90.0
          ? 1.0L
          : anchor.latitude == -90.0 ? -1.0L : std::sin(anchor_latitude);
  const long double cos_anchor =
      std::fabs(anchor.latitude) == 90.0 ? 0.0L
                                         : std::cos(anchor_latitude);
  const long double cos_point =
      std::fabs(point.latitude) == 90.0 ? 0.0L
                                        : std::cos(point_latitude);
  const long double delta_latitude_degrees =
      static_cast<long double>(point.latitude) -
      static_cast<long double>(anchor.latitude);
  long double sin_delta_latitude = std::sin(delta_latitude);
  long double cos_delta_latitude = std::cos(delta_latitude);
  if (delta_latitude_degrees == 0.0L) {
    sin_delta_latitude = 0.0L;
    cos_delta_latitude = 1.0L;
  } else if (std::fabs(delta_latitude_degrees) == 180.0L) {
    sin_delta_latitude = 0.0L;
    cos_delta_latitude = -1.0L;
  }
  return {
      cos_delta_latitude -
          cos_anchor * cos_point * one_minus_cos_lon,
      cos_point * sin_delta_longitude,
      sin_delta_latitude +
          sin_anchor * cos_point * one_minus_cos_lon};
}

bool AddTriangleSolidAngle(const LocalPoint& first, const LocalPoint& second,
                           CompensatedSum* sum) {
  const long double determinant =
      first.east * second.north - first.north * second.east;
  const long double denominator =
      1.0L + first.dot + first.dot * second.dot +
      first.east * second.east + first.north * second.north + second.dot;
  if (determinant == 0.0L && denominator == 0.0L) return false;
  sum->Add(2.0L * std::atan2(determinant, denominator));
  return true;
}

bool VertexFanArea(const std::vector<Coordinate>& loop, long double* result) {
  std::vector<LocalPoint> points;
  points.reserve(loop.size());
  points.push_back({1.0L, 0.0L, 0.0L});
  for (size_t i = 1; i < loop.size(); ++i) {
    points.push_back(RelativePoint(loop[0], loop[i]));
  }
  CompensatedSum sum;
  for (size_t i = 1; i + 1 < points.size(); ++i) {
    if (!AddTriangleSolidAngle(points[i], points[i + 1], &sum)) return false;
  }
  *result = sum.Value();
  return true;
}

bool InteriorFanArea(const std::vector<Coordinate>& loop, Coordinate anchor,
                     long double* result) {
  CompensatedSum sum;
  for (size_t i = 0; i < loop.size(); ++i) {
    const LocalPoint first = RelativePoint(anchor, loop[i]);
    const LocalPoint second =
        RelativePoint(anchor, loop[(i + 1) % loop.size()]);
    if (!AddTriangleSolidAngle(first, second, &sum)) return false;
  }
  *result = sum.Value();
  return true;
}

}  // namespace

bool SphericalLoopArea(const std::vector<Coordinate>& loop,
                       bool represents_large_side, long double* area,
                       std::string* error) {
  if (loop.size() < 3 || area == nullptr) {
    return Fail(error, "WGS84 spherical loop state is invalid");
  }
  long double fan_area = 0.0L;
  bool resolved = VertexFanArea(loop, &fan_area);
  const Coordinate fallback_anchors[] = {
      {0.0, 90.0}, {0.0, -90.0}, {13.0, 0.0}, {-71.0, 23.0},
      {109.0, -37.0}, {-149.0, 61.0}};
  for (const Coordinate anchor : fallback_anchors) {
    if (resolved) break;
    bool is_vertex = false;
    for (const Coordinate vertex : loop) {
      if (SameCoordinate(vertex, anchor)) {
        is_vertex = true;
        break;
      }
    }
    if (!is_vertex) resolved = InteriorFanArea(loop, anchor, &fan_area);
  }
  if (!resolved) {
    return Fail(error, "WGS84 spherical loop fan is numerically unresolved");
  }
  const long double four_pi = 4.0L * Pi();
  const long double signed_area = std::remainder(fan_area, four_pi);
  if (!std::isfinite(signed_area) ||
      std::fabs(signed_area) > 2.0L * Pi() + 1.0e-9L) {
    return Fail(error, "WGS84 spherical loop area branch is numerically unresolved");
  }
  const long double minor_area = std::fabs(signed_area);
  *area = represents_large_side ? four_pi - minor_area : minor_area;
  return true;
}

}  // namespace ellipsoid_internal
}  // namespace local_ee_s2
