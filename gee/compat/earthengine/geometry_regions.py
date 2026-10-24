"""Fresh, budgeted ownership for EE geometry region consumers."""
from __future__ import annotations

from .geometry_consumers import reject_spherical_edges
from .geometry_preflight import (
    MAX_GEOMETRY_DEPTH,
    _charge,
    precharge_geometry_copy,
)
from .geometry_public import public_geometry_mapping
from .geometry_values import GEOMETRY_TYPES, own_geometry_bounded
from .ir import fail
from .spherical_wire import FullSphere


_FEATURE_FIELDS = frozenset({"type", "geometry", "properties", "id"})
_UNSUPPORTED_FEATURE_MODEL_FIELDS = frozenset({"geodesic", "evenOdd", "crs"})


def _unwrap_feature_region(translator, value, label):
    """Validate and discard bounded Feature wrappers without inheriting flags."""
    seen = set()
    depth = 0
    while isinstance(value, dict) and value.get("type") == "Feature":
        if id(value) in seen:
            fail(f"{label} Feature wrappers contain a cycle")
        if depth >= MAX_GEOMETRY_DEPTH:
            fail(f"{label} Feature wrapper nesting exceeds 16 levels")

        # Feature wrappers are small wire envelopes. Charge their full finite
        # field scan before inspecting keys or allocating a detached property
        # representation. Geometry coordinate work is charged separately by
        # the shared geometry preflight below.
        if len(value) > 5:
            _charge(translator, 11, f"{label} Feature wrapper")
            fail(f"{label} Feature wrapper has unsupported fields")
        _charge(translator, 1 + 2 * len(value), f"{label} Feature wrapper")
        seen.add(id(value))
        depth += 1

        for key in value:
            if type(key) is not str:
                fail(f"{label} Feature wrapper keys must be strings")
            if key in _UNSUPPORTED_FEATURE_MODEL_FIELDS:
                fail(f"{label} does not support geometry-model or CRS fields on Feature wrappers")
            if key not in _FEATURE_FIELDS:
                fail(f"{label} Feature wrapper has unsupported fields")

        if value.get("id") is not None:
            from .owned_metadata_values import preflight_public_value

            if type(value["id"]) is not str:
                fail(f"{label} Feature id must be a string")
            preflight_public_value(translator, value["id"], f"{label} Feature id")

        properties = value.get("properties")
        if properties is not None:
            if not isinstance(properties, dict):
                fail(f"{label} Feature properties must be a dictionary or null")
            from .owned_metadata_values import preflight_public_value

            preflight_public_value(
                translator, properties, f"{label} Feature properties",
            )

        if "geometry" not in value or value["geometry"] is None:
            fail("An explicit geometry is required")
        value = value["geometry"]
    return value


def _strip_inferred_even_odd(output, source, inherited=None):
    if not isinstance(output, dict) or not isinstance(source, dict):
        return
    explicit = source.get("evenOdd", inherited)
    if explicit is None:
        output.pop("evenOdd", None)
    if (source.get("type") == "GeometryCollection"
            and output.get("type") == "GeometryCollection"):
        for child, source_child in zip(
                output.get("geometries", []), source.get("geometries", [])):
            _strip_inferred_even_odd(child, source_child, explicit)


def own_ee_region(translator, value, label, *, strip_inferred_even_odd=False):
    """Return a freshly validated geometry and its model-preserving EE map.

    Unflagged EE edge-bearing leaves use the EE spherical default. Feature
    wrapper model/CRS members are rejected locally because this boundary has
    no audited rule for applying them to the wrapped geometry; the child's
    own model remains authoritative.
    """
    value = _unwrap_feature_region(translator, value, label)
    if isinstance(value, FullSphere):
        reject_spherical_edges(
            translator, value, label, default_geodesic=True,
        )
        return value, value

    if not isinstance(value, dict) or value.get("type") not in GEOMETRY_TYPES:
        fail("Expected a supported GeoJSON geometry")
    owned = own_geometry_bounded(translator, value)
    reject_spherical_edges(
        translator, owned, label, default_geodesic=True,
    )

    # public_geometry_mapping copies every geometry node and emits the
    # constructor-supported model flags. Reserve that mapping and its
    # measured coordinate/model pass before materializing any output dicts.
    extra_walks = 1 if strip_inferred_even_odd else 0
    precharge_geometry_copy(
        translator, owned, f"{label} public mapping",
        additional_geometry_walks=extra_walks,
    )
    mapped = public_geometry_mapping(owned)
    if strip_inferred_even_odd:
        _strip_inferred_even_odd(mapped, owned)
    return owned, mapped
