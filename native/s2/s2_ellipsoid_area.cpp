#include "s2_ellipsoid_math_internal.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <string>
#include <vector>

namespace local_ee_s2 {
namespace {

using ellipsoid_internal::Arc;
using ellipsoid_internal::CompensatedSum;
using ellipsoid_internal::QuadratureLevels;

constexpr long double kWgs84A = 6378137.0L;
constexpr long double kWgs84Flattening = 1.0L / 298.257223563L;
constexpr long double kWgs84E2 =
    kWgs84Flattening * (2.0L - kWgs84Flattening);
constexpr int kAreaSeriesTerms = 16;
constexpr long double kCenteredChartLocalizationRadius = 0.01L;

long double Eccentricity() { return std::sqrt(kWgs84E2); }

long double AreaScale() {
  const long double prefactor =
      kWgs84A * kWgs84A * (1.0L - kWgs84E2) / 2.0L;
  const long double e = Eccentricity();
  return prefactor *
         (1.0L / (1.0L - kWgs84E2) + std::atanh(e) / e);
}

long double TotalEllipsoidArea() {
  return 4.0L * ellipsoid_internal::Pi() * AreaScale();
}

long double AreaCorrectionQuotient(long double sine_latitude) {
  if (sine_latitude == 0.0L) return 0.0L;
  // H(s) = (Q(s) - Q(1) * s) / (1 - s^2). Its convergent e^2 series
  // avoids subtracting nearly equal O(1) terms and remains regular at poles.
  // Sixteen terms leave less than 7.6e-23 m^2 of omitted-series tail over
  // |s| <= 1; this bound covers truncation only, not quadrature error.
  long double series = 0.0L;
  long double even_power = 1.0L;
  long double geometric_sum = 1.0L;
  long double eccentricity_power = kWgs84E2;
  const long double sine_squared = sine_latitude * sine_latitude;
  for (int n = 1; n <= kAreaSeriesTerms; ++n) {
    const long double coefficient =
        static_cast<long double>(n + 1) / (2.0L * n + 1.0L);
    series += coefficient * eccentricity_power * geometric_sum;
    even_power *= sine_squared;
    geometric_sum += even_power;
    eccentricity_power *= kWgs84E2;
  }
  return -kWgs84A * kWgs84A * (1.0L - kWgs84E2) * sine_latitude * series;
}

long double AreaCorrectionValue(long double sine_latitude) {
  return AreaCorrectionQuotient(sine_latitude) *
         (1.0L - sine_latitude * sine_latitude);
}

long double CenteredAreaCorrection(long double sine_latitude,
                                   long double reference_sine,
                                   long double stable_delta) {
  if (stable_delta == 0.0L) return 0.0L;
  // C(s) - C(r) = K (s-r) sum[n>=1] b_n q^n (P_2n(s,r) - 1),
  // where P_m = sum[j=0..m] s^(m-j) r^j. The n=0 term cancels exactly.
  // Sixteen terms leave less than 1.6e-22 m^2 of omitted-series tail for
  // |s|, |r| <= 1; this bound covers truncation only, not quadrature error.
  long double sum = 0.0L;
  long double divided_difference = 1.0L;
  long double sine_power = 1.0L;
  long double eccentricity_power = kWgs84E2;
  for (int degree = 1; degree <= 2 * kAreaSeriesTerms; ++degree) {
    sine_power *= sine_latitude;
    divided_difference =
        sine_power + reference_sine * divided_difference;
    if (degree % 2 != 0) continue;
    const int n = degree / 2;
    const long double coefficient =
        static_cast<long double>(n + 1) / (2.0L * n + 1.0L);
    sum += coefficient * eccentricity_power *
           (divided_difference - 1.0L);
    eccentricity_power *= kWgs84E2;
  }
  return kWgs84A * kWgs84A * (1.0L - kWgs84E2) * stable_delta * sum;
}

long double DirectAreaIntegrand(const Arc& arc, long double t, const void*) {
  const long double sine_latitude =
      std::max(-1.0L, std::min(1.0L, ellipsoid_internal::ArcZ(arc, t)));
  return AreaCorrectionQuotient(sine_latitude) * arc.longitude_rate;
}

struct CenteredAreaContext {
  long double sine;
  long double latitude_radians;
  double latitude_degrees;
};

long double CenteredAreaIntegrand(const Arc& arc, long double t,
                                  const void* context) {
  const auto& reference = *static_cast<const CenteredAreaContext*>(context);
  const long double start_latitude =
      static_cast<long double>(arc.start.latitude) *
      ellipsoid_internal::Pi() / 180.0L;
  const long double latitude_difference =
      static_cast<long double>(arc.start.latitude) -
      static_cast<long double>(reference.latitude_degrees);
  const long double stable_start_delta =
      latitude_difference == 0.0L
          ? 0.0L
          : 2.0L *
                std::cos((start_latitude + reference.latitude_radians) / 2.0L) *
                std::sin(latitude_difference * ellipsoid_internal::Pi() /
                         360.0L);
  const long double stable_delta =
      stable_start_delta + ellipsoid_internal::ArcZDifference(arc, t);
  const long double sine_latitude =
      std::max(-1.0L, std::min(
                           1.0L, arc.z0 +
                                     ellipsoid_internal::ArcZDifference(arc, t)));
  const long double horizontal2 = ellipsoid_internal::ArcHorizontal2(arc, t);
  if (horizontal2 == 0.0L) return 0.0L;
  return CenteredAreaCorrection(sine_latitude, reference.sine, stable_delta) *
         arc.longitude_rate / horizontal2;
}

bool NearPoleOnArc(const Arc& arc) {
  long double maximum_absolute_sine =
      std::max(std::fabs(ellipsoid_internal::ArcZ(arc, 0.0L)),
               std::fabs(ellipsoid_internal::ArcZ(arc, arc.angle)));
  const long double extremum = std::atan2(arc.uz, arc.z0);
  for (int k = -2; k <= 2; ++k) {
    const long double t = extremum + k * ellipsoid_internal::Pi();
    if (t < 0.0L || t > arc.angle) continue;
    maximum_absolute_sine =
        std::max(maximum_absolute_sine,
                 std::fabs(ellipsoid_internal::ArcZ(arc, t)));
  }
  return 1.0L - maximum_absolute_sine * maximum_absolute_sine < 1.0e-6L;
}

bool LoopNeedsDirectAreaChart(const std::vector<Coordinate>& loop,
                              bool* use_direct, std::string* error) {
  if (use_direct == nullptr) {
    return ellipsoid_internal::Fail(error, "WGS84 area chart state is null");
  }
  *use_direct = false;
  // Centering suppresses cancellation for a small local loop. For broader
  // loops, use H(s) directly: it avoids the 1/cos(latitude)^2 factor in the
  // centered integrand. The 0.01-radian locality threshold is a bounded
  // numerical chart policy, not a formal quadrature error certificate.
  const Coordinate reference = loop[0];
  for (size_t i = 1; i < loop.size(); ++i) {
    const Coordinate& vertex = loop[i];
    if (vertex.longitude == reference.longitude &&
        vertex.latitude == reference.latitude) {
      continue;
    }
    Arc from_reference;
    if (!ellipsoid_internal::BuildArc(reference, vertex, &from_reference,
                                      nullptr) ||
        from_reference.angle > kCenteredChartLocalizationRadius) {
      *use_direct = true;
      return true;
    }
  }
  for (size_t i = 0; i < loop.size(); ++i) {
    const Coordinate& start = loop[i];
    const Coordinate& end = loop[(i + 1) % loop.size()];
    if (std::fabs(start.latitude) == 90.0 ||
        std::fabs(end.latitude) == 90.0) {
      *use_direct = true;
      return true;
    }
    Arc arc;
    if (!ellipsoid_internal::BuildArc(start, end, &arc, error)) return false;
    if (NearPoleOnArc(arc)) {
      *use_direct = true;
      return true;
    }
  }
  return true;
}

bool MeasureLoopAreaCorrection(const std::vector<Coordinate>& loop,
                               bool use_centered_chart,
                               long double* correction, std::string* error) {
  if (loop.size() < 3 || correction == nullptr) {
    return ellipsoid_internal::Fail(error,
                                    "WGS84 area loop state is invalid");
  }
  CompensatedSum line_integral;
  CompensatedSum longitude_change;
  const long double reference_latitude =
      static_cast<long double>(loop[0].latitude) *
      ellipsoid_internal::Pi() / 180.0L;
  const long double reference_sine =
      loop[0].latitude == 90.0
          ? 1.0L
          : loop[0].latitude == -90.0 ? -1.0L
                                      : std::sin(reference_latitude);
  const CenteredAreaContext context{reference_sine, reference_latitude,
                                    loop[0].latitude};
  for (size_t i = 0; i < loop.size(); ++i) {
    Arc arc;
    if (!ellipsoid_internal::BuildArc(
            loop[i], loop[(i + 1) % loop.size()], &arc, error)) {
      return false;
    }
    if (use_centered_chart) {
      longitude_change.Add(arc.longitude_change);
    }
    const QuadratureLevels values =
        use_centered_chart
            ? ellipsoid_internal::IntegrateArc(
                  arc, CenteredAreaIntegrand, &context)
            : ellipsoid_internal::IntegrateArc(
                  arc, DirectAreaIntegrand, nullptr);
    if (!ellipsoid_internal::Converged(values, 1.0e-20L, 5.0e-16L)) {
      return ellipsoid_internal::Fail(
          error, "WGS84 area quadrature did not converge within 56 evaluations per edge");
    }
    line_integral.Add(values.four);
  }

  long double result = line_integral.Value();
  if (use_centered_chart) {
    const long double turns =
        longitude_change.Value() / (2.0L * ellipsoid_internal::Pi());
    const long double winding = std::round(turns);
    if (std::fabs(turns - winding) > 1.0e-9L) {
      return ellipsoid_internal::Fail(
          error, "WGS84 polygon longitude winding is numerically unresolved");
    }
    result += AreaCorrectionValue(reference_sine) *
              (2.0L * ellipsoid_internal::Pi() * winding);
  }
  *correction = result;
  return true;
}

}  // namespace

bool MeasureWgs84PolygonArea(const S2Polygon& polygon,
                             const Wgs84PolygonLoops& loops,
                             long double* area, std::string* error) {
  if (area == nullptr || error == nullptr) {
    return ellipsoid_internal::Fail(error, "WGS84 area output state is null");
  }
  if (polygon.is_full()) {
    *area = TotalEllipsoidArea();
    return true;
  }
  if (polygon.is_empty()) {
    *area = 0.0L;
    return true;
  }
  if (loops.size() != static_cast<size_t>(polygon.num_loops())) {
    return ellipsoid_internal::Fail(
        error, "WGS84 polygon loop mapping does not match validated topology");
  }

  CompensatedSum spherical_area;
  CompensatedSum boundary_correction;
  for (size_t loop_index = 0; loop_index < loops.size(); ++loop_index) {
    const S2Loop* s2_loop = polygon.loop(static_cast<int>(loop_index));
    const std::vector<Coordinate>& loop = loops[loop_index];
    if (loop.size() != static_cast<size_t>(s2_loop->num_vertices())) {
      return ellipsoid_internal::Fail(
          error, "WGS84 coordinate map does not match an S2 polygon loop");
    }
    long double loop_spherical_area = 0.0L;
    const bool represents_large_side =
        s2_loop->GetArea() >
        2.0 * static_cast<double>(ellipsoid_internal::Pi());
    if (!ellipsoid_internal::SphericalLoopArea(
            loop, represents_large_side, &loop_spherical_area, error)) {
      return false;
    }
    bool direct_chart = false;
    if (!LoopNeedsDirectAreaChart(loop, &direct_chart, error)) return false;
    long double loop_correction = 0.0L;
    if (!MeasureLoopAreaCorrection(loop, !direct_chart, &loop_correction,
                                   error)) {
      return false;
    }
    const long double sign = static_cast<long double>(s2_loop->sign());
    spherical_area.Add(sign * loop_spherical_area);
    boundary_correction.Add(sign * loop_correction);
  }
  *area = AreaScale() * spherical_area.Value() -
          boundary_correction.Value();
  if (!std::isfinite(*area) || *area < 0.0L ||
      *area > TotalEllipsoidArea() * (1.0L + 1.0e-12L)) {
    return ellipsoid_internal::Fail(
        error, "WGS84 polygon area is numerically unresolved");
  }
  return true;
}

}  // namespace local_ee_s2
