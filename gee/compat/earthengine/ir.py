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


@dataclass(frozen=True)
class ClipFootprintIdentity:
    """Identity of an unresolved geodesic clip footprint.

    ``spec`` is the exact immutable canonical ROI wire when known. ``None``
    retains the fact that the public footprint is pending but that no single
    ROI can safely justify implicit sampling.
    """

    spec: str | None
    fingerprint: bytes | None = None


def valid_clip_footprint_identity(value):
    """Check the fixed-size immutable identity payload without string scans."""
    if type(value) is not ClipFootprintIdentity:
        return False
    if value.spec is None:
        return value.fingerprint is None
    return (
        type(value.spec) is str and bool(value.spec)
        and type(value.fingerprint) is bytes and len(value.fingerprint) == 32
    )


def _known_clip_footprint(value):
    return valid_clip_footprint_identity(value) and value.spec is not None


def clip_footprint_after_first_input(first, *others):
    """Keep first-image ownership unless another pending ROI makes it unclear."""
    pending = (first, *others)
    if not any(value is not None for value in pending):
        return None
    if not _known_clip_footprint(first):
        return ClipFootprintIdentity(None)
    for value in others:
        if value is None:
            continue
        if (not _known_clip_footprint(value)
                or value.fingerprint != first.fingerprint):
            return ClipFootprintIdentity(None)
    return first


def combine_clip_footprints(*values):
    """Retain a single identity only when every combined input agrees."""
    if not values or all(value is None for value in values):
        return None
    first = values[0]
    if not _known_clip_footprint(first):
        return ClipFootprintIdentity(None)
    if any(
        not _known_clip_footprint(value)
        or value.fingerprint != first.fingerprint for value in values[1:]
    ):
        return ClipFootprintIdentity(None)
    return first


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
    # Exact immutable ROI identity while `footprint` remains conservative
    # source support. An identity with spec=None means pending but ambiguous.
    clip_footprint: ClipFootprintIdentity | None = None


@dataclass(frozen=True)
class SampledFeatures:
    """Server-side sampled rows; values are produced only by the backend."""

    image: Image
    spec: str
    operations: tuple[str, ...] = ()


@dataclass(frozen=True)
class DynamicMinimumDistance:
    """A minimum-distance model trained from a runtime sample-table node."""

    samples: SampledFeatures
    metric: str
    schema: tuple[str, ...]
    class_property: str
    output_mode: str = "CLASSIFICATION"


@dataclass(frozen=True)
class SmileRandomForest:
    """Validated constructor parameters for the distinct Smile RF algorithm."""

    number_of_trees: int
    variables_per_split: int | None
    min_leaf_population: int
    bag_fraction: float
    max_nodes: int | None
    seed: int
    output_mode: str = "CLASSIFICATION"


@dataclass(frozen=True)
class TrainedSmileRandomForest:
    """Runtime-training IR backed by literal rows or a lazy sampled table."""

    classifier: SmileRandomForest
    schema: tuple[str, ...]
    class_property: str
    training_spec: str
    rows: str | None = None
    samples: SampledFeatures | None = None


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


@dataclass(frozen=True)
class ParsedExpression:
    text: str
    default: str
    variables: tuple[str, ...]


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


def static_truth(value: Any, translator=None) -> bool:
    from .kernel_values import KernelSpec
    from .neighborhood_reducer_plan import NeighborhoodUnweighted
    from .date_ranges import is_date_range
    from .nested_collections import NestedFeatureCollection
    from .composed_reducers import is_reducer_spec
    from .array_values import StaticArray
    from .join_ops import Join
    from .table_reducers import TableReducer
    from .inner_join import InnerJoin
    from .raster_array_core import RasterArrayImage
    from .confusion_values import StaticConfusionMatrix
    from .minimum_distance import StaticMinimumDistance
    from .raster_array_bands import RasterArrayBands
    from .runtime_feature_ir import (
        RFClassifiedFeatureTable,
        RuntimeConfusionValue,
        RuntimeFeatureErrorMatrix,
        RuntimeRFTrainingConfusion,
    )
    from .rf_explanation import (
        RuntimeRFExplanation,
        contains_runtime_explanation,
    )

    # EE If treats empty arrays/dictionaries/strings, zero, NaN and null as
    # false. Do not accidentally use truthiness of internal IR dataclasses.
    if is_date_range(value) or isinstance(value, (NestedFeatureCollection, KernelSpec, NeighborhoodUnweighted)) or is_reducer_spec(value):
        fail("Algorithms.If currently requires a static scalar/list/dictionary condition")
    may_contain_runtime_explanation = (
        translator is None
        or getattr(translator, "_runtime_rf_explanation_seen", False)
    )
    if (may_contain_runtime_explanation
            and contains_runtime_explanation(value, translator)):
        fail("Algorithms.If currently requires a static scalar/list/dictionary condition")
    if isinstance(value, (Image, Collection, ImageSequence, Pixel, Region, Function, Filter, Reducer, StaticArray, Join, InnerJoin, TableReducer, RasterArrayImage, StaticConfusionMatrix, StaticMinimumDistance, RasterArrayBands, SampledFeatures, DynamicMinimumDistance, SmileRandomForest, TrainedSmileRandomForest, RFClassifiedFeatureTable, RuntimeRFTrainingConfusion, RuntimeFeatureErrorMatrix, RuntimeConfusionValue, RuntimeRFExplanation)):
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
    if bool(a.bands) != bool(b.bands):
        # One-band broadcasting has no proven zero-band counterpart. Reject
        # this local gap symmetrically instead of silently erasing one input.
        fail("Zero-band Image arithmetic with a nonempty Image is unsupported")
    if len(a.bands) == 1 and len(b.bands) > 1:
        return a, b, [(name, a.bands[0][1], pixel) for name, pixel in b.bands]
    if len(b.bands) == 1:
        return a, b, [(name, pixel, b.bands[0][1]) for name, pixel in a.bands]
    if len(a.bands) != len(b.bands):
        fail("Image operands need equal band counts or a single broadcast band")
    return a, b, [(name, pixel, other) for (name, pixel), (_, other) in zip(a.bands, b.bands)]


def binary(a: Any, b: Any, op: str, translator=None) -> Image:
    a, b, matched = pairs(a, b)
    boolean = op in {"eq", "neq", "gt", "gte", "lt", "lte", "and", "or"}
    from .image_mask_math import binary_pixel

    return Image(
        [(name, binary_pixel(translator, op, left, right, boolean=boolean))
         for name, left, right in matched],
        dict(a.props),
        a.source or b.source,
        a.mapped or b.mapped,
        a.inherit_props,
        a.copied_props,
        a.footprint,
        a.footprint_is_absolute,
        clip_footprint_after_first_input(a.clip_footprint, b.clip_footprint),
    )


def unary(image: Any, op: str, translator=None) -> Image:
    image = as_image(image)
    from .image_mask_math import unary_pixel

    return replace(
        image,
        bands=[(name, unary_pixel(translator, op, pixel, boolean=op in {"not", "is_nodata"}))
               for name, pixel in image.bands],
    )
