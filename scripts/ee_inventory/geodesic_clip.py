"""Partial limits for the real bounded geodesic clip producer and consumers."""


CLIP_CONTEXT_LIMITS = {
    "Image.clip": [
        "Finite default/explicit-geodesic EPSG:4326 Polygon/MultiPolygon with "
        "evenOdd interiors. Independent Float64 projected-cell area weights on "
        "the actual raster grid; raw NoData yields valid zero, source Infinity "
        "rejects even outside ROI, science is never multiplied by coverage. "
        "Bounded great-circle tessellation targets1e-6 pixel chord deviation and "
        "0.25 degree maximum arc; this is a local approximation, not a rigorous "
        "area-error certificate or Google quantizer. Exact meridian/equator "
        "identities preserve zero contacts and positive representable slivers; "
        "other curved contact parity remains open. Actual CRS restricted to "
        "EPSG:4326/3857/normal-zone UTM; numerical angle/grid/domain guards and "
        "existing compiler/graph/native budgets remain. No wraps, poles, "
        "left-inside, points/lines, clipToCollection, repeated clips or existing "
        "fractional input composition. Explicit planar historical clip stays "
        "binary-center based. New weighted science only enters audited mask "
        "getter/unary/scalar/sample consumers; weighted regional reduction, "
        "display and scientific raster export remain unsupported. Exact "
        "clipped footprint is pending; preserve its canonical identity through "
        "derived expression/collection Images and reject unaudited collection "
        "geometry extraction. Preserve "
        "first-image ownership through zero-band selection, copies and merges. "
        "Actual tile and trusted CSV evidence is not full Spark/deployment or "
        "Google equivalence. See docs/gee-python/geodesic-clip.md."
    ],
    "Image.geometry": [
        "Images with an unresolved geodesic clip footprint reject public "
        "geometry extraction, including after zero-band selection/overwrites; "
        "the original source envelope is internal scan support only."
    ],
    "Image.sample": [
        "For a pending geodesic clip footprint, omitted/null region currently "
        "requires exactly one band, dropNulls=true and a weighted output whose zero-support "
        "proof matches the retained canonical footprint clip identity. Mask "
        "replacement/validity barriers and a different clipped donor cannot "
        "supply that proof. Otherwise provide an explicit supported region. "
        "This guard does not change the existing explicit region center rule."
    ],
}
