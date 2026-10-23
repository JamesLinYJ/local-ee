"""Reject contradictory single-item asset grids before native selection merges."""
from __future__ import annotations

from .ir import fail
from .numeric_reducer_projection import asset_projection, item_projection, same_grid


def require_single_item_grid(translator, cid, item_id, selectors):
    from .numeric_reducer_grid import _charge, _item_lookup

    item = _item_lookup(translator, cid).get(item_id)
    if item is None:
        fail("Float64 selection source item is unavailable for grid validation")
    _charge(translator, 1 + len(selectors))
    _crs, _transform, item_crs_values, item_transforms = item_projection(item)
    crs_values = list(item_crs_values)
    transforms = list(item_transforms)
    for name in selectors:
        _charge(translator, 1 + len(name))
        asset_crs, asset_transform = asset_projection(item, name)
        if asset_crs is not None:
            crs_values.append(asset_crs)
        if asset_transform is not None:
            transforms.append(asset_transform)
    # Retain the existing single-item grid contract when optional projection
    # fields are absent. Explicit contradictions cannot authorize resampling.
    if crs_values and any(value != crs_values[0] for value in crs_values[1:]):
        fail("Float64 selection single-item asset CRS evidence conflicts")
    if transforms:
        _charge(translator, len(transforms))
        if any(not same_grid(transforms[0], value, check_crs=False)
               for value in transforms[1:]):
            fail("Float64 selection requires a proven common pixel grid for selected assets")
