"""Fresh source-grid, observation-time and footprint proofs for linked rasters."""
from __future__ import annotations

import math

from .image_collection_link_common import charge
from .ir import Image, Pixel, Source, fail


def _charge_geojson(translator, value, label):
    """Bound GeoJSON traversal before footprint operations allocate shapes."""
    stack = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > 96:
            fail(f"{label} footprint exceeds the geometry depth limit")
        kind = type(current)
        if isinstance(current, dict):
            charge(translator, 1 + len(current), label + " footprint proof")
            for key, child in current.items():
                if type(key) is not str:
                    fail(f"{label} footprint has a non-string key")
                charge(translator, len(key), label + " footprint proof")
                stack.append((child, depth + 1))
        elif isinstance(current, (list, tuple)):
            charge(translator, 1 + len(current), label + " footprint proof")
            stack.extend((child, depth + 1) for child in current)
        elif kind is str:
            charge(translator, 1 + len(current), label + " footprint proof")
        elif kind is bool or current is None:
            charge(translator, 1, label + " footprint proof")
        elif kind is int:
            charge(translator, max(1, current.bit_length()), label + " footprint proof")
            if abs(current) > 10**15:
                fail(f"{label} footprint coordinate is out of range")
        elif kind is float:
            if not math.isfinite(current) or abs(current) > 10**15:
                fail(f"{label} footprint coordinates must be finite and in range")
            charge(translator, 1, label + " footprint proof")
        else:
            fail(f"{label} footprint is not finite GeoJSON")


def _lookup(translator, cid, lookups):
    if cid not in lookups:
        from .numeric_reducer_grid import _item_lookup

        lookups[cid] = _item_lookup(translator, cid)
    return lookups[cid]


def _geometry(translator, value, label):
    if value is None:
        fail(f"{label} has no actual source footprint")
    from .geometry_values import GEOMETRY_TYPES

    if not isinstance(value, dict) or value.get("type") not in GEOMETRY_TYPES:
        fail(f"{label} footprint is not a supported GeoJSON geometry")
    _charge_geojson(translator, value, label)
    from shapely.geometry import shape

    try:
        result = shape(value)
    except (TypeError, ValueError, KeyError, RecursionError):
        fail(f"{label} footprint is invalid GeoJSON")
    if result.is_empty or not result.is_valid:
        fail(f"{label} footprint must be nonempty valid geometry")
    return result


def _validated_source(translator, source, label):
    if (not isinstance(source, Source) or type(source.cid) is not str
            or not source.cid or type(source.ids) is not tuple
            or not source.ids or len(source.ids) > 1000):
        fail(f"{label} requires a valid finite source lineage")
    charge(translator, 1 + len(source.cid) + len(source.ids), label + " source scan")
    seen = set()
    for item_id in source.ids:
        if type(item_id) is not str or not item_id:
            fail(f"{label} requires nonempty string image IDs")
        charge(translator, len(item_id), label + " source scan")
        if item_id in seen:
            fail(f"{label} contains duplicate source image IDs")
        seen.add(item_id)
    return source


def _effective_footprint(translator, image, label, lookups):
    source = image.source
    if isinstance(source, Source):
        source = _validated_source(translator, source, label + " footprint")
        lookup = _lookup(translator, source.cid, lookups)
        shapes = []
        from shapely.ops import unary_union

        for item_id in source.ids:
            item = lookup.get(item_id)
            if item is None:
                fail(f"{label} source item is unavailable for footprint validation")
            shapes.append(_geometry(translator, item.get("geometry"), label))
        base = unary_union(shapes)
        if image.footprint_is_absolute and image.footprint is not None:
            return _geometry(translator, image.footprint, label)
        if image.footprint is not None:
            clip = _geometry(translator, image.footprint, label)
            base = base.intersection(clip)
        if base.is_empty or not base.is_valid:
            fail(f"{label} footprint must be nonempty valid geometry")
        return base
    if image.footprint is None:
        return None
    if not image.footprint_is_absolute:
        fail(f"{label} source-free footprint must be explicitly absolute")
    return _geometry(translator, image.footprint, label)


def _time_start(translator, item, cid, label):
    properties = item.get("properties", {})
    if type(properties) is not dict or len(properties) > 10_000:
        fail(f"{label} source properties are malformed or exceed 10000 entries")
    charge(translator, 1 + len(properties), label + " source property scan")
    for key, property_value in properties.items():
        if type(key) is not str:
            fail(f"{label} source property names must be strings")
        charge(translator, len(key), label + " source property scan")
        charge(
            translator,
            len(property_value) + 1 if type(property_value) is str else 1,
            label + " source property value scan",
        )
    properties = translator._base_properties(item, cid)
    charge(translator, len("system:time_start") + 1, label + " timestamp proof")
    value = properties.get("system:time_start")
    if type(value) not in (int, float) or not math.isfinite(value):
        fail(f"{label} requires an actual finite system:time_start")
    return value


def require_pair_alignment(translator, primary, secondary, pixels, label):
    """Prove every pixel lineage is on the primary time, grid and footprint.

    Wrapper fields alone do not prove alignment: addBands can retain one
    Image.source while its band pixels refer to another item or collection.
    Inspect the exact pixel DAGs that will be combined and reject multi-item
    lineages rather than guessing which temporal slice they mean.
    """
    from .numeric_reducer_grid import _collect, _projection_for_item
    from .numeric_reducer_projection import same_grid

    if not isinstance(primary.source, Source):
        fail(f"{label} requires one actual primary observation")
    _validated_source(translator, primary.source, label + " primary")
    if len(primary.source.ids) != 1:
        fail(f"{label} requires one actual primary observation")
    lookups = {}
    primary_lookup = _lookup(translator, primary.source.cid, lookups)
    primary_item = primary_lookup.get(primary.source.ids[0])
    if primary_item is None:
        fail(f"{label} primary source item is unavailable")
    primary_time = _time_start(translator, primary_item, primary.source.cid, label)
    primary_geometry = _geometry(
        translator, primary_item.get("geometry"), label + " primary",
    )
    primary_footprint = _effective_footprint(
        translator, primary, label + " primary", lookups,
    )
    if primary_footprint is None:
        fail(f"{label} requires a finite primary raster footprint")
    linked_footprint = _effective_footprint(
        translator, secondary, label + " linked", lookups,
    )
    if linked_footprint is not None and not primary_footprint.equals(linked_footprint):
        fail(f"{label} requires equal actual image footprints")

    sources, selectors = _collect(translator, pixels)
    if not sources:
        fail(f"{label} requires actual source projection evidence")
    if (primary.source.cid, primary.source.ids) not in sources:
        fail(f"{label} pixel DAG does not retain the actual primary source")

    projections = []
    for (cid, ids), source in sources.items():
        if len(ids) != 1 or not ids[0]:
            fail(f"{label} raster pixels require one observation per lineage")
        lookup = _lookup(translator, cid, lookups)
        item = lookup.get(ids[0])
        if item is None:
            fail(f"{label} source item is unavailable for alignment validation")
        if _time_start(translator, item, cid, label) != primary_time:
            fail(f"{label} requires equal actual source timestamps for raster alignment")
        geometry = _geometry(translator, item.get("geometry"), label + " linked")
        if not primary_geometry.equals(geometry):
            fail(f"{label} requires equal actual source footprints")

        selected = selectors.get((cid, ids), set())
        if not selected:
            selected = set(source.names)
        projections.extend(_projection_for_item(item, ids[0], selected, translator))

    if not projections:
        fail(f"{label} requires actual source projection evidence")
    charge(translator, len(projections), label + " common-grid proof")
    reference_crs, reference_transform = projections[0]
    for crs, transform in projections[1:]:
        if not same_grid(
                reference_transform, transform,
                left_crs=reference_crs, right_crs=crs):
            fail(f"{label} requires a proven common pixel grid")


def _pixel_cost(translator, pixels, label):
    charge(translator, 1 + len(pixels), label + " pixel stack")
    stack = list(pixels)
    seen = set()
    while stack:
        value = stack.pop()
        if isinstance(value, (tuple, list)):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            charge(translator, 1 + len(value), label + " pixel scan")
            stack.extend(value)
        elif isinstance(value, Pixel):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            charge(translator, 1 + len(value.args), label + " pixel scan")
            stack.extend(value.args)
        elif isinstance(value, Source):
            charge(translator, 1 + len(value.cid), label + " source scan")
            for item_id in value.ids:
                charge(translator, len(item_id), label + " source scan")
