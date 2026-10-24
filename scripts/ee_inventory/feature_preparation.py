"""Explicit finite metadata, feature, filter and geometry preparation limits."""

FEATURE_PREPARATION_LIMITS = {}

FEATURE_PREPARATION_LIMITS["Feature.geometry"] = [
    "Finite inline Feature extraction only; omitted/null maxError, proj and "
    "geodesics preserve the existing model, geometry omissions and collection "
    "inheritance. Without proj, a valid Boolean geodesics is ignored as the "
    "pinned SDK specifies. Explicit EPSG:4326 supports unchanged edge models "
    "only; non-null maxError, other CRS and actual edge-model transforms reject. "
    "Null geometry stays null. Fresh coordinate/topology validation and owned "
    "copies, including explicit model-inspection work, use the shared50000 "
    "budget; mutable prior validation flags cannot bypass it. Spherical "
    "extraction retains S2 semantics, not legacy GEOS raster authorization. "
    "Private full sphere, arbitrary Element/runtime receivers and Google "
    "service equivalence remain unsupported or unverified."
]

for _method in ("getNumber", "getString", "getArray", "toDictionary", "replaceProperties"):
    FEATURE_PREPARATION_LIMITS["Element." + _method] = [
        "Finite inline Feature/FeatureCollection metadata and concrete unmapped Image "
        "metadata only, with actual per-item ImageCollection map expansion. Typed getters "
        "keep Number/String/StaticArray values, reject incompatible non-null types and "
        "return null for missing/null properties. toDictionary defaults to non-system "
        "properties; explicit missing keys are omitted by documented local policy. "
        "replaceProperties replaces rather than merges; omitted/null source removes "
        "ordinary properties (Image retains an actual system:index locally), actual "
        "destination Feature identity is preserved and conflicting "
        "source system:index rejects. Typed arrays, concrete joined Images and owned "
        "nested outputs retain their representation under shared50000 work/1MB/depth "
        "limits. Dynamic sampled metadata and opaque runtime values reject. No Google "
        "missing-key, identity, default-output or numerical equivalence claim."
    ]

for _method in ("id", "select", "setGeometry", "toArray"):
    FEATURE_PREPARATION_LIMITS["Feature." + _method] = [
        "Finite inline Features only. id reads actual explicit id or system:index, "
        "never generates an index. select uses bounded RE2 fullmatch with ordered "
        "selectors and optional equal-length unique renames; retainGeometry=false "
        "sets null geometry. Actual identity preservation when index is removed or "
        "renamed is an explicit local policy. setGeometry accepts null or validated "
        "local planar EPSG:4326 geometry. toArray accepts ordered finite numeric "
        "properties only; no dynamic feature-table/raster vector engine. Owned outputs "
        "and scan/copy/regex work use unchanged50000 work/1MB/rank8/10000-cell limits. "
        "No Google identity, dtype, shape or default-property parity claim."
    ]

for _method in (
    "eq", "gt", "gte", "lt", "lte", "neq", "notEquals", "greaterThanOrEquals",
    "lessThanOrEquals", "stringStartsWith", "stringEndsWith", "rangeContains",
    "dayOfYear", "always", "never", "hasGeometry",
):
    FEATURE_PREPARATION_LIMITS["Filter." + _method] = [
        "Validated finite metadata filters. Comparison aliases lower to existing "
        "canonical Filter trees; string boundaries evaluate real string operands, "
        "rangeContains is inclusive and dayOfYear uses UTC with wrapping ranges. "
        "Inline Features/catalog items retain existing missing/null/type policies; "
        "sampled/classified tables admit comparison aliases, rangeContains, always/never, "
        "string boundaries and hasGeometry, revalidating bounded canonical wire expressions "
        "under their unchanged16-operation/50000-work caps. hasGeometry uses actual "
        "inline/catalog/sampled/classified row geometry, with missing/null false. Every inline "
        "Filter branch is preflighted before rows, including empty inputs and a "
        "false earlier branch. Filter.hasType remains explicitly unsupported. "
        "No Google string/calendar/null or service-join equivalence claim."
    ]

FEATURE_PREPARATION_LIMITS["Filter.dayOfYear"].append(
    "Inline Features and local catalog metadata only. Sampled/classified runtime "
    "tables reject calendarRange/dayOfYear because their canonical wire grammar "
    "does not define temporal filter evaluation."
)

for _method in (
    "type", "coordinates", "geometries", "isUnbounded", "edgesAreGeodesics", "geodesic",
):
    FEATURE_PREPARATION_LIMITS["Geometry." + _method] = [
        "Owned accessors on validated finite EPSG:4326 local geometries. "
        "Single geometries return a singleton from geometries(); collections return "
        "their immediate children and do not provide coordinates(). isUnbounded is "
        "false for admitted finite geometries. Effective EE geodesic/evenOdd "
        "defaults, oriented spherical interiors and collection inheritance use "
        "the pinned S2 validator; explicit planar edges retain GEOS. Other CRS "
        "and transforms reject, and mixed edge-model scalar accessors reject. "
        "Decode/native work and copies are precharged within unchanged50000 "
        "work/10000-coordinate/depth limits. No Google oracle proof."
    ]

for _method in ("BBox", "MultiGeometry", "LinearRing"):
    FEATURE_PREPARATION_LIMITS["GeometryConstructors." + _method] = [
        "Pinned-signature normalization into actual finite EPSG:4326 geometry values; "
        "bounded decode preserves admitted constructor flags and owns coordinates. "
        "BBox retains planar edges, non-wrapping longitude and clipped pole latitude; circular "
        "longitude wrapping rejects. MultiGeometry uses GeometryCollection and "
        "LinearRing retains its own type. Other finite constructors retain EE "
        "geodesic/evenOdd defaults through pinned S2, or explicit planar GEOS "
        "edges. Other CRS and non-null maxError/reprojection reject. Existing "
        "50000 work/10000-coordinate/topology limits remain. No Google geometric "
        "boundary, winding or projection equivalence claim."
    ]
