#ifndef LOCAL_EE_S2_ELLIPSOID_MEASURES_H_
#define LOCAL_EE_S2_ELLIPSOID_MEASURES_H_

#include "s2_internal.h"

namespace local_ee_s2 {

// Operation codes shared by the native adapter and the WGS84 metric kernel.
constexpr int kWgs84AreaOperation = 11;
constexpr int kWgs84LinearLengthOperation = 12;
constexpr int kWgs84PolygonPerimeterOperation = 13;

// Returns the maximum number of scalar quadrature evaluations for the
// selected metric. The adapter adds this to CheckCallBudget's geometry cost
// before constructing any S2 components. `overflow` is set if the estimate
// cannot be represented.
size_t EstimateWgs84MeasureWork(int op, const ParsedGeometry& parsed,
                               bool* overflow);

// Computes one WGS84 ellipsoid measure along the input's existing S2 great
// circle edges. The output is the fixed two-double record [1, value].
bool RunEllipsoidMeasure(int op, const ParsedGeometry& parsed,
                         S2MemoryTracker* tracker, double output[2],
                         std::string* error);

}  // namespace local_ee_s2

#endif  // LOCAL_EE_S2_ELLIPSOID_MEASURES_H_
