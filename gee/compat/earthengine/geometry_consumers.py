"""Keep spherical values out of legacy planar raster and bounds consumers.

Callers handling an Earth Engine geometry pass ``default_geodesic=True``.
Catalog GeoJSON retains its documented planar policy by being explicitly
normalized at the catalog boundary before this guard is called. The default
here remains planar for legacy internal callers that have not established
their input's provenance.
"""
from __future__ import annotations

from .geometry_values import GeometryValue
from .ir import fail
from .spherical_wire import FullSphere


def reject_spherical_edges(translator, value, label, *, default_geodesic=False):
    """Reject effective spherical edge models before any legacy planar call.

    ``default_geodesic`` is the caller's provenance policy for untyped leaf
    geometries. A collection does not apply that fallback as an inherited
    parent flag: typed child sidecars and explicit child models remain intact.
    This keeps legacy raw catalog values planar when callers normalize them at
    the catalog boundary, while SDK-decoded inputs use Earth Engine defaults.
    """
    if type(default_geodesic) is not bool:
        fail("Geometry consumer default edge model must be a boolean")

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
    # walker operates on GeoJSON geometries. An absent Feature flag contributes
    # no inherited model; each child keeps its explicit flag or typed default.
    while isinstance(root, dict) and root.get("type") == "Feature":
        child = root.get("geometry")
        feature_model = root.get("geodesic")
        if feature_model is not None:
            inherited = feature_model
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

    from .geometry_topology import _has_edges

    def edge_models(geometry, inherited_model=None):
        if isinstance(geometry, FullSphere):
            yield True
            return
        kind = geometry.get("type")
        stored = (geometry.geometry_metadata
                  if isinstance(geometry, GeometryValue) else {})
        if kind == "GeometryCollection":
            if "geodesic" in geometry:
                model = geometry["geodesic"]
            elif inherited_model is not None:
                model = inherited_model
            else:
                model = stored.get("geodesic")
            for child in geometry["geometries"]:
                yield from edge_models(child, model)
            return
        if _has_edges(geometry):
            if "geodesic" in geometry:
                model = geometry["geodesic"]
            elif inherited_model is not None:
                model = inherited_model
            elif "geodesic" in stored:
                model = stored["geodesic"]
            else:
                model = default_geodesic
            yield model

    for model in edge_models(root, inherited):
        if model is True:
            fail(f"{label} spherical geometry edges require a spherical raster/reprojection adapter")
        if model is not False:
            fail(f"{label} geometry edge model is unresolved")
