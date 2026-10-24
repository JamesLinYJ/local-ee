"""Keep explicitly spherical values out of legacy planar raster consumers.

S2 results expose geodesic=true, as do explicitly geodesic constructors. The
legacy unflagged raster/filter input path still has its earlier planar model;
it is not evidence of GEE default-geodesic raster compatibility. Extending
those consumers needs a bounded spherical mask/reprojection adapter.
"""
from __future__ import annotations

from .geometry_values import GeometryValue
from .ir import fail
from .spherical_wire import FullSphere


def reject_spherical_edges(translator, value, label):
    """Reject effective spherical edge models before any legacy planar call.

    Untyped legacy GeoJSON keeps the former planar default. Typed geometry
    values carry the SDK's effective defaults in their metadata sidecar, so
    they must be inspected through ``geometry_edge_models`` rather than by
    looking only for a public ``geodesic`` key.
    """
    from .geometry_topology import geometry_edge_models

    active = set()
    charged = 0

    def visit(geometry, depth=0):
        nonlocal charged
        if isinstance(geometry, FullSphere):
            fail(f"{label} does not support a full-sphere geometry")
        if not isinstance(geometry, dict):
            return  # The existing consumer retains its own shape/type checks.
        if depth > 16 or id(geometry) in active:
            fail(f"{label} geometry exceeds finite nesting limits")
        if translator.steps + 1 > 50_000:
            fail(f"{label} exceeds the shared 50000-step compilation work budget")
        translator.steps += 1
        charged += 1
        active.add(id(geometry))
        try:
            kind = geometry.get("type")
            if kind == "Feature":
                if "geodesic" in geometry and type(geometry["geodesic"]) is not bool:
                    fail("Geometry geodesic must be a boolean")
                visit(geometry.get("geometry"), depth + 1)
                return
            if "geodesic" in geometry and type(geometry["geodesic"]) is not bool:
                fail("Geometry geodesic must be a boolean")
            if kind == "GeometryCollection":
                children = geometry.get("geometries")
                if not isinstance(children, (list, tuple)) or len(children) > 1_000:
                    fail(f"{label} requires a bounded GeometryCollection")
                for child in children:
                    visit(child, depth + 1)
        finally:
            active.remove(id(geometry))

    visit(value)
    root = value
    inherited = None
    # Feature wrappers are accepted by existing consumers, but the topology
    # walker operates on GeoJSON geometries. Preserve an explicit Feature
    # flag; otherwise keep raw values on the legacy planar route while letting
    # a typed child supply its sidecar default.
    while isinstance(root, dict) and root.get("type") == "Feature":
        child = root.get("geometry")
        feature_model = root.get("geodesic")
        if feature_model is not None:
            inherited = feature_model
        elif inherited is None and not isinstance(child, GeometryValue):
            inherited = False
        root = child
        if root is None:
            return

    if isinstance(root, FullSphere):
        fail(f"{label} does not support a full-sphere geometry")
    if not isinstance(root, dict):
        return

    # Run the shared structural preflight before geometry_edge_models walks
    # coordinates, preserving the existing finite nesting/cycle diagnostic
    # above while bounding coordinate arrays and malformed collections.
    from .geometry_preflight import measure_geometry

    cost = measure_geometry(root)
    # The first walk charges the geometry/Feature tree nodes and preserves its
    # cycle/depth diagnostics. Also charge the bounded coordinate-array and
    # effective-model inspection before geometry_edge_models descends them.
    required = cost.nodes + cost.positions
    if required > charged:
        extra = required - charged
        if translator.steps + extra > 50_000:
            fail(f"{label} exceeds the shared 50000-step compilation work budget")
        translator.steps += extra

    if inherited is None and not isinstance(root, GeometryValue):
        inherited = False
    for model in geometry_edge_models(root, inherited):
        if model is True:
            fail(f"{label} spherical geometry edges require a spherical raster/reprojection adapter")
        if model is not False:
            fail(f"{label} geometry edge model is unresolved")
