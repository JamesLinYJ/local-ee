"""Keep explicitly spherical values out of legacy planar raster consumers.

S2 results expose geodesic=true, as do explicitly geodesic constructors. The
legacy unflagged raster/filter input path still has its earlier planar model;
it is not evidence of GEE default-geodesic raster compatibility. Extending
those consumers needs a bounded spherical mask/reprojection adapter.
"""
from __future__ import annotations

from .ir import fail
from .spherical_wire import FullSphere


def reject_spherical_edges(translator, value, label):
    """Reject public spherical edge models before any legacy GEOS call."""
    active = set()

    def visit(geometry, inherited=None, depth=0):
        if isinstance(geometry, FullSphere):
            fail(f"{label} does not support a full-sphere geometry")
        if not isinstance(geometry, dict):
            return  # The existing consumer retains its own shape/type checks.
        if depth > 16 or id(geometry) in active:
            fail(f"{label} geometry exceeds finite nesting limits")
        if translator.steps + 1 > 50_000:
            fail(f"{label} exceeds the shared 50000-step compilation work budget")
        translator.steps += 1
        active.add(id(geometry))
        try:
            kind = geometry.get("type")
            if kind == "Feature":
                visit(geometry.get("geometry"), inherited, depth + 1)
                return
            model = geometry.get("geodesic", inherited)
            if kind == "GeometryCollection":
                children = geometry.get("geometries")
                if not isinstance(children, (list, tuple)) or len(children) > 1_000:
                    fail(f"{label} requires a bounded GeometryCollection")
                for child in children:
                    visit(child, model, depth + 1)
            elif kind not in {"Point", "MultiPoint"} and model is True:
                fail(f"{label} spherical geometry edges require a spherical raster/reprojection adapter")
        finally:
            active.remove(id(geometry))

    visit(value)
