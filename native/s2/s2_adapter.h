#ifndef LOCAL_EE_S2_ADAPTER_H_
#define LOCAL_EE_S2_ADAPTER_H_

#include <stddef.h>

#if defined(_WIN32)
#define LOCAL_EE_S2_EXPORT __declspec(dllexport)
#else
#define LOCAL_EE_S2_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Run one bounded spherical geometry operation.
 *
 * Input and overlay output use wire v1 doubles:
 *   [1, shape_count, shape, ...]
 *   shape = [kind, even_odd, part_count, part_vertex_count, lon, lat, ...]
 * kind is 0 for points, 1 for one polyline, and 2 for a polygon whose parts
 * are loops. even_odd is meaningful only for polygons; point and line records
 * must set it to zero. Polygon loops use oriented boundaries when even_odd is
 * zero, and even/odd interior interpretation when it is one. A polygon with
 * exactly one zero-vertex loop and even_odd zero is the internal full-sphere
 * sentinel. Overlay output polygon rings are explicitly closed by repeating
 * their first coordinate. An empty geometry is [1, 0].
 *
 * Operation codes are 0 contains, 1 containedIn, 2 intersects, 3 disjoint,
 * 4 intersection, 5 union, 6 difference, 7 symmetric difference, 8
 * validate-left-only, 9 bounds-left-only, 10 measures-left-only, 11
 * ellipsoid-area-left-only, 12 ellipsoid-length-left-only, and 13
 * ellipsoid-perimeter-left-only. Return
 * value 0 means success;
 * nonzero values indicate an invalid call, invalid wire, invalid spherical
 * topology, exhausted budget, or output overflow. Predicates and validation
 * return one scalar; overlay operations return wire v1; bounds returns the
 * fixed eight-double record [1, empty, full_longitude, wrapped, west, south,
 * east, north]. Error text is NUL-terminated when error_capacity is nonzero.
 * Bounds flags are exactly 0 or 1. Empty bounds use empty=1, the other flags
 * and all coordinates zero. Nonempty coordinates are degrees in EPSG:4326;
 * wrapped intervals have west > east. Full-longitude bounds use west=-180 and
 * east=180 and are never marked wrapped. Measures returns the fixed
 * eight-double record [1, highest_dimension, area_steradians,
 * linear_length_radians, polygon_perimeter_radians, centroid_x, centroid_y,
 * centroid_z]. highest_dimension is -1 for empty and otherwise 0, 1, or 2;
 * all measures are sums over original component records, with no component
 * union or point deduplication. The centroid vector is the unnormalized
 * measure-weighted vector of components at the highest dimension. The native
 * adapter does not apply an Earth radius or project/normalize this vector.
 * Ellipsoid area, length, and perimeter each return [1, value] in square
 * meters or meters. Area sums polygon components, length sums linear
 * components, and perimeter sums polygon boundaries, all with multiplicity.
 * These scalar measures follow WGS84 ellipsoid lengths along the input's
 * spherical great-circle edges.
 */
LOCAL_EE_S2_EXPORT int local_ee_s2_run(
    int op,
    const double* left,
    size_t left_size,
    const double* right,
    size_t right_size,
    double* output,
    size_t output_capacity,
    size_t* output_size,
    char* error,
    size_t error_capacity);

#ifdef __cplusplus
}
#endif

#endif  // LOCAL_EE_S2_ADAPTER_H_
