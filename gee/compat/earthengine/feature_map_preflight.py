"""Validate serialized empty-map callback structure without inventing a row."""
from __future__ import annotations

from .array_core import charge_array
from .geometry_values import GEOMETRY_TYPES
from .ir import fail


def _contract(name):
    from .element_metadata_values import ELEMENT_METADATA_VALUE_ARGUMENTS
    from .feature_structure import FEATURE_STRUCTURE_ARGUMENTS
    from .filtering import FILTER_PREPARATION_ARGUMENTS
    from .geometry_structure import GEOMETRY_STRUCTURE_ARGUMENTS
    from .geometry_constructors import GEOMETRY_CONSTRUCTOR_ARGUMENTS

    for contracts in (
        ELEMENT_METADATA_VALUE_ARGUMENTS, FEATURE_STRUCTURE_ARGUMENTS,
        FILTER_PREPARATION_ARGUMENTS, GEOMETRY_STRUCTURE_ARGUMENTS,
        GEOMETRY_CONSTRUCTOR_ARGUMENTS,
    ):
        if name in contracts:
            return contracts[name]
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
            return
        key = (id(value), id(scope))
        if key in active:
            fail("Empty Feature map callback contains a serialized cycle")
        if key in complete:
            return
        active.add(key)
        try:
            if type(value) is list:
                if len(value) > 10000:
                    fail("Inline list exceeds 10000 values in empty Feature map")
                charge_array(translator, len(value))
                for child in value:
                    walk(child, scope, depth + 1)
            else:
                kind = value.get("type")
                if kind is not None and type(kind) is not str:
                    fail("Empty Feature map callback has an invalid serialized value type")
                if kind == "ValueRef":
                    reference = value.get("value")
                    if type(reference) is not str or reference not in scope:
                        fail("Empty Feature map callback has an unknown value reference")
                    walk(scope[reference], scope, depth + 1)
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
                    walk(value.get("value"), nested, depth + 1)
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
                        walk(value.get("function"), scope, depth + 1)
                    for child in arguments.values():
                        walk(child, scope, depth + 1)
                elif kind == "Function":
                    walk(value.get("body"), scope, depth + 1)
                elif kind == "Dictionary":
                    entries = value.get("value", {})
                    if type(entries) is not dict:
                        fail("Empty Feature map callback dictionary must be an object")
                    charge_array(translator, len(entries))
                    for child in entries.values():
                        walk(child, scope, depth + 1)
                elif kind in GEOMETRY_TYPES or kind == "ArgumentRef":
                    pass
                elif kind:
                    fail(f"Unsupported serialized value type in empty Feature map: {kind}")
                else:
                    charge_array(translator, len(value))
                    for child in value.values():
                        walk(child, scope, depth + 1)
        finally:
            active.remove(key)
        charge_array(translator, 1)
        # Retain both identities for this bounded walk, including temporary
        # CompoundValue scopes, so recycled ids cannot authorize a cache hit.
        complete[key] = (value, scope)

    walk(function.body, translator.scope, 0)
