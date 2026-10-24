"""Separate actual S2 defaults, projected subsets, and remaining consumers."""


GEOMETRY_BINARY_LIMITS = {}

for _family in ("Geometry", "Feature"):
    for _method in (
        "contains", "containedIn", "disjoint", "intersects", "intersection",
        "union", "difference", "symmetricDifference",
    ):
        GEOMETRY_BINARY_LIMITS[_family + "." + _method] = [
            "Official left/right/maxError/proj signatures; finite inline geometry "
            "calculation only. Omitted/null proj routes geodesic EPSG:4326 input "
            "through pinned local S2 0.14.0; geodesic and evenOdd defaults are "
            "retained, including oriented spherical loops, holes, dateline and "
            "polar geometry. Explicit proj='EPSG:4326' remains a planar subset "
            "requiring proven geodesic=false edges. Non-null maxError/ErrorMargin, "
            "other CRS and planar-to-sphere transformations remain unsupported. "
            "Fresh bounded validation, normalization, pair/output-growth and "
            "owned-copy work share50000 steps,10000 coordinates,1000 children "
            "and16 levels. Native S2 tracks up to64MiB of working allocations; "
            "this is not a total RSS bound. Empty and lower-dimensional outputs "
            "retain their actual type; full-sphere public encoding rejects. "
            "S2 CLOSED and GEOS interior-boundary policies are local; binary64 "
            "input/output conversion has measured exact-incidence and inserted-"
            "vertex roundtrip gaps. Nearby distinct points are not epsilon-merged. "
            "Explicit spherical outputs reject at legacy planar raster/filter "
            "consumers; unflagged raster input retains the earlier planar path "
            "and has no GEE geodesic parity claim. Trusted synthetic SDK/CSV and "
            "native component checks are not full Spark/deployment/Google acceptance."
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
