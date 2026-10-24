"""Merge actual inline Feature geometries without dropping their edge models."""
from __future__ import annotations

from .geometry_binary import invoke_geometry_binary
from .geometry_preflight import _charge, measure_geometry
from .geometry_topology import common_edge_model
from .geometry_values import GeometryValue, decode_geometry_bounded
from .ir import fail


COLLECTION_GEOMETRY_ARGUMENTS = {
    "Collection.geometry": (
        frozenset({"collection"}), frozenset({"maxError"}),
    ),
}


def invoke_collection_geometry(translator, arguments):
    """Merge same-CRS/same-edge finite Features without reprojection.

    Freshly decoded EPSG:4326 input selects S2 or planar GEOS according to
    its actual homogeneous edge model. No tolerance-based approximation is
    performed, and input properties do not become output geometry metadata.
    """
    required, optional = COLLECTION_GEOMETRY_ARGUMENTS["Collection.geometry"]
    translator.allowed(arguments, required | optional)
    if required - arguments.keys():
        fail("Collection.geometry requires collection")
    from .error_margin import validate_no_reprojection_margin
    from .feature_ops import _features

    validate_no_reprojection_margin(
        translator, arguments.get("maxError"), "Collection.geometry",
    )
    features = _features(translator, arguments["collection"])
    _charge(translator, len(features), "Collection.geometry input list")
    geometries = []
    for feature in features:
        if feature.get("geometry") is not None:
            geometry = decode_geometry_bounded(translator, feature["geometry"])
            cost = measure_geometry(geometry)
            _charge(translator, cost.nodes + cost.positions,
                    "Collection.geometry edge-model inspection")
            geometries.append(geometry)
    model = common_edge_model(*geometries)
    _charge(translator, 8, "Collection.geometry empty accumulator")
    merged = GeometryValue(
        {"type": "GeometryCollection", "geometries": []},
        {"crs": "EPSG:4326", "geodesic": model}, validated=True,
    )
    for geometry in geometries:
        # A spherical MultiPolygon can contain overlapping components. Starting
        # empty normalizes it too; invalid planar topology still rejects earlier.
        options = {"proj": "EPSG:4326"} if model is False else {}
        merged = invoke_geometry_binary(translator, "Geometry.union", {
            "left": merged, "right": geometry, **options,
        })
    return merged
