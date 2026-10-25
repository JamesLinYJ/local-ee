#ifndef LOCAL_EE_S2_ELLIPSOID_MATH_H_
#define LOCAL_EE_S2_ELLIPSOID_MATH_H_

#include <string>
#include <vector>

#include "s2_internal.h"

namespace local_ee_s2 {

using Wgs84PolygonLoops = std::vector<std::vector<Coordinate>>;

bool MeasureWgs84LineLength(const PartView& line, long double* length,
                            std::string* error);
bool MeasureWgs84PolygonArea(const S2Polygon& polygon,
                             const Wgs84PolygonLoops& loops,
                             long double* area, std::string* error);
bool MeasureWgs84PolygonPerimeter(const S2Polygon& polygon,
                                  const Wgs84PolygonLoops& loops,
                                  long double* perimeter,
                                  std::string* error);

}  // namespace local_ee_s2

#endif  // LOCAL_EE_S2_ELLIPSOID_MATH_H_
