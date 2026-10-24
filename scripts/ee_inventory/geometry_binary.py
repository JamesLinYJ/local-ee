"""Projected binary geometry support is distinct from spherical defaults."""


GEOMETRY_BINARY_LIMITS = {}

for _family in ("Geometry", "Feature"):
    for _method in (
        "contains", "containedIn", "disjoint", "intersects", "intersection",
        "union", "difference", "symmetricDifference",
    ):
        GEOMETRY_BINARY_LIMITS[_family + "." + _method] = [
            "Official left/right/maxError/proj signatures; finite inline geometry "
            "calculation only. Requires explicit EPSG:4326 projection and proven "
            "planar non-point edges (explicit geodesic=false); point/empty values "
            "have no edges. Omitted/null proj has spherical semantics in GEE and "
            "remains unsupported, never silently replaced by planar geometry. "
            "Non-null maxError, non-4326 reprojection, geodesic=true, ambiguous "
            "non-point edges and evenOdd=false reject. Existing mutable Geometry "
            "values are freshly validated; structural, GEOS pair/output-growth "
            "and owned-copy work are precharged within shared50000 work, "
            "10000-coordinate,1000-child and16-level bounds. Empty results are "
            "valid owned geometries; lower-dimensional intersections retain "
            "their actual type. Contains uses local GEOS interior/boundary "
            "semantics, not a Google oracle. No spherical, native raster, "
            "full Spark, deployed service or Google same-data acceptance."
        ]
        if _family == "Feature":
            GEOMETRY_BINARY_LIMITS[_family + "." + _method].append(
                "Only actual finite inline Features with non-null geometry; "
                "arbitrary Element/Image/runtime receivers remain unsupported. "
                "Overlays retain an owned copy of left properties and actual "
                "left identity under the existing explicit local ID policy; "
                "right properties are ignored. This is not complete Element "
                "overload or default-argument compatibility."
            )
