"""Strict STAC projection evidence parsing for numeric raster grid checks.

Only CRS plus six-value affine transforms are considered. Affine basis
comparisons and pixel-origin offsets use exact binary-rational arithmetic.
"""
from __future__ import annotations

import math
from fractions import Fraction

from .ir import fail


_MAX_COORDINATE = 1e15


def _normal_crs(value, *, epsg=False):
    if epsg:
        if type(value) is not int or not 0 < value <= 2**31 - 1:
            fail("Numeric raster grid projection has an invalid proj:epsg")
        return f"EPSG:{value}"
    if type(value) is not str or not value or len(value) > 256:
        fail("Numeric raster grid projection has an invalid proj:code")
    normalized = value.strip()
    if not normalized:
        fail("Numeric raster grid projection has an invalid proj:code")
    if normalized[:5].upper() == "EPSG:":
        suffix = normalized[5:]
        if not suffix.isdigit() or int(suffix) <= 0:
            fail("Numeric raster grid projection has an invalid proj:code")
        return f"EPSG:{int(suffix)}"
    return normalized


def _field_crs(mapping):
    if type(mapping) is not dict:
        return None
    candidates = []
    if "proj:epsg" in mapping:
        candidates.append(_normal_crs(mapping["proj:epsg"], epsg=True))
    if "proj:code" in mapping:
        candidates.append(_normal_crs(mapping["proj:code"]))
    if candidates and any(value != candidates[0] for value in candidates[1:]):
        fail("Numeric raster grid projection contains conflicting CRS evidence")
    return candidates[0] if candidates else None


def _field_transform(mapping):
    if type(mapping) is not dict or "proj:transform" not in mapping:
        return None
    value = mapping["proj:transform"]
    if type(value) not in (list, tuple) or len(value) != 6:
        fail("Numeric raster grid projection requires a six-value affine transform")
    transform = []
    for component in value:
        if isinstance(component, bool) or type(component) not in (int, float):
            fail("Numeric raster grid projection has an invalid affine transform")
        if type(component) is int:
            if abs(component) > _MAX_COORDINATE:
                fail("Numeric raster grid projection has an invalid affine transform")
        elif not math.isfinite(component) or abs(component) > _MAX_COORDINATE:
            fail("Numeric raster grid projection has an invalid affine transform")
        transform.append(
            Fraction(component) if type(component) is int
            else Fraction.from_float(component)
        )
    a, b, _x, c, d, _y = transform
    determinant = a * d - b * c
    basis_scale = max(abs(a * d), abs(b * c))
    if (not math.isfinite(determinant) or determinant == 0 or basis_scale == 0
            or abs(determinant) * 10**12 <= basis_scale):
        fail("Numeric raster grid projection has a singular affine transform")
    return tuple(transform)


def same_grid(left, right, *, check_crs=True, left_crs=None, right_crs=None):
    """Check equal CRS/basis and an exact integer-pixel origin displacement."""
    if check_crs and left_crs != right_crs:
        return False
    if any(left[index] != right[index] for index in (0, 1, 3, 4)):
        return False
    a, b, _, c, d, _ = left
    dx, dy = right[2] - left[2], right[5] - left[5]
    determinant = a * d - b * c
    column = (dx * d - b * dy) / determinant
    row = (a * dy - dx * c) / determinant
    return column.denominator == 1 and row.denominator == 1


def item_projection(item):
    if type(item) is not dict:
        fail("Numeric raster grid metadata is unavailable")
    properties = item.get("properties", {})
    if type(properties) is not dict:
        fail("Numeric raster grid item properties are malformed")
    mappings = (item, properties)
    crs_values = [value for value in (_field_crs(mapping) for mapping in mappings)
                  if value is not None]
    transforms = [value for value in (_field_transform(mapping) for mapping in mappings)
                  if value is not None]
    if crs_values and any(value != crs_values[0] for value in crs_values[1:]):
        fail("Numeric raster item has conflicting CRS evidence")
    if len(transforms) > 1 and any(
            not same_grid(transforms[0], transform, check_crs=False)
            for transform in transforms[1:]):
        fail("Numeric raster item has conflicting affine evidence")
    return (crs_values[0] if crs_values else None,
            transforms[0] if transforms else None,
            crs_values, transforms)


def asset_projection(item, asset_name):
    assets = item.get("assets", {})
    if type(assets) is not dict:
        fail("Numeric raster item assets are malformed")
    if asset_name not in assets:
        return None, None
    asset = assets[asset_name]
    if type(asset) is not dict:
        fail("Numeric raster asset projection metadata is malformed")
    asset_properties = asset.get("properties", {})
    if type(asset_properties) is not dict:
        fail("Numeric raster asset projection properties are malformed")
    mappings = (asset, asset_properties)
    crs_values = [value for value in (_field_crs(mapping) for mapping in mappings)
                  if value is not None]
    transforms = [value for value in (_field_transform(mapping) for mapping in mappings)
                  if value is not None]
    if crs_values and any(value != crs_values[0] for value in crs_values[1:]):
        fail("Numeric raster asset has conflicting CRS evidence")
    if len(transforms) > 1 and any(
            not same_grid(transforms[0], transform, check_crs=False)
            for transform in transforms[1:]):
        fail("Numeric raster asset has conflicting affine evidence")
    return (crs_values[0] if crs_values else None,
            transforms[0] if transforms else None)
