"""Grid proof for typed numeric reductions over finite raster observations.

Earth Engine export scale/crs options are applied after a reduction and cannot
prove that source pixels were aligned before values were combined.
"""
from __future__ import annotations

from .ir import Pixel, Source, fail
from .numeric_reducer_projection import asset_projection, item_projection, same_grid


MAX_GRID_VALIDATION_WORK = 50_000
MAX_GRID_SOURCE_IDS = 1_000


def _charge(translator, amount: int) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or amount < 0 or amount > MAX_GRID_VALIDATION_WORK
            or steps + amount > MAX_GRID_VALIDATION_WORK):
        fail("Numeric raster grid validation exceeds the shared 50000-step work budget")
    translator.steps = steps + amount


def _source_key(translator, source: Source):
    if (type(source.cid) is not str or not source.cid or type(source.ids) is not tuple
            or not source.ids or len(source.ids) > MAX_GRID_SOURCE_IDS):
        fail("Numeric raster grid validation requires a valid finite source lineage")
    _charge(translator, 1 + len(source.cid) + len(source.ids))
    id_chars = 0
    for item_id in source.ids:
        if type(item_id) is not str or not item_id:
            fail("Numeric raster grid validation requires a valid finite source lineage")
        id_chars += len(item_id)
    _charge(translator, id_chars)
    if len(set(source.ids)) != len(source.ids):
        fail("Numeric raster grid validation requires a valid finite source lineage")
    return source.cid, source.ids


def _collect(translator, pixels):
    if type(pixels) not in (tuple, list) or not pixels:
        fail("Numeric raster grid validation requires nonempty Pixel operands")
    _charge(translator, len(pixels))
    sources = {}
    selectors = {}
    source_memo = {}
    stack = list(pixels)
    seen = set()

    def register(source):
        identity = id(source)
        cached = source_memo.get(identity)
        if cached is not None and cached[0] is source:
            return cached[1]
        key = _source_key(translator, source)
        source_memo[identity] = (source, key)
        sources.setdefault(key, source)
        return key

    while stack:
        value = stack.pop()
        _charge(translator, 1)
        if isinstance(value, Source):
            register(value)
            continue
        if isinstance(value, (tuple, list)):
            identity = id(value)
            if identity in seen:
                continue
            seen.add(identity)
            _charge(translator, len(value))
            stack.extend(value)
            continue
        if not isinstance(value, Pixel):
            continue
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        _charge(translator, 1 + len(value.args))
        if value.op == "band":
            if (len(value.args) != 2 or not isinstance(value.args[0], Source)
                    or type(value.args[1]) is not str or not value.args[1]):
                fail("Numeric raster grid validation found a malformed band selector")
            source = value.args[0]
            key = register(source)
            _charge(translator, len(value.args[1]))
            selectors.setdefault(key, set()).add(value.args[1])
        stack.extend(value.args)

    source_free = 0
    from .pixel_math_graph import _PixelFactsWalker

    walker = _PixelFactsWalker(translator)
    for pixel in pixels:
        if not walker.inspect(pixel).sources:
            source_free += 1
    if sources and source_free:
        fail("Numeric raster reduction cannot align source-free operands with raster pixels")
    return sources, selectors


def _item_lookup(translator, cid):
    items = getattr(translator, "items", None)
    if type(items) is not dict:
        fail("Numeric raster grid item catalogue is unavailable")
    rows = items.get(cid)
    if type(rows) is dict:
        if len(rows) > MAX_GRID_VALIDATION_WORK:
            fail("Numeric raster grid item catalogue exceeds the bounded lookup budget")
        _charge(translator, len(rows))
        id_chars = 0
        for item_id, item in rows.items():
            if (type(item_id) is not str or not item_id or type(item) is not dict
                    or item.get("id") != item_id):
                fail("Numeric raster grid item catalogue has an invalid item ID")
            id_chars += len(item_id)
        _charge(translator, id_chars)
        return rows
    if type(rows) not in (list, tuple) or len(rows) > MAX_GRID_VALIDATION_WORK:
        fail("Numeric raster grid item catalogue exceeds the bounded lookup budget")
    _charge(translator, len(rows))
    id_chars = 0
    for item in rows:
        if type(item) is not dict or type(item.get("id")) is not str or not item["id"]:
            fail("Numeric raster grid item catalogue has an invalid item ID")
        id_chars += len(item["id"])
    _charge(translator, id_chars)
    lookup = {}
    for item in rows:
        item_id = item["id"]
        if item_id in lookup:
            fail("Numeric raster grid item catalogue contains duplicate item IDs")
        lookup[item_id] = item
    return lookup


def _projection_for_item(item, item_id, selectors, translator):
    _charge(translator, 1 + len(item_id) + len(selectors))
    item_crs, item_transform, item_crs_values, item_transforms = item_projection(item)
    projections = []
    asset_names = tuple(sorted(selectors))
    for asset_name in asset_names:
        asset_crs, asset_transform = asset_projection(item, asset_name)
        crs = asset_crs or item_crs
        transform = asset_transform or item_transform
        if crs is None or transform is None:
            fail("Multiple raster observations require complete proj:code/epsg and proj:transform evidence")
        for fallback_crs in item_crs_values:
            if fallback_crs != crs:
                fail("Raster asset and item CRS evidence conflict")
        for fallback_transform in item_transforms:
            if not same_grid(transform, fallback_transform, check_crs=False):
                fail("Raster asset and item affine evidence conflict")
        projections.append((crs, transform))
    if not projections:
        if item_crs is None or item_transform is None:
            fail("Multiple raster observations require complete item projection evidence")
        projections.append((item_crs, item_transform))
    return projections


def require_common_grid(translator, pixels, *, label="numeric raster reduction",
                        check_single_item_assets=False) -> None:
    """Require source-aligned pixels before combining distinct raster item IDs.

    Pixels are the exact scalar operands about to be merged. One distinct item
    keeps the existing one-source contract. Multiple collection CIDs or
    source-free operands cannot prove implicit alignment.
    """
    sources, selectors = _collect(translator, pixels)
    if not sources:
        return
    _charge(translator, len(sources))
    cids = {cid for cid, _ids in sources}
    if len(cids) != 1:
        fail(f"{label} cannot merge distinct collection lineages implicitly")
    _charge(translator, len(sources))
    distinct_count = sum(len(ids) for _cid, ids in sources)
    _charge(translator, distinct_count)
    distinct_ids = tuple(dict.fromkeys(
        item_id for _cid, ids in sources for item_id in ids
    ))
    if len(distinct_ids) <= 1:
        if check_single_item_assets:
            from .selection_grid import require_single_item_grid

            _charge(translator, sum(len(names) for names in selectors.values()))
            selected = set().union(*selectors.values())
            require_single_item_grid(
                translator, next(iter(cids)), distinct_ids[0], selected,
            )
        return

    cid = next(iter(cids))
    item_lookup = _item_lookup(translator, cid)
    projections = []
    for lineage, source in sources.items():
        _cid, ids = lineage
        selected = selectors.get(lineage, set())
        if not selected:
            names = source.names
            if type(names) is not tuple or len(names) > MAX_GRID_VALIDATION_WORK:
                fail("Numeric raster grid validation requires valid band selectors")
            _charge(translator, len(names))
            name_chars = 0
            for name in names:
                if type(name) is not str or not name:
                    fail("Numeric raster grid validation requires valid band selectors")
                name_chars += len(name)
            _charge(translator, name_chars)
            selected = set(names)
        for item_id in ids:
            item = item_lookup.get(item_id)
            if item is None:
                fail("Numeric raster source item is unavailable for grid validation")
            for crs, transform in _projection_for_item(
                    item, item_id, selected, translator):
                projections.append((item_id, crs, transform))

    if not projections:
        fail("Multiple raster observations require proven projection grids")
    _charge(translator, len(projections))
    _reference_id, reference_crs, reference_transform = projections[0]
    for _item_id, crs, transform in projections[1:]:
        if not same_grid(
                reference_transform, transform, left_crs=reference_crs,
                right_crs=crs):
            fail("Numeric raster reductions require a proven common pixel grid")
