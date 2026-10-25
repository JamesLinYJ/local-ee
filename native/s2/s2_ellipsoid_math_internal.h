#ifndef LOCAL_EE_S2_ELLIPSOID_MATH_INTERNAL_H_
#define LOCAL_EE_S2_ELLIPSOID_MATH_INTERNAL_H_

#include <cmath>

#include "s2_ellipsoid_math.h"

namespace local_ee_s2 {
namespace ellipsoid_internal {

struct Arc {
  Coordinate start;
  Coordinate end;
  long double z0;
  long double cosine_latitude;
  long double uz;
  long double ax;
  long double ay;
  long double ux;
  long double uy;
  long double angle;
  long double longitude_rate;
  long double longitude_change;
};

struct QuadratureLevels {
  long double one = 0;
  long double two = 0;
  long double four = 0;
};

struct CompensatedSum {
  long double sum = 0;
  long double correction = 0;

  void Add(long double value) {
    const long double next = sum + value;
    if (std::fabs(sum) >= std::fabs(value)) {
      correction += (sum - next) + value;
    } else {
      correction += (value - next) + sum;
    }
    sum = next;
  }

  long double Value() const { return sum + correction; }
};

using Integrand = long double (*)(const Arc&, long double, const void*);

bool BuildArc(Coordinate start, Coordinate end, Arc* arc, std::string* error);
long double ArcZ(const Arc& arc, long double t);
long double ArcZDifference(const Arc& arc, long double t);
long double ArcZDerivative(const Arc& arc, long double t);
long double ArcHorizontal2(const Arc& arc, long double t);
QuadratureLevels IntegrateArc(const Arc& arc, Integrand function,
                              const void* context);
bool Converged(const QuadratureLevels& values, long double abs_tolerance,
               long double rel_tolerance);
bool SphericalLoopArea(const std::vector<Coordinate>& loop,
                       bool represents_large_side, long double* area,
                       std::string* error);
long double Pi();
bool Fail(std::string* error, const std::string& message);

}  // namespace ellipsoid_internal
}  // namespace local_ee_s2

#endif  // LOCAL_EE_S2_ELLIPSOID_MATH_INTERNAL_H_
