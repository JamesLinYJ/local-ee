#include "s2_ellipsoid_math_internal.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <string>

namespace local_ee_s2 {
namespace ellipsoid_internal {
namespace {

constexpr long double kWgs84A = 6378137.0L;
constexpr long double kWgs84Flattening = 1.0L / 298.257223563L;
constexpr long double kWgs84E2 =
    kWgs84Flattening * (2.0L - kWgs84Flattening);

const long double kGaussX[4] = {
    0.183434642495649804939476142360184L,
    0.525532409916328985817739049189246L,
    0.796666477413626739591553936475831L,
    0.960289856497536231683560868569473L};
const long double kGaussW[4] = {
    0.362683783378361982965150449277195L,
    0.313706645877887287337962201986601L,
    0.222381034453374470544355994426240L,
    0.101228536290376259152531354309962L};

}  // namespace

long double LengthIntegrand(const Arc& arc, long double t, const void*) {
  const long double z = std::max(-1.0L, std::min(1.0L, ArcZ(arc, t)));
  const long double horizontal = std::sqrt(std::max(0.0L, ArcHorizontal2(arc, t)));
  const long double e2_sin2 = kWgs84E2 * z * z;
  const long double denominator = 1.0L - e2_sin2;
  const long double meridional =
      kWgs84A * (1.0L - kWgs84E2) /
      (denominator * std::sqrt(denominator));
  const long double prime_vertical = kWgs84A / std::sqrt(denominator);
  if (horizontal == 0.0L) return meridional;
  const long double north = ArcZDerivative(arc, t) / horizontal;
  const long double east = arc.longitude_rate / horizontal;
  return std::hypot(meridional * north, prime_vertical * east);
}

long double Pi() { return std::acos(-1.0L); }

bool Fail(std::string* error, const std::string& message) {
  if (error != nullptr) *error = message;
  return false;
}

bool BuildArc(Coordinate start, Coordinate end, Arc* arc, std::string* error) {
  if (arc == nullptr) return Fail(error, "WGS84 metric edge state is null");
  start = CanonicalizeCoordinate(start);
  end = CanonicalizeCoordinate(end);
  const long double degrees_to_radians = Pi() / 180.0L;
  const long double latitude_a =
      static_cast<long double>(start.latitude) * degrees_to_radians;
  const long double latitude_b =
      static_cast<long double>(end.latitude) * degrees_to_radians;
  const long double delta_latitude =
      (static_cast<long double>(end.latitude) -
       static_cast<long double>(start.latitude)) * degrees_to_radians;
  const long double delta_latitude_degrees =
      static_cast<long double>(end.latitude) -
      static_cast<long double>(start.latitude);
  long double delta_longitude_degrees =
      static_cast<long double>(end.longitude) -
      static_cast<long double>(start.longitude);
  if (delta_longitude_degrees > 180.0L) {
    delta_longitude_degrees =
        (static_cast<long double>(end.longitude) - 180.0L) -
        (static_cast<long double>(start.longitude) + 180.0L);
  } else if (delta_longitude_degrees < -180.0L) {
    delta_longitude_degrees =
        (180.0L - static_cast<long double>(start.longitude)) +
        (static_cast<long double>(end.longitude) + 180.0L);
  }
  const long double delta_longitude =
      delta_longitude_degrees * degrees_to_radians;
  const long double sin_a =
      start.latitude == 90.0 ? 1.0L
      : start.latitude == -90.0 ? -1.0L
                                : std::sin(latitude_a);
  const long double cos_a =
      std::fabs(start.latitude) == 90.0 ? 0.0L : std::cos(latitude_a);
  const long double cos_b =
      std::fabs(end.latitude) == 90.0 ? 0.0L : std::cos(latitude_b);
  long double sin_delta_latitude = std::sin(delta_latitude);
  long double cos_delta_latitude = std::cos(delta_latitude);
  if (delta_latitude_degrees == 0.0L) {
    sin_delta_latitude = 0.0L;
    cos_delta_latitude = 1.0L;
  } else if (std::fabs(delta_latitude_degrees) == 180.0L) {
    sin_delta_latitude = 0.0L;
    cos_delta_latitude = -1.0L;
  }
  long double sin_delta_longitude = std::sin(delta_longitude);
  long double one_minus_cos_lon =
      2.0L * std::sin(delta_longitude / 2.0L) *
      std::sin(delta_longitude / 2.0L);
  if (delta_longitude_degrees == 0.0L) {
    sin_delta_longitude = 0.0L;
    one_minus_cos_lon = 0.0L;
  } else if (std::fabs(delta_longitude_degrees) == 180.0L) {
    sin_delta_longitude = 0.0L;
    one_minus_cos_lon = 2.0L;
  }
  const long double east = cos_b * sin_delta_longitude;
  const long double north =
      sin_delta_latitude +
      sin_a * cos_b * one_minus_cos_lon;
  const long double along =
      cos_delta_latitude -
      cos_a * cos_b * one_minus_cos_lon;
  const long double tangent_norm = std::hypot(east, north);
  if (tangent_norm == 0.0L) {
    return Fail(error, "WGS84 metric edge collapses at input coordinate precision");
  }
  if (along < 0.0L &&
      tangent_norm <= 64.0L * std::numeric_limits<double>::epsilon()) {
    return Fail(error, "WGS84 metric edge is too close to antipodal to resolve");
  }

  const long double east_tangent = east / tangent_norm;
  const long double north_tangent = north / tangent_norm;
  const long double longitude_a =
      static_cast<long double>(start.longitude) * degrees_to_radians;
  const long double sin_lon = std::sin(longitude_a);
  const long double cos_lon = std::cos(longitude_a);
  const long double ux =
      -east_tangent * sin_lon -
      north_tangent * sin_a * cos_lon;
  const long double uy =
      east_tangent * cos_lon -
      north_tangent * sin_a * sin_lon;
  const long double ax = cos_a * cos_lon;
  const long double ay = cos_a * sin_lon;

  arc->start = start;
  arc->end = end;
  arc->z0 = sin_a;
  arc->cosine_latitude = cos_a;
  arc->uz = north_tangent * cos_a;
  arc->ax = ax;
  arc->ay = ay;
  arc->ux = ux;
  arc->uy = uy;
  arc->angle = std::atan2(tangent_norm, along);
  arc->longitude_rate = cos_a * east_tangent;
  arc->longitude_change = delta_longitude;
  if (std::fabs(delta_longitude_degrees) == 180.0L &&
      arc->longitude_rate != 0.0L &&
      std::signbit(arc->longitude_change) !=
          std::signbit(arc->longitude_rate)) {
    arc->longitude_change = -arc->longitude_change;
  }
  return true;
}

long double ArcZDifference(const Arc& arc, long double t) {
  const long double half_sine = std::sin(t / 2.0L);
  return -2.0L * arc.z0 * half_sine * half_sine +
         arc.uz * std::sin(t);
}

long double ArcZ(const Arc& arc, long double t) {
  return arc.z0 + ArcZDifference(arc, t);
}

long double ArcZDerivative(const Arc& arc, long double t) {
  return -arc.z0 * std::sin(t) + arc.uz * std::cos(t);
}

long double ArcHorizontal2(const Arc& arc, long double t) {
  const long double cosine = std::cos(t);
  const long double sine = std::sin(t);
  const long double x = arc.ax * cosine + arc.ux * sine;
  const long double y = arc.ay * cosine + arc.uy * sine;
  return std::max(0.0L, x * x + y * y);
}

long double Gauss8Panel(const Arc& arc, long double low, long double high,
                        Integrand function, const void* context) {
  const long double midpoint = (low + high) / 2.0L;
  const long double half = (high - low) / 2.0L;
  CompensatedSum sum;
  for (int i = 0; i < 4; ++i) {
    const long double offset = half * kGaussX[i];
    sum.Add(kGaussW[i] * function(arc, midpoint - offset, context));
    sum.Add(kGaussW[i] * function(arc, midpoint + offset, context));
  }
  return half * sum.Value();
}

long double CompositeGauss8(const Arc& arc, int panels, Integrand function,
                            const void* context) {
  CompensatedSum sum;
  for (int panel = 0; panel < panels; ++panel) {
    const long double low = arc.angle * panel / panels;
    const long double high = arc.angle * (panel + 1) / panels;
    sum.Add(Gauss8Panel(arc, low, high, function, context));
  }
  return sum.Value();
}

QuadratureLevels IntegrateArc(const Arc& arc, Integrand function,
                              const void* context) {
  return {CompositeGauss8(arc, 1, function, context),
          CompositeGauss8(arc, 2, function, context),
          CompositeGauss8(arc, 4, function, context)};
}

bool Converged(const QuadratureLevels& values, long double abs_tolerance,
               long double rel_tolerance) {
  const long double scale =
      std::max({std::fabs(values.one), std::fabs(values.two),
                std::fabs(values.four)});
  const long double tolerance = abs_tolerance + rel_tolerance * scale;
  const long double coarse_change = std::fabs(values.two - values.one);
  const long double fine_change = std::fabs(values.four - values.two);
  return fine_change <= tolerance &&
         (coarse_change <= tolerance || fine_change <= coarse_change / 2.0L);
}

}  // namespace ellipsoid_internal

bool MeasureWgs84LineLength(const PartView& line, long double* length,
                            std::string* error) {
  if (length == nullptr || error == nullptr) {
    return ellipsoid_internal::Fail(error, "WGS84 length output state is null");
  }
  ellipsoid_internal::CompensatedSum sum;
  for (size_t i = 0; i + 1 < line.vertex_count; ++i) {
    const Coordinate start{line.coordinates[i * 2], line.coordinates[i * 2 + 1]};
    const Coordinate end{line.coordinates[(i + 1) * 2],
                         line.coordinates[(i + 1) * 2 + 1]};
    ellipsoid_internal::Arc arc;
    if (!ellipsoid_internal::BuildArc(start, end, &arc, error)) return false;
    const auto values = ellipsoid_internal::IntegrateArc(
        arc, ellipsoid_internal::LengthIntegrand, nullptr);
    if (!ellipsoid_internal::Converged(values, 1.0e-10L, 1.0e-14L)) {
      return ellipsoid_internal::Fail(
          error, "WGS84 length quadrature did not converge within 56 evaluations per edge");
    }
    sum.Add(values.four);
  }
  *length = sum.Value();
  return true;
}

bool MeasureWgs84PolygonPerimeter(const S2Polygon& polygon,
                                  const Wgs84PolygonLoops& loops,
                                  long double* perimeter,
                                  std::string* error) {
  if (perimeter == nullptr || error == nullptr) {
    return ellipsoid_internal::Fail(error,
                                    "WGS84 perimeter output state is null");
  }
  if (polygon.is_full() || polygon.is_empty()) {
    *perimeter = 0.0L;
    return true;
  }
  if (loops.size() != static_cast<size_t>(polygon.num_loops())) {
    return ellipsoid_internal::Fail(
        error, "WGS84 polygon loop mapping does not match validated topology");
  }
  ellipsoid_internal::CompensatedSum sum;
  for (const auto& loop : loops) {
    if (loop.size() < 3) {
      return ellipsoid_internal::Fail(error,
                                      "WGS84 polygon loop has fewer than three vertices");
    }
    for (size_t i = 0; i < loop.size(); ++i) {
      ellipsoid_internal::Arc arc;
      if (!ellipsoid_internal::BuildArc(loop[i], loop[(i + 1) % loop.size()],
                                        &arc, error)) {
        return false;
      }
      const auto values = ellipsoid_internal::IntegrateArc(
          arc, ellipsoid_internal::LengthIntegrand, nullptr);
      if (!ellipsoid_internal::Converged(values, 1.0e-10L, 1.0e-14L)) {
        return ellipsoid_internal::Fail(
            error, "WGS84 perimeter quadrature did not converge within 56 evaluations per edge");
      }
      sum.Add(values.four);
    }
  }
  *perimeter = sum.Value();
  return true;
}

}  // namespace local_ee_s2
