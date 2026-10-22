"""Intermediate representation and image-value helpers for Earth Engine."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any


class UnsupportedEEError(ValueError):
    """The serialized program uses a semantic this local adapter cannot honor."""


@dataclass(frozen=True)
class Source:
    cid: str
    ids: tuple[str, ...]
    names: tuple[str, ...]
    alias: bool = False


@dataclass(frozen=True)
class Pixel:
    op: str
    args: tuple
    boolean: bool = False


@dataclass
class Image:
    bands: list[tuple[str, Pixel]]
    props: dict
    source: Source | None = None
    mapped: bool = False
    inherit_props: bool = True
    copied_props: tuple = ()
    footprint: dict | None = None
    footprint_is_absolute: bool = False


@dataclass
class Collection:
    source: Source
    image: Image


@dataclass
class ImageSequence:
    """Finite explicitly ordered Images, including per-period composites."""
    images: list[Image]


@dataclass
class Function:
    names: list
    body: Any
    env: dict


@dataclass
class ParsedExpression:
    text: str
    default: str
    variables: list


@dataclass
class Filter:
    name: str
    args: dict


@dataclass
class Reducer:
    name: str
    unweighted: bool = False


@dataclass
class Region:
    image: Image
    geometry: dict
    reducer: Reducer
    options: dict


def fail(message: str) -> None:
    raise UnsupportedEEError(message)


def const(value: Any) -> Pixel:
    if isinstance(value, bool):
        return Pixel("constant", (value,), True)
    if value is None or isinstance(value, (int, float)) and math.isfinite(value):
        return Pixel("constant", (value,))
    fail("Image.constant only supports finite numeric values")


def integer(value: Any, label: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value:
        fail(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        fail(f"{label} must be >= {minimum}")
    return int(value)


def static_truth(value: Any) -> bool:
    from .array_values import StaticArray
    from .join_ops import Join
    from .table_reducers import TableReducer
    from .inner_join import InnerJoin
    from .raster_array_core import RasterArrayImage
    from .confusion_values import StaticConfusionMatrix

    # EE If treats empty arrays/dictionaries/strings, zero, NaN and null as
    # false. Do not accidentally use truthiness of internal IR dataclasses.
    if isinstance(value, (Image, Collection, ImageSequence, Pixel, Region, Function, Filter, Reducer, StaticArray, Join, InnerJoin, TableReducer, RasterArrayImage, StaticConfusionMatrix)):
        fail("Algorithms.If currently requires a static scalar/list/dictionary condition")
    if isinstance(value, (int, float)) and not math.isfinite(value):
        return False
    return bool(value)


def _substitute(value: Any, old: Source, new: Source, memo: dict | None = None):
    memo = {} if memo is None else memo
    if isinstance(value, Source):
        return new if value == old else value
    if isinstance(value, Pixel):
        key = id(value)
        if key not in memo:
            memo[key] = replace(value, args=tuple(_substitute(a, old, new, memo) for a in value.args))
        return memo[key]
    if isinstance(value, tuple):
        return tuple(_substitute(a, old, new, memo) for a in value)
    return value


def rebind(collection: Collection, ids) -> Collection:
    source = replace(collection.source, ids=tuple(ids))
    memo = {}
    image = replace(
        collection.image,
        source=source,
        bands=[(name, _substitute(pixel, collection.source, source, memo))
               for name, pixel in collection.image.bands],
    )
    return Collection(source, image)


def as_image(value: Any) -> Image:
    if isinstance(value, Image):
        return value
    if isinstance(value, (int, float, bool)):
        return Image([("constant", const(value))], {})
    if isinstance(value, list) and all(isinstance(item, (int, float, bool)) for item in value):
        return Image([
            ("constant" + ("_" + str(index) if index else ""), const(item))
            for index, item in enumerate(value)
        ], {})
    fail("Expected an Image or finite number")


def pairs(a: Any, b: Any):
    a, b = as_image(a), as_image(b)
    if len(a.bands) == 1 and len(b.bands) > 1:
        return a, b, [(name, a.bands[0][1], pixel) for name, pixel in b.bands]
    if len(b.bands) == 1:
        return a, b, [(name, pixel, b.bands[0][1]) for name, pixel in a.bands]
    if len(a.bands) != len(b.bands):
        fail("Image operands need equal band counts or a single broadcast band")
    return a, b, [(name, pixel, other) for (name, pixel), (_, other) in zip(a.bands, b.bands)]


def binary(a: Any, b: Any, op: str) -> Image:
    a, b, matched = pairs(a, b)
    boolean = op in {"eq", "neq", "gt", "gte", "lt", "lte", "and", "or"}
    return Image(
        [(name, Pixel(op, (left, right), boolean)) for name, left, right in matched],
        dict(a.props),
        a.source or b.source,
        a.mapped or b.mapped,
        a.inherit_props,
        a.copied_props,
        a.footprint,
        a.footprint_is_absolute,
    )


def unary(image: Any, op: str) -> Image:
    image = as_image(image)
    return replace(
        image,
        bands=[(name, Pixel(op, (pixel,), op in {"not", "is_nodata"}))
               for name, pixel in image.bands],
    )
