"""Metadata-aware adapters for finite, locally indexed EE image collections.

The normal collection map path compiles one pixel expression over a collection.
That remains the fast path for callbacks that do not read item metadata. This
module only detects metadata reads rooted in the callback's image argument and
provides a bounded explicit-frame adapter for those callbacks.

This operates on the official serialized expression tree; it never evaluates
JavaScript or interprets source text.
"""
from __future__ import annotations

from typing import Any, Mapping


# These methods obtain per-image metadata, geometry, or property names. The
# argument names are those emitted by the pinned Earth Engine serializer.
_METADATA_READS = {
    "Image.date": ("image",),
    # The official serializer calls the Image.geometry receiver `feature`.
    "Image.geometry": ("feature", "image"),
    # unmask reads both operands' per-image masks/footprints. Keep its mapped
    # output property lineage separate: Image.unmask inherits properties from
    # its input receiver, not from the replacement image.
    "Image.unmask": ("input", "value"),
    "Image.get": ("image", "object"),
    "Element.get": ("object", "image"),
    "Element.propertyNames": ("element", "object", "image"),
}

# Track only receivers whose result is image-like and may carry, derive, or
# intentionally drop image properties. This avoids treating an unrelated
# captured image's static get()/date() call as varying with the mapped item.
_IMAGE_RECEIVERS = {
    "Image": ("value", "image", "input"),
    # Numeric casts retain image-level properties. The pinned serializer
    # writes the receiver image under `value` for both methods.
    "Image.toFloat": ("value",),
    "Image.toDouble": ("value",),
    "Image.select": ("input",),
    "Image.rename": ("input",),
    "Image.addBands": ("dstImg",),
    "Image.normalizedDifference": ("input",),
    "Image.expression": ("image", "input"),
    "Image.updateMask": ("image",),
    "Image.mask": ("image",),
    "Image.unmask": ("input",),
    "Image.where": ("input",),
    "Image.clamp": ("input",),
    "Image.unitScale": ("input",),
    "Image.reduce": ("image",),
    "Image.clip": ("input",),
    "Image.copyProperties": ("destination", "source"),
    "Element.copyProperties": ("destination", "source"),
    "Element.set": ("object",),
    "Element.setMulti": ("object",),
    "Image.add": ("image1",),
    "Image.subtract": ("image1",),
    "Image.multiply": ("image1",),
    "Image.divide": ("image1",),
    "Image.pow": ("image1",),
    "Image.mod": ("image1",),
    "Image.eq": ("image1",),
    "Image.neq": ("image1",),
    "Image.gt": ("image1",),
    "Image.gte": ("image1",),
    "Image.lt": ("image1",),
    "Image.lte": ("image1",),
    "Image.and": ("image1",),
    "Image.or": ("image1",),
    "Image.min": ("image1",),
    "Image.max": ("image1",),
    "Image.abs": ("image", "value"),
    "Image.sqrt": ("image", "value"),
    "Image.log": ("image", "value"),
    "Image.log10": ("image", "value"),
    "Image.exp": ("image", "value"),
    "Image.round": ("image", "value"),
    "Image.floor": ("image", "value"),
    "Image.ceil": ("image", "value"),
    "Image.sin": ("image", "value"),
    "Image.cos": ("image", "value"),
    "Image.tan": ("image", "value"),
    "Image.not": ("image", "value"),
}


def _flows_from_argument(value: Any, argument: str, scope: Mapping[str, Any],
                         seen: frozenset[str] = frozenset(), memo: dict | None = None) -> bool:
    """Whether an image expression is derived from this map callback argument."""
    memo = {} if memo is None else memo
    if not isinstance(value, dict):
        return False
    kind = value.get("type")
    if kind == "ArgumentRef":
        return value.get("value") == argument
    if kind == "CompoundValue":
        local = dict(scope)
        for pair in value.get("scope", []):
            if isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], str):
                local[pair[0]] = pair[1]
        return _flows_from_argument(value.get("value"), argument, local, seen, memo)
    if kind == "ValueRef":
        key = value.get("value")
        if not isinstance(key, str) or key in seen or key not in scope:
            return False
        cache_key = (id(scope), key, argument)
        cached = memo.get(cache_key)
        if cached is not None and cached[0] is scope:
            return cached[1]
        # Serialized EE scopes are DAGs. Memoizing each shared ValueRef avoids
        # rewalking a diamond-shaped expression exponentially many times. Keep
        # the scope alive with the entry: CompoundValue creates temporary scope
        # dictionaries, and an id-only key could otherwise be reused later.
        memo[cache_key] = (scope, False)
        result = _flows_from_argument(scope[key], argument, scope, seen | {key}, memo)
        memo[cache_key] = (scope, result)
        return result
    if kind != "Invocation":
        return False
    name = value.get("functionName")
    selected = _IMAGE_RECEIVERS.get(name, ())
    arguments = value.get("arguments", {})
    return any(_flows_from_argument(arguments.get(key), argument, scope, seen, memo) for key in selected)


def _contains_mapped_metadata_read(value: Any, argument: str, scope: Mapping[str, Any],
                                   seen: frozenset[str] = frozenset(), memo: dict | None = None,
                                   flow_memo: dict | None = None) -> bool:
    """Walk a callback body and find metadata reads on the mapped image lineage."""
    memo = {} if memo is None else memo
    flow_memo = {} if flow_memo is None else flow_memo
    if isinstance(value, list):
        return any(_contains_mapped_metadata_read(item, argument, scope, seen, memo, flow_memo) for item in value)
    if not isinstance(value, dict):
        return False
    kind = value.get("type")
    if kind == "CompoundValue":
        local = dict(scope)
        for pair in value.get("scope", []):
            if isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], str):
                local[pair[0]] = pair[1]
        return _contains_mapped_metadata_read(value.get("value"), argument, local, seen, memo, flow_memo)
    if kind == "ValueRef":
        key = value.get("value")
        if not isinstance(key, str) or key in seen or key not in scope:
            return False
        cache_key = (id(scope), key, argument)
        cached = memo.get(cache_key)
        if cached is not None and cached[0] is scope:
            return cached[1]
        # Retain and verify scope identity for the same reason as the lineage
        # memo above; a transient CompoundValue scope must not inherit another
        # lexical scope's cached result if Python recycles its id.
        memo[cache_key] = (scope, False)
        result = _contains_mapped_metadata_read(scope[key], argument, scope, seen | {key}, memo, flow_memo)
        memo[cache_key] = (scope, result)
        return result
    if kind == "Function":
        # ArgumentRef values are lexical names in the EE wire format. A nested
        # callback that reuses the outer name shadows it; a differently named
        # callback can still close over the mapped image and remains searchable.
        if argument in value.get("argumentNames", []):
            return False
        return _contains_mapped_metadata_read(value.get("body"), argument, scope, seen, memo, flow_memo)
    if kind == "Invocation":
        name = value.get("functionName")
        arguments = value.get("arguments", {})
        receiver_names = _METADATA_READS.get(name, ())
        if any(_flows_from_argument(arguments.get(key), argument, scope, memo=flow_memo) for key in receiver_names):
            return True
    # The traversal is for discovery only; it does not evaluate an invocation.
    return any(_contains_mapped_metadata_read(child, argument, scope, seen, memo, flow_memo) for child in value.values())


def requires_item_metadata(function: Any, scope: Mapping[str, Any] | None = None) -> bool:
    """Return true only for map callbacks reading metadata from their argument.

    Pass the translator's serialized scope so official SDK ValueRefs inside a
    callback body are inspected. Static reads on captured objects do not make a
    callback item-dependent.
    """
    names = getattr(function, "names", None)
    body = getattr(function, "body", None)
    if not isinstance(names, list) or len(names) != 1:
        return False
    return _contains_mapped_metadata_read(body, names[0], scope or {})


def evaluate_per_image_map(translator: Any, collection: Any, function: Any, drop_nulls: bool = False):
    """Evaluate a metadata-dependent map over bounded, ordered item frames.

    The finite frame materializer is shared with explicit ``fromImages(toList())``
    operations. It rebinds each immutable local item ID before callback
    evaluation, preserving observations that share a timestamp. This helper
    does not invent a timestamp, create constant rasters, or suppress failures.
    """
    from .ee_collections import frames, invoke_sequence
    from .compat.earthengine.ir import ImageSequence

    return invoke_sequence(translator, "Collection.map", {
        "collection": ImageSequence(frames(translator, collection)),
        "baseAlgorithm": function,
        "dropNulls": bool(drop_nulls),
    })


__all__ = ["evaluate_per_image_map", "requires_item_metadata"]
