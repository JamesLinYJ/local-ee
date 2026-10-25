"""Validate serialized empty-map callback structure without inventing a row."""
from __future__ import annotations

from .array_core import charge_array
from .geometry_values import GEOMETRY_TYPES
from .ir import fail


_BAND_STATE_ARGUMENTS = {
    "Image.select": (frozenset({"input", "bandSelectors"}), frozenset({"newNames"})),
    "Image.rename": (frozenset({"input", "names"}), frozenset()),
    "Image.addBands": (frozenset({"dstImg", "srcImg"}), frozenset({"names", "overwrite"})),
    "Image.bandNames": (frozenset({"image"}), frozenset()),
    "Image.constant": (frozenset({"value"}), frozenset()),
    "Collection.iterate": (frozenset({"collection", "function"}), frozenset({"first"})),
}


def _contract(name):
    from .element_metadata_values import ELEMENT_METADATA_VALUE_ARGUMENTS
    from .feature_structure import FEATURE_STRUCTURE_ARGUMENTS
    from .filtering import FILTER_PREPARATION_ARGUMENTS
    from .geometry_structure import GEOMETRY_STRUCTURE_ARGUMENTS
    from .geometry_constructors import GEOMETRY_CONSTRUCTOR_ARGUMENTS
    from .geometry_binary import GEOMETRY_BINARY_ARGUMENTS
    from .feature_geometry_binary import FEATURE_GEOMETRY_BINARY_ARGUMENTS
    from .geometry_bounds import GEOMETRY_BOUNDS_ARGUMENTS
    from .geometry_measures import (
        FEATURE_MEASURE_ARGUMENTS, GEOMETRY_MEASURE_ARGUMENTS,
    )
    from .feature_values import FEATURE_GEOMETRY_ARGUMENTS
    from .collection_geometry import COLLECTION_GEOMETRY_ARGUMENTS
    from .error_margin import ERROR_MARGIN_ARGUMENTS
    from .spatial_filters import SPATIAL_FILTER_ARGUMENTS
    from .image_band_preparation import BAND_PREPARATION_ARGUMENTS
    from .image_metadata_raster import IMAGE_METADATA_RASTER_ARGUMENTS
    from .image_mask_weights import MASK_WEIGHT_ARGUMENTS
    from .image_unmix import IMAGE_UNMIX_ARGUMENTS
    from .raster_array_preparation import RASTER_ARRAY_PREPARATION_ARGUMENTS
    from .raster_array_dot import RASTER_ARRAY_DOT_ARGUMENTS
    from .image_color import IMAGE_COLOR_REQUIRED_ARGUMENTS, IMAGE_COLOR_OPTIONAL_ARGUMENTS
    from .image_curves import IMAGE_CURVE_REQUIRED_ARGUMENTS, IMAGE_CURVE_OPTIONAL_ARGUMENTS

    for contracts in (
        _BAND_STATE_ARGUMENTS,
        ELEMENT_METADATA_VALUE_ARGUMENTS, FEATURE_STRUCTURE_ARGUMENTS,
        FILTER_PREPARATION_ARGUMENTS, GEOMETRY_STRUCTURE_ARGUMENTS,
        GEOMETRY_CONSTRUCTOR_ARGUMENTS,
        GEOMETRY_BINARY_ARGUMENTS, FEATURE_GEOMETRY_BINARY_ARGUMENTS,
        GEOMETRY_BOUNDS_ARGUMENTS,
        GEOMETRY_MEASURE_ARGUMENTS, FEATURE_MEASURE_ARGUMENTS,
        FEATURE_GEOMETRY_ARGUMENTS,
        COLLECTION_GEOMETRY_ARGUMENTS, ERROR_MARGIN_ARGUMENTS,
        SPATIAL_FILTER_ARGUMENTS,
        BAND_PREPARATION_ARGUMENTS, IMAGE_METADATA_RASTER_ARGUMENTS, MASK_WEIGHT_ARGUMENTS,
        IMAGE_UNMIX_ARGUMENTS, RASTER_ARRAY_PREPARATION_ARGUMENTS,
        RASTER_ARRAY_DOT_ARGUMENTS,
    ):
        if name in contracts:
            return contracts[name]
    for required, optional in (
        (IMAGE_COLOR_REQUIRED_ARGUMENTS, IMAGE_COLOR_OPTIONAL_ARGUMENTS),
        (IMAGE_CURVE_REQUIRED_ARGUMENTS, IMAGE_CURVE_OPTIONAL_ARGUMENTS),
    ):
        if name in required:
            return required[name], optional[name]
    return None


def preflight_empty_feature_map(translator, function):
    """Check operator names and new preparation signatures, never callback values.

    Missing row properties and value-dependent types cannot be evaluated on an
    empty collection. The serialized operators and their literal keyword names
    can still be checked. This walk does not call evaluate(), resolve catalog
    metadata, execute a function, or synthesize a Feature.
    """
    from .capabilities import SUPPORTED_FUNCTIONS

    active = set()
    complete = {}

    def walk(value, scope, depth):
        charge_array(translator, 1)
        if depth > 96:
            fail("Empty Feature map callback exceeds the serialized depth limit")
        if type(value) not in (dict, list):
            return 0
        key = (id(value), id(scope))
        if key in active:
            fail("Empty Feature map callback contains a serialized cycle")
        cached = complete.get(key)
        if cached is not None:
            height = cached[2]
            if depth + height > 96:
                fail("Empty Feature map callback exceeds the serialized depth limit")
            return height
        active.add(key)
        height = 0

        def descend(child, child_scope=scope):
            nonlocal height
            height = max(height, 1 + walk(child, child_scope, depth + 1))

        try:
            if type(value) is list:
                if len(value) > 10000:
                    fail("Inline list exceeds 10000 values in empty Feature map")
                charge_array(translator, len(value))
                for child in value:
                    descend(child)
            else:
                kind = value.get("type")
                if kind is not None and type(kind) is not str:
                    fail("Empty Feature map callback has an invalid serialized value type")
                if kind == "ValueRef":
                    reference = value.get("value")
                    if type(reference) is not str or reference not in scope:
                        fail("Empty Feature map callback has an unknown value reference")
                    descend(scope[reference])
                elif kind == "CompoundValue":
                    pairs = value.get("scope", [])
                    if type(pairs) is not list:
                        fail("Empty Feature map callback has an invalid scope")
                    charge_array(translator, len(scope) + 3 * len(pairs))
                    nested = dict(scope)
                    for pair in pairs:
                        if (type(pair) is not list or len(pair) != 2
                                or type(pair[0]) is not str or pair[0] in nested):
                            fail("Empty Feature map callback has an invalid scope reference")
                        nested[pair[0]] = pair[1]
                    descend(value.get("value"), nested)
                elif kind == "Invocation":
                    arguments = value.get("arguments", {})
                    if type(arguments) is not dict:
                        fail("Empty Feature map callback arguments must be an object")
                    charge_array(translator, 3 * len(arguments))
                    for argument in arguments:
                        if type(argument) is not str:
                            fail("Empty Feature map callback argument names must be strings")
                        charge_array(translator, len(argument))
                    if "functionName" in value:
                        name = value["functionName"]
                        if type(name) is not str:
                            fail("Empty Feature map callback algorithm name must be a string")
                        charge_array(translator, len(name))
                        if name not in SUPPORTED_FUNCTIONS:
                            fail(f"Unsupported Earth Engine algorithm in empty Feature map: {name}")
                        contract = _contract(name)
                        if contract is not None:
                            required, optional = contract
                            translator.allowed(arguments, required | optional)
                            if required - arguments.keys():
                                fail(f"{name} is missing required arguments in empty Feature map")
                    else:
                        descend(value.get("function"))
                    for child in arguments.values():
                        descend(child)
                elif kind == "Function":
                    descend(value.get("body"))
                elif kind == "Dictionary":
                    entries = value.get("value", {})
                    if type(entries) is not dict:
                        fail("Empty Feature map callback dictionary must be an object")
                    charge_array(translator, len(entries))
                    for child in entries.values():
                        descend(child)
                elif kind in GEOMETRY_TYPES or kind == "ArgumentRef":
                    pass
                elif kind:
                    fail(f"Unsupported serialized value type in empty Feature map: {kind}")
                else:
                    charge_array(translator, len(value))
                    for child in value.values():
                        descend(child)
        finally:
            active.remove(key)
        charge_array(translator, 1)
        # Retain both identities for this bounded walk, including temporary
        # CompoundValue scopes, so recycled ids cannot authorize a cache hit.
        # Reusing a shallow occurrence must not hide the same subtree's true
        # depth when it is reached under a longer path later in this DAG.
        complete[key] = (value, scope, height)
        return height

    walk(function.body, translator.scope, 0)
