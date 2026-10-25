"""Whole-table resource reservation for the closed EE component CSV route."""
from __future__ import annotations

from .table_geometry import TableGeometryError
from .table_spherical_geometry import spherical_model, even_odd_model
from .compat.earthengine.spherical_preflight import native_work


STRICT_OGC = "strict_ogc"
EE_COMPONENTS = "ee_components"
MAX_COMPONENT_WORK = 50_000
_NESTING = {"Point": 0, "MultiPoint": 1, "LineString": 1,
            "MultiLineString": 2, "Polygon": 2, "MultiPolygon": 3}


def validate_geometry_profile(profile):
    if type(profile) is not str or profile not in {STRICT_OGC, EE_COMPONENTS}:
        raise TableGeometryError("Unsupported internal table geometry profile")


def reserve_component_table_work(features):
    """Count every row before the first atomic GEOS operation can run.

    The counter covers structure/model walks, coordinate visits and copies,
    extra MultiPolygon atom wrappers, and each actual S2 validation call.
    Mixed planar/spherical rows share this single ledger. Existing byte/row/
    cell checks remain independent. This is not a GEOS CPU-time proof.
    """
    work = 0
    active = set()

    def charge(amount):
        nonlocal work
        work += amount
        if work > MAX_COMPONENT_WORK:
            raise TableGeometryError(
                "EE component table geometry exceeds the shared 50000-step work budget"
            )

    def enter(value):
        identity = id(value)
        if identity in active:
            raise TableGeometryError("EE component table geometry contains a cycle")
        active.add(identity)
        return identity

    def coordinates(value, nesting, positions):
        if type(value) is not list or len(value) > 10_000:
            raise TableGeometryError("EE table geometry requires bounded coordinate lists")
        identity = enter(value)
        try:
            charge(1 + len(value))
            if nesting == 0:
                if len(value) != 2:
                    raise TableGeometryError("EE table geometry requires two-dimensional positions")
                positions[0] += 1
                if positions[0] > 10_000:
                    raise TableGeometryError("EE table geometry exceeds 10000 positions")
                charge(4)
            else:
                for child in value:
                    coordinates(child, nesting - 1, positions)
        finally:
            active.remove(identity)

    def geometry(value, depth, positions, inherited_model=None, inherited_parity=None):
        if value is None:
            if depth:
                raise TableGeometryError("EE GeometryCollection children must be geometry objects")
            charge(1)
            return
        if not isinstance(value, dict) or depth > 16:
            raise TableGeometryError("EE table geometry exceeds its bounded structure")
        identity = enter(value)
        try:
            charge(4 + len(value))
            model = spherical_model(value, inherited_model)
            parity = even_odd_model(value, inherited_parity)
            kind = value.get("type")
            if kind == "GeometryCollection":
                children = value.get("geometries")
                if type(children) is not list or len(children) > 1000:
                    raise TableGeometryError("EE GeometryCollection requires at most 1000 children")
                charge(len(children))
                for child in children:
                    geometry(child, depth + 1, positions, model, parity)
                if not children and model is True:
                    charge(native_work(value))
            elif type(kind) is str and kind in _NESTING:
                raw = value.get("coordinates")
                coordinates(raw, _NESTING[kind], positions)
                if kind == "MultiPolygon":
                    charge(4 * len(raw))
                if model is True:
                    # Mirror model-aware table validation: nonempty collections
                    # validate their leaves; only empty collections call S2.
                    charge(native_work(value))
            else:
                raise TableGeometryError("Unsupported EE table geometry type")
        finally:
            active.remove(identity)

    for feature in features:
        if type(feature) is not dict:
            raise TableGeometryError("FeatureCollection entries must be objects")
        geometry(feature.get("geometry"), 0, [0])
    return work
