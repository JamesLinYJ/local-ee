"""Model-preserving finite spatial selection, merge and margin boundaries."""


SPATIAL_CONSUMER_LIMITS = {
    "ErrorMargin": [
        "Typed finite static descriptor; optional value/unit normalization follows "
        "the pinned constructor. No standalone public JSON, arbitrary metadata or "
        "automatic reprojection. Only Filter.intersects and finite inline "
        "Collection.geometry consume it after proving same CRS/edge semantics. "
        "Other geometry/image consumers retain their explicit tolerance gaps."
    ],
    "Filter.intersects": [
        "Finite inline Features and catalog rows; full left/right field/value "
        "signature with exactly one non-null operand per side. .all/.geo read "
        "actual geometry; other names read finite flat geometry properties. "
        "Feature-valued literals unwrap their actual geometry. Default EPSG:4326 "
        "geodesic inputs use pinned S2; homogeneous explicit planar inputs use "
        "GEOS. Unflagged raw STAC catalog footprints retain RFC7946 planar edges; "
        "mixing them with curved polygon ROI rejects until reprojection exists. "
        "Points have no curve model. Validate every literal before empty rows, "
        "then freshly own row/literal coordinates within shared50000 work. "
        "maxError validates a static descriptor on no-transform paths only; "
        "it is not a buffer. Binary joins and sampled/runtime spatial filters "
        "remain unsupported. Local CLOSED/GEOS boundaries are not Google parity."
    ],
    "Collection.geometry": [
        "Finite inline FeatureCollections merge real non-null geometries with "
        "same EPSG:4326 CRS and homogeneous actual edge interpretation. Preserve "
        "S2 defaults or explicit planar GEOS, child overrides, dimensions, holes "
        "and owned coordinates; normalize even a single spherical MultiPolygon, "
        "while invalid OGC planar topology still rejects. Omitted/null "
        "and valid static maxError perform no reprojection or curve approximation. "
        "Empty/null-only collections return local empty GeometryCollection; "
        "Google empty behavior is unverified. Catalog ImageCollection geometry "
        "retains its older footprint path. Other CRS, mixed curves, public full "
        "sphere and raster masks remain gaps. Shared50000/geometry/row caps unchanged."
    ],
}
