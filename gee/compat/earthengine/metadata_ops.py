"""Properties and property-copy operations on decoded Earth Engine values."""
from __future__ import annotations

import json
from dataclasses import replace

from .ir import fail


METADATA_HANDLERS = frozenset({
    "Element.get", "Image.get", "Element.propertyNames", "Element.set", "Element.setMulti",
    "Element.copyProperties", "Image.copyProperties",
})


def invoke_metadata(translator, name, arguments):
    a = arguments
    if name in {"Element.get", "Element.propertyNames", "Image.get"}:
        obj = a.get("object", a.get("image", a.get("element")))
        if name.endswith("propertyNames"):
            if obj.mapped:
                fail("propertyNames inside map depends on per-item metadata")
            return list(obj.props)
        key = a["property"]
        if key not in obj.props and obj.mapped:
            fail(f"Dynamic item metadata inside map is unsupported: {key}")
        return obj.props.get(key)
    if name in {"Element.set", "Element.setMulti"}:
        obj = a["object"]
        props = dict(obj.props)
        if name.endswith("setMulti"):
            props.update(a["properties"])
        else:
            props[a["key"]] = a["value"]
        if not all(isinstance(key, str) for key in props):
            fail("Metadata property names must be strings")
        try:
            json.dumps(props, allow_nan=False)
        except (TypeError, ValueError):
            fail("Only static JSON values may be stored in image metadata")
        return replace(obj, props=props)
    if name in {"Image.copyProperties", "Element.copyProperties"}:
        translator.allowed(a, {"destination", "source", "properties", "exclude"})
        destination, source = a["destination"], a["source"]
        names = a.get("properties")
        if names is not None and a.get("exclude"):
            fail("copyProperties cannot use properties and exclude together")
        if source.mapped:
            if destination.source != source.source:
                fail("Mapped copyProperties must use the same source image")
            if names is None:
                fail("copyProperties inside map currently requires an explicit property-name list")
        names = names if names is not None else [key for key in source.props if not key.startswith("system:")]
        props = dict(destination.props)
        for key in names:
            if key not in a.get("exclude", []) and key in source.props:
                props[key] = source.props[key]
        copied = tuple(dict.fromkeys((*destination.copied_props, *names)))
        return replace(destination, props=props, copied_props=copied)
    fail(f"Unsupported Earth Engine algorithm: {name}")
