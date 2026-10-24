"""Bounded binary predicates and overlays for actual inline Features."""
from __future__ import annotations

from .feature_structure import _feature, _identity
from .geometry_binary import invoke_geometry_binary
from .ir import fail
from .owned_metadata_values import owned_metadata_copy


FEATURE_GEOMETRY_BINARY_FUNCTIONS = frozenset({
    "Feature.contains", "Feature.containedIn", "Feature.disjoint",
    "Feature.intersects", "Feature.intersection", "Feature.union",
    "Feature.difference", "Feature.symmetricDifference",
})
FEATURE_GEOMETRY_BINARY_ARGUMENTS = {
    name: (frozenset({"left", "right"}), frozenset({"maxError", "proj"}))
    for name in FEATURE_GEOMETRY_BINARY_FUNCTIONS
}
_PREDICATES = frozenset({
    "Feature.contains", "Feature.containedIn", "Feature.disjoint",
    "Feature.intersects",
})


def _arguments(translator, name, arguments):
    if type(arguments) is not dict:
        fail(f"{name} arguments must be a dictionary")
    required, optional = FEATURE_GEOMETRY_BINARY_ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def invoke_feature_geometry_binary(translator, name, arguments):
    """Apply a finite Geometry binary operator to actual inline Features.

    The geometry worker owns edge-model/overlay validation and the
    shared geometry budget. Feature validation and the left properties copy
    happen first, so mutable Feature data is never copied before reservation
    or left aliased while GEOS runs.
    """
    if name not in FEATURE_GEOMETRY_BINARY_FUNCTIONS:
        fail(f"Unsupported Feature geometry operation: {name}")
    _arguments(translator, name, arguments)

    left = _feature(translator, arguments["left"], name)
    right = _feature(translator, arguments["right"], name)
    left_identity = _identity(left)
    _identity(right)
    left_geometry = left.get("geometry")
    right_geometry = right.get("geometry")
    if left_geometry is None or right_geometry is None:
        fail(f"{name} requires non-null geometry on both Features")

    output_properties = None
    if name not in _PREDICATES:
        # Charge and detach the only mutable Feature payload returned by an
        # overlay before the geometry worker may invoke GEOS.
        output_properties = owned_metadata_copy(
            translator, left["properties"], name + " left properties",
        )

    geometry_arguments = {
        "left": left_geometry,
        "right": right_geometry,
    }
    for option in ("maxError", "proj"):
        if option in arguments:
            geometry_arguments[option] = arguments[option]
    geometry_name = name.replace("Feature.", "Geometry.", 1)
    result = invoke_geometry_binary(translator, geometry_name, geometry_arguments)

    if name in _PREDICATES:
        if type(result) is not bool:
            fail(f"{name} geometry worker returned a non-Boolean result")
        return result

    from .spherical_wire import FullSphere

    if isinstance(result, FullSphere):
        fail("Feature full-sphere public GeoJSON encoding is unverified")
    if not isinstance(result, dict) or type(result.get("type")) is not str:
        fail(f"{name} geometry worker returned a malformed geometry")
    feature = {
        "type": "Feature",
        "geometry": result,
        "properties": output_properties,
    }
    # Preserve the actual left Feature identity exactly once. A system:index
    # remains in the copied properties when present; otherwise retain its id.
    if "id" in left:
        feature["id"] = left["id"]
    elif left_identity is not None and "system:index" not in output_properties:
        feature["id"] = left_identity
    return feature
