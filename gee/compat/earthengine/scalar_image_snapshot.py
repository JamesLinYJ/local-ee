"""Owned root-scope snapshots for shared official RGB/HSV ValueRefs."""
from __future__ import annotations

import copy
from dataclasses import dataclass

from .array_core import charge_array
from .ir import (
    ClipFootprintIdentity, Image, Pixel, Source, valid_clip_footprint_identity,
)
from .raster_factor_snapshot import _immutable_pixels, _json_metadata_work


SCALAR_IMAGE_SNAPSHOT_METHODS = frozenset({"Image.rgbToHsv", "Image.hsvToRgb"})
MAX_SCALAR_IMAGE_SNAPSHOTS = 64


@dataclass(frozen=True)
class ScalarImageSnapshot:
    bands: tuple
    props: dict
    source: Source | None
    inherit_props: bool
    copied_props: tuple
    footprint: dict | None
    footprint_is_absolute: bool
    clip_footprint: ClipFootprintIdentity | None
    clone_work: int


def snapshot_scalar_image(translator, value):
    """Share proven frozen scalar IR while detaching all mutable metadata."""
    if (type(value) is not Image or value.mapped is not False
            or type(value.bands) is not list or len(value.bands) != 3
            or type(value.props) is not dict
            or type(value.inherit_props) is not bool
            or type(value.footprint_is_absolute) is not bool
            or value.clip_footprint is not None
            and not valid_clip_footprint_identity(value.clip_footprint)
            or type(value.copied_props) is not tuple
            or value.source is not None and type(value.source) is not Source):
        return None
    charge_array(translator, 2 * len(value.bands) + len(value.copied_props) + 2)
    names = set()
    band_chars = 0
    for band in value.bands:
        if (type(band) is not tuple or len(band) != 2
                or type(band[0]) is not str or not band[0]
                or type(band[1]) is not Pixel):
            return None
        charge_array(translator, len(band[0]) + 1)
        if band[0] in names:
            return None
        names.add(band[0])
        band_chars += len(band[0])
    copied_chars = 0
    for key in value.copied_props:
        if type(key) is not str or not key:
            return None
        charge_array(translator, len(key) + 1)
        copied_chars += len(key)

    metadata_work = _json_metadata_work(translator, (value.props, value.footprint))
    if metadata_work is None:
        return None
    charge_array(translator, 1 + len(value.bands))
    bands = tuple(value.bands)
    if not _immutable_pixels(translator, (bands, value.source)):
        return None
    clone_work = (
        2 * metadata_work + 3 * len(bands) + band_chars
        + len(value.copied_props) + copied_chars + 9
    )
    # Precharge the complete detached copy before the snapshot owns a mutable
    # metadata container. Every restore pays the same copy work separately.
    charge_array(translator, clone_work)
    return ScalarImageSnapshot(
        bands, copy.deepcopy(value.props), value.source,
        value.inherit_props, value.copied_props, copy.deepcopy(value.footprint),
        value.footprint_is_absolute, value.clip_footprint, clone_work,
    )


def restore_scalar_image(translator, value):
    """Return a fresh Image wrapper and metadata; frozen Pixel identities stay."""
    if type(value) is not ScalarImageSnapshot:
        return value
    charge_array(translator, value.clone_work)
    return Image(
        bands=list(value.bands), props=copy.deepcopy(value.props),
        source=value.source, mapped=False, inherit_props=value.inherit_props,
        copied_props=value.copied_props, footprint=copy.deepcopy(value.footprint),
        footprint_is_absolute=value.footprint_is_absolute,
        clip_footprint=value.clip_footprint,
    )
