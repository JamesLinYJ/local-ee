"""Image.sampleRegions IR construction and bounded sample-table lowering."""
from __future__ import annotations

import math

from .ir import Image, Pixel, SampledFeatures, fail


MAX_TRANSLATOR_WORK = 50_000
SAMPLING_BOUNDARY_WARNING = (
    "Image.sampleRegions uses a local finite-grid cell selection policy; global "
    "and spherical boundary behavior has not been verified against Earth Engine."
)
_ARGUMENTS = {
    "image", "collection", "properties", "scale", "projection", "tileScale",
    "geometries",
}


def _charge(translator, work):
    if work < 0 or translator.steps + work > MAX_TRANSLATOR_WORK:
        fail("Image.sampleRegions exceeds the 50000-step compilation work budget")
    translator.steps += work


def _coordinate_count(value):
    if type(value) is list:
        if len(value) == 2 and all(type(item) in (int, float) for item in value):
            return 1
        return sum(_coordinate_count(item) for item in value)
    return 0


def invoke_sample_regions(translator, arguments):
    """Build a lazy server-side sample table; pixel values stay in the backend."""
    from ...sampling_spec import prepare_sampling_spec

    translator.allowed(arguments, _ARGUMENTS)
    for required in ("image", "collection"):
        if required not in arguments:
            fail(f"Image.sampleRegions requires {required}")

    image = arguments["image"]
    collection = arguments["collection"]
    if not isinstance(image, Image):
        fail("Image.sampleRegions image must be an Earth Engine Image")
    if type(collection) is not dict or collection.get("type") != "FeatureCollection":
        fail("Image.sampleRegions collection must be a literal FeatureCollection")
    if type(image.bands) is not list or not 1 <= len(image.bands) <= 64:
        fail("Image.sampleRegions requires 1..64 named input bands")
    band_names = []
    for item in image.bands:
        if (type(item) is not tuple or len(item) != 2 or type(item[0]) is not str):
            fail("Image.sampleRegions requires named scalar pixel bands")
        if not isinstance(item[1], Pixel):
            fail("Image.sampleRegions requires named scalar pixel bands")
        band_names.append(item[0])
    if len(set(band_names)) != len(band_names):
        fail("Image.sampleRegions input band names must be unique")

    properties = arguments.get("properties")
    geometries = arguments.get("geometries", False)
    if type(geometries) is not bool:
        fail("Image.sampleRegions geometries must be a boolean")
    tile_scale = arguments.get("tileScale", 1.0)
    try:
        valid_tile_scale = (not isinstance(tile_scale, bool)
                            and type(tile_scale) in (int, float)
                            and math.isfinite(tile_scale) and tile_scale == 1)
    except OverflowError:
        valid_tile_scale = False
    if not valid_tile_scale:
        fail("Image.sampleRegions only supports tileScale=1")

    grid = {"scale": arguments.get("scale"), "crs": arguments.get("projection")}
    features = collection.get("features")
    if type(features) is not list:
        fail("Image.sampleRegions collection must contain a feature list")
    # Charge the bounded geometry/property scan and the eventual canonical
    # specification handoff before the shared helper copies any feature data.
    feature_work = 1 + len(band_names) + sum(map(len, band_names))
    for feature in features:
        if type(feature) is not dict:
            fail("Image.sampleRegions collection contains a malformed Feature")
        props = feature.get("properties")
        geometry = feature.get("geometry")
        if type(props) is dict:
            feature_work += 1 + len(props) + sum(map(len, props))
        if type(geometry) is dict:
            feature_work += _coordinate_count(geometry.get("coordinates")) + 1
    _charge(translator, feature_work)
    try:
        spec = prepare_sampling_spec(
            collection, band_names, properties=properties,
            geometries=geometries, grid=grid,
        )
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(str(exc))
    _charge(translator, len(spec) + len(band_names) + 1)
    translator.warn(SAMPLING_BOUNDARY_WARNING)
    return SampledFeatures(image=image, spec=spec)


def compile_sample_table(sampled, translator):
    """Compile a standalone sample table to a bounded lazy process graph."""
    from .decoder import Translator
    from .graph import Graph
    from .sampled_training import image_node_estimate, image_work_estimate
    from .sampled_feature_ops import (
        emit_sampled_operations,
        validated_sampled_schema,
    )

    if not isinstance(sampled, SampledFeatures):
        fail("Internal sample-table IR is malformed")
    spec, columns, operations = validated_sampled_schema(
        sampled, translator, "Image.sampleRegions operation chain",
    )
    grid = spec["grid"]
    options = {key: grid[key] for key in ("scale", "crs") if grid[key] is not None}
    child = Translator(list(translator.catalog.values()), translator.items, options)
    graph = Graph(child)

    # Bound the preflight estimate before compiling any source or pixel node.
    # Each band may need a filter, a temporal drop, a final band label and one
    # merge; nested expressions are still checked by the 500-node graph limit.
    estimated_nodes = image_node_estimate(sampled.image, options) + 1 + len(operations)
    graph.reserve_nodes(estimated_nodes, "Image.sampleRegions")
    _charge(translator, len(columns) + image_work_estimate(sampled.image) + 1)
    ref, timed = graph.image(sampled.image)
    if timed:
        fail("Image.sampleRegions requires a spatial Image without a time dimension")
    result = graph.node("local_ee_sample_regions", data=ref, spec=sampled.spec)
    result = emit_sampled_operations(graph, result, operations)
    process_graph = graph.finish(result)
    warnings = list(translator.warnings)
    return {
        "kind": "sample_table",
        "process_graph": process_graph,
        "bands": columns,
        "sample_spec": sampled.spec,
        "sample_operations": list(operations),
        "grid_options": grid,
        "source_item_ids": list(dict.fromkeys(
            item_id for source in graph.sources for item_id in source.ids
        )),
        "warnings": warnings,
    }
