"""Feature measure wrappers retaining owned identity and properties."""
from __future__ import annotations

from .feature_structure import _feature, _feature_header, _identity
from .geometry_measures import (
    FEATURE_MEASURE_ARGUMENTS,
    FEATURE_MEASURE_METHODS,
    _charge,
    _evaluate,
)
from .geometry_preflight import MAX_GEOMETRY_WORK
from .ir import fail
from .feature_preflight_cache import owned_feature_copy


_FEATURE_CENTROID_OUTPUT_WORK = 6


def _arguments(translator, name, arguments):
    if type(arguments) is not dict:
        fail(f"{name} arguments must be a dictionary")
    required, optional = FEATURE_MEASURE_ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires arguments: {sorted(missing)}")


def invoke_feature_geometry_measures(translator, name, arguments):
    """Evaluate Feature scalars or return a centroid with source metadata."""
    if name not in FEATURE_MEASURE_METHODS:
        fail(f"Unsupported Feature measure operation: {name}")
    _arguments(translator, name, arguments)
    method = name.removeprefix("Feature.")
    if method == "centroid":
        # Make the one returned snapshot after complete validation, before
        # comparing identity strings or inspecting any retained metadata.
        source = _feature_header(arguments["feature"], name)
        feature = owned_feature_copy(translator, source, name)
    else:
        # Scalar methods still receive the full cycle/public-size/metadata
        # validation, without reserving an unused detached Feature copy.
        feature = _feature(
            translator, arguments["feature"], name, reserve_copy=False,
        )
    # Reject malformed identity consistently for scalar methods too, even
    # though their numeric result does not carry the source Feature through.
    identity = _identity(feature)
    projection = arguments.get("proj")
    max_error = arguments.get("maxError")

    if method != "centroid":
        return _evaluate(
            translator, name, method, feature.get("geometry"),
            projection=projection, max_error=max_error, allow_null=True,
        )

    snapshot = feature
    _charge(translator, _FEATURE_CENTROID_OUTPUT_WORK,
            name + " Feature wrapper output reservation")
    result = _evaluate(
        translator, name, method, snapshot.get("geometry"),
        projection=projection, max_error=max_error, allow_null=True,
    )
    if identity is not None:
        # `_feature` already checks that top-level id and system:index agree;
        # the deep owned snapshot preserves the actual wire form exactly.
        if "id" not in snapshot and snapshot["properties"].get("system:index") != identity:
            fail(f"{name} lost the Feature system:index during its owned copy")
    snapshot["geometry"] = result
    if type(snapshot) is not dict or snapshot.get("type") != "Feature":
        fail(f"{name} returned a malformed Feature")
    if translator.steps > MAX_GEOMETRY_WORK:
        fail(f"{name} exceeds the shared 50000-step compilation work budget")
    return snapshot
