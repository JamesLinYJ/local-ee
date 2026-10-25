"""Static values, metadata and geometry operations for inline Features."""
from __future__ import annotations

import math

import numpy as np

from .array_values import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray
from .geometry_components import own_component_geometry_bounded
from .geometry_values import GEOMETRY_TYPES
from .geometry_topology import geometry_edge_models as _geometry_edge_models
from .ir import Image, Pixel, fail


FEATURE_VALUE_METHODS = frozenset({
    "Feature.geometry", "Element.get", "Element.set", "Element.setMulti",
    "Element.propertyNames", "Element.copyProperties",
})
FEATURE_GEOMETRY_ARGUMENTS = {
    "Feature.geometry": (
        frozenset({"feature"}), frozenset({"maxError", "proj", "geodesics"}),
    ),
}
MAX_PROPERTY_NAMES = 10000


def is_feature(value):
    return isinstance(value, dict) and value.get("type") == "Feature"


def is_collection(value):
    return isinstance(value, dict) and value.get("type") == "FeatureCollection"


def charge(translator, amount=1):
    translator.steps += amount
    if translator.steps > 50000:
        fail("Earth Engine graph exceeds compilation limits")


def validate_json_value(translator, value, depth=0):
    """Require bounded JSON metadata while retaining finite StaticArray IR."""
    charge(translator)
    if depth > 96:
        fail("Feature properties exceed the metadata depth limit")
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return
    if type(value) is float:
        if not math.isfinite(value):
            fail("Feature properties must contain finite JSON numbers")
        return
    if isinstance(value, StaticArray):
        array = value.data
        if (array.size > MAX_ARRAY_CELLS or array.ndim > MAX_ARRAY_RANK
                or not np.isfinite(array).all()):
            fail("Feature StaticArray properties exceed finite array limits")
        charge(translator, int(array.size))
        return
    if isinstance(value, Image):
        # Inner joins retain concrete source Images as Feature properties.
        # Validate their public metadata without replacing the pixel graph by
        # a description; downstream ee.Image(feature.get(...)) needs that IR.
        if value.mapped:
            fail("Feature properties require concrete local Images")
        validate_json_value(translator, value.props, depth + 1)
        charge(translator, len(value.bands))
        for name, pixel in value.bands:
            if not isinstance(name, str) or not isinstance(pixel, Pixel):
                fail("Feature Image properties require valid named pixel bands")
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            fail("Feature property names must be strings")
        charge(translator, len(value))
        for child in value.values():
            validate_json_value(translator, child, depth + 1)
        return
    if isinstance(value, list):
        charge(translator, len(value))
        for child in value:
            validate_json_value(translator, child, depth + 1)
        return
    fail("Inline Feature properties must be static JSON, finite ee.Array or concrete Images")


def validate_feature(translator, value):
    if not is_feature(value):
        fail("Expected an inline Feature")
    geometry = value.get("geometry")
    if geometry is not None and (
        not isinstance(geometry, dict) or geometry.get("type") not in GEOMETRY_TYPES
    ):
        fail("Inline Feature geometry must be decoded GeoJSON or null")
    properties = value.get("properties")
    if not isinstance(properties, dict) or not all(isinstance(key, str) for key in properties):
        fail("Inline Feature properties must be a dictionary with string keys")
    if "id" in value and not isinstance(value["id"], str):
        fail("Inline Feature ids must be strings")
    for child in properties.values():
        validate_json_value(translator, child)
    return value


def with_properties(feature, properties):
    return {**feature, "properties": properties}


def property_name(value):
    if not isinstance(value, str):
        fail("Feature property names must be strings")
    return value


def property_names(value, label):
    if not isinstance(value, list) or len(value) > MAX_PROPERTY_NAMES:
        fail(f"{label} must be a list of at most {MAX_PROPERTY_NAMES} property names")
    if any(not isinstance(name, str) for name in value):
        fail(f"{label} must contain only strings")
    return value


def _invoke_element(translator, name, arguments):
    a = arguments
    if name in {"Element.get", "Element.set", "Element.setMulti", "Element.propertyNames"}:
        allowed = {
            "Element.get": {"object", "property"},
            "Element.set": {"object", "key", "value"},
            "Element.setMulti": {"object", "properties"},
            "Element.propertyNames": {"element"},
        }[name]
        translator.allowed(a, allowed)
        key = "element" if name == "Element.propertyNames" else "object"
        feature = validate_feature(translator, a[key])
        properties = feature["properties"]
        if name == "Element.get":
            result = properties.get(property_name(a.get("property")))
            validate_json_value(translator, result)
            return result
        if name == "Element.propertyNames":
            charge(translator, len(properties))
            if len(properties) > MAX_PROPERTY_NAMES:
                fail(f"Feature.propertyNames supports at most {MAX_PROPERTY_NAMES} properties")
            return list(properties)
        updated = dict(properties)
        if name == "Element.set":
            updated[property_name(a.get("key"))] = a.get("value")
        else:
            values = a.get("properties")
            if not isinstance(values, dict) or not all(isinstance(k, str) for k in values):
                fail("Element.setMulti properties must be a dictionary with string keys")
            for value in values.values():
                validate_json_value(translator, value)
            updated.update(values)
        for value in updated.values():
            validate_json_value(translator, value)
        return with_properties(feature, updated)
    if name == "Element.copyProperties":
        translator.allowed(a, {"destination", "source", "properties", "exclude"})
        destination = validate_feature(translator, a.get("destination"))
        source = validate_feature(translator, a.get("source"))
        names = a.get("properties")
        excluded = a.get("exclude")
        if names is not None and excluded is not None:
            fail("copyProperties cannot use properties and exclude together")
        names = (
            [key for key in source["properties"] if not key.startswith("system:")]
            if names is None else property_names(names, "copyProperties properties")
        )
        excluded = [] if excluded is None else property_names(excluded, "copyProperties exclude")
        charge(translator, len(names) + len(excluded))
        props = dict(destination["properties"])
        for key in names:
            if key not in excluded and key in source["properties"]:
                props[key] = source["properties"][key]
        for value in props.values():
            validate_json_value(translator, value)
        return with_properties(destination, props)
    fail(f"Unsupported Earth Engine algorithm: {name}")


def invoke_feature_value(translator, name, arguments):
    """Evaluate Feature.geometry and Element metadata calls for static Features."""
    a = arguments
    if name == "Feature.geometry":
        required, optional = FEATURE_GEOMETRY_ARGUMENTS[name]
        translator.allowed(a, required | optional)
        missing = required - a.keys()
        if missing:
            fail(f"{name} requires arguments: {sorted(missing)}")
        max_error = a.get("maxError")
        projection = a.get("proj")
        geodesics = a.get("geodesics")
        if max_error is not None:
            fail("Feature.geometry maxError reprojection is unsupported")
        if projection is not None and projection != "EPSG:4326":
            fail("Feature.geometry supports only the existing EPSG:4326 geometry")
        if geodesics is not None and type(geodesics) is not bool:
            fail("Feature.geometry geodesics must be a boolean or null")
        feature = validate_feature(translator, a.get("feature"))
        geometry = feature["geometry"]
        if geometry is None:
            return None
        scan_cost = None
        if projection is not None and geodesics is not None:
            # The subsequent model walk revisits the copied geometry and the
            # coordinate-bearing leaves. Reserve that work before the walk.
            from .geometry_preflight import measure_geometry

            scan_cost = measure_geometry(geometry)
        owned = own_component_geometry_bounded(translator, geometry)
        # Per the pinned SDK, geodesics is ignored unless a projection is
        # specified. With the only admitted projection (EPSG:4326), changing
        # an existing edge model would still require a geometry transform.
        if scan_cost is not None:
            charge(translator, scan_cost.nodes + scan_cost.positions)
            if any(model is not geodesics for model in _geometry_edge_models(owned)):
                fail("Feature.geometry geodesic edge-model conversion is unsupported")
        return owned
    return _invoke_element(translator, name, a)
