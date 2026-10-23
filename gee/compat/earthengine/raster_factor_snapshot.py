"""Owned metadata snapshots for root-scope SDK factor ValueRef reuse."""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace
import math

from .array_core import charge_array
from .ir import Image, Pixel, Source
from .raster_array_bands import RasterArrayBands
from .raster_array_core import RasterArrayImage


FACTOR_METHODS = frozenset({
    "Image.matrixCholeskyDecomposition", "Image.matrixLUDecomposition",
    "Image.matrixQRDecomposition", "Image.matrixSingularValueDecomposition",
})


@dataclass(frozen=True)
class FactorSnapshot:
    value: RasterArrayImage | RasterArrayBands
    metadata_work: int


def _json_metadata_work(translator, root):
    """Accept plain owned JSON only; typed/joined metadata keeps old evaluation."""
    active = set()
    stack = [(root, False, 0)]
    work = 0
    while stack:
        value, leaving, depth = stack.pop()
        charge_array(translator, 1)
        work += 1
        if depth > 96:
            return None
        if type(value) in (type(None), bool, int):
            continue
        if type(value) is float:
            if not math.isfinite(value):
                return None
            continue
        if type(value) is str:
            charge_array(translator, len(value))
            work += len(value)
            continue
        if type(value) not in (dict, list, tuple):
            return None
        identity = id(value)
        if leaving:
            active.remove(identity)
            continue
        if identity in active:
            return None
        count = len(value) * (2 if type(value) is dict else 1)
        charge_array(translator, count)
        work += count
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                return None
            children = tuple(value.keys()) + tuple(value.values())
        else:
            children = value
        active.add(identity)
        stack.append((value, True, depth))
        stack.extend((child, False, depth + 1) for child in children)
    return work


def _immutable_pixels(translator, root):
    """Prove exact frozen IR types before sharing any scalar identities."""
    active, complete = set(), set()
    stack = [(root, False, 0)]
    while stack:
        value, leaving, depth = stack.pop()
        charge_array(translator, 1)
        if depth > 96:
            return False
        if type(value) in (type(None), bool, int, float, str, bytes):
            continue
        identity = id(value)
        if leaving:
            active.remove(identity)
            complete.add(identity)
            continue
        if identity in active:
            return False
        if identity in complete:
            continue
        if type(value) is Pixel and type(value.op) is str and type(value.boolean) is bool:
            children = value.args
        elif type(value) is Source:
            if (type(value.cid) is not str or type(value.ids) is not tuple
                    or type(value.names) is not tuple or type(value.alias) is not bool):
                return False
            children = (value.cid, value.ids, value.names)
        elif type(value) is tuple:
            children = value
        else:
            return False
        if type(children) is not tuple:
            return False
        charge_array(translator, len(children))
        active.add(identity)
        stack.append((value, True, depth))
        stack.extend((child, False, depth + 1) for child in children)
    return True


def _clone(translator, snapshot):
    value = snapshot.value
    arrays = value.arrays if type(value) is RasterArrayBands else (value,)
    charge_array(translator, 2 * snapshot.metadata_work + sum(len(a.cells) + len(a.shape) + 1 for a in arrays))
    image = replace(value.image, bands=[], props=copy.deepcopy(value.image.props),
                    footprint=copy.deepcopy(value.image.footprint))
    cloned = tuple(replace(array, image=image) for array in arrays)
    return RasterArrayBands(image, cloned) if type(value) is RasterArrayBands else cloned[0]


def snapshot_factor(translator, value):
    """Detach mutable metadata; never cache catalog facts or mapped evaluation."""
    if type(value) not in (RasterArrayImage, RasterArrayBands):
        return None
    image = value.image
    if type(image) is not Image or image.bands or image.mapped or image.copied_props:
        return None
    arrays = value.arrays if type(value) is RasterArrayBands else (value,)
    if (type(arrays) is not tuple or not 1 <= len(arrays) <= 3
            or any(type(array) is not RasterArrayImage or array.image is not image
                   or type(array.cells) is not tuple or type(array.shape) is not tuple for array in arrays)
            or sum(len(array.cells) for array in arrays) > 64):
        return None
    work = _json_metadata_work(translator, (image.props, image.footprint))
    if work is None or not _immutable_pixels(
            translator, (tuple((array.cells, array.mask) for array in arrays), image.source)):
        return None
    initial = FactorSnapshot(value, work)
    return FactorSnapshot(_clone(translator, initial), work)


def restore_factor(translator, value):
    return _clone(translator, value) if type(value) is FactorSnapshot else value
