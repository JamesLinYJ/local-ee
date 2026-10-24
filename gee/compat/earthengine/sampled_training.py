"""Runtime sample-table training node construction for minimum distance."""
from __future__ import annotations

from .ir import DynamicMinimumDistance, Image, Pixel, SampledFeatures, fail


MAX_TRANSLATOR_WORK = 50_000
MAX_GRAPH_NODES = 500


def _pixel_cost(pixel, seen, sources):
    if not isinstance(pixel, Pixel) or id(pixel) in seen:
        return 0
    seen.add(id(pixel))
    if pixel.op == "band":
        sources.add(pixel.args[0])
        return 1
    children = []

    def collect(value):
        if isinstance(value, Pixel):
            children.append(value)
        elif isinstance(value, tuple):
            for item in value:
                collect(item)

    for argument in pixel.args:
        collect(argument)
    child_cost = sum(_pixel_cost(child, seen, sources) for child in children)
    if pixel.op == "constant":
        return child_cost
    if pixel.op == "reduce_t":
        return child_cost + 1
    if pixel.op == "mask_guard":
        # Validation is a typed identity using apply(value,1), including its
        # implicit Double boundary, constant grid binding, labels and merge.
        return child_cost + 8
    if pixel.op == "mask_set_value":
        # Strict apply includes labels/merge/casts; zero and unmask add2nodes.
        return child_cost + 10
    if pixel.op in {"mask_validity", "mask_result_value"}:
        return child_cost + 4
    if pixel.op in {"mask_apply", "mask_update"}:
        # A fractional projection labels both operands, merges them, then
        # emits its closed native process. Reserve a possible Float64 input
        # conversion too, even when a scalar happens not to materialize it.
        return child_cost + 5 + max(0, len(children) - 2)
    if pixel.op in {"clip", "to_double", "to_float", "unmask", "unmask_constant", "on_grid"}:
        return child_cost + 2
    if pixel.op == "reduce_bands":
        return child_cost + len(children) + 1
    # A raster callback may need one merge per extra raster operand and one
    # reduce_dimension node. This bound includes both before graph mutation.
    return child_cost + 2 + max(0, len(children) - 1)


def pixel_node_estimate(pixels, options=None):
    seen, sources = set(), set()
    expression_cost = sum(_pixel_cost(pixel, seen, sources) for pixel in pixels)
    # Per output band, reserve its label/add_dimension and merge_cubes slot.
    output_cost = 2 * len(pixels) + max(0, len(pixels) - 1)
    option_cost = 0
    options = options or {}
    if options.get("scale") is not None or options.get("crs") is not None:
        option_cost += 1
    if options.get("region") is not None:
        option_cost += 1
    return expression_cost + len(sources) + output_cost + option_cost + 1


def image_node_estimate(image, options=None):
    return pixel_node_estimate([pixel for _, pixel in image.bands], options)


def image_work_estimate(image):
    seen, sources = set(), set()
    work = 3 * len(image.bands) + sum(len(name) for name, _ in image.bands)

    def include_sample_image(sampled):
        nonlocal work
        if not isinstance(sampled, SampledFeatures) or not isinstance(sampled.image, Image):
            return
        work += len(sampled.spec) + sum(map(len, sampled.operations))
        work += 3 * len(sampled.image.bands)
        work += sum(len(name) for name, _ in sampled.image.bands)
        for _, child_pixel in sampled.image.bands:
            scan(child_pixel)

    def scan(value):
        nonlocal work
        if isinstance(value, Pixel):
            if id(value) in seen:
                return
            seen.add(id(value))
            work += 1 + len(value.op)
            if value.op in {"mask_apply", "mask_update"}:
                # Projection lowering may insert one Float64 cast that is not
                # represented as a separate IR node.
                work += 1
            if value.op == "band":
                source, band = value.args
                if source not in sources:
                    sources.add(source)
                    work += 1 + len(source.cid) + sum(map(len, source.ids))
                work += len(band)
            if value.op == "trained_classify" and len(value.args) == 2:
                model = value.args[1]
                if isinstance(model, DynamicMinimumDistance):
                    work += len(model.class_property)
                    work += sum(map(len, model.schema))
                    include_sample_image(model.samples)
            if value.op == "smile_rf_classify" and len(value.args) == 2:
                from .ir import TrainedSmileRandomForest

                model = value.args[1]
                if isinstance(model, TrainedSmileRandomForest):
                    work += len(model.training_spec) + len(model.rows or "")
                    work += len(model.class_property) + sum(map(len, model.schema))
                    include_sample_image(model.samples)
            if value.op == "remap" and len(value.args) == 2 and type(value.args[1]) is str:
                # The parent graph precharges specifications in both the target
                # and independently compiled sample-image lineages.
                work += 6 * len(value.args[1]) + 1
            for argument in value.args:
                scan(argument)
        elif isinstance(value, (tuple, list)):
            for item in value:
                scan(item)

    for _, pixel in image.bands:
        scan(pixel)
    return work


def _training_spec(classifier):
    from ...sampling_spec import decode_training_spec, encode_spec

    text = encode_spec({
        "version": 1,
        "metric": classifier.metric,
        "class_property": classifier.class_property,
        "schema": list(classifier.schema),
    })
    decode_training_spec(text)
    return text


def compile_training_model(graph, classifier, target_inputs):
    """Emit child sample graph, auxiliary provenance, and runtime trainer node."""
    from .decoder import Translator
    from .graph import Graph
    from .sampled_feature_ops import (
        emit_sampled_operations,
        validated_sampled_schema,
    )
    from .sample_mask_projection import project_sample_mask_image

    if not isinstance(classifier, DynamicMinimumDistance):
        fail("Internal dynamic classifier IR is malformed")
    sampled = classifier.samples
    if not isinstance(sampled, SampledFeatures) or not isinstance(sampled.image, Image):
        fail("Sample-trained classifier has no server-side sample image")
    sample_spec, columns, operations = validated_sampled_schema(
        sampled, graph.t, "Classifier.train sample-table operation chain",
    )
    projected_image = project_sample_mask_image(sampled.image, graph.t)

    # The shared spec decoder and encoder walk bounded JSON, so reserve their
    # cost before parsing or serializing either wire value. Six bytes per
    # code point covers both UTF-8 expansion and JSON escaping of controls.
    schema_chars = sum(map(len, classifier.schema))
    training_wire_bound = 6 * (
        len(classifier.metric) + len(classifier.class_property) + schema_chars
    ) + 256
    work = (
        2 * len(sampled.spec.encode("utf-8")) + 2 * training_wire_bound
        + len(classifier.schema) + schema_chars + len(classifier.class_property)
        + image_work_estimate(projected_image)
        + image_work_estimate(Image([
            (str(index), pixel) for index, pixel in enumerate(target_inputs)
        ], {}))
        + 8
    )
    if graph.t.steps + work > MAX_TRANSLATOR_WORK:
        fail("Image.classify dynamic model compilation exceeds the 50000-step work budget")
    graph.t.steps += work

    if not sample_spec["regions"]["features"]:
        fail("Classifier.train requires at least one sampling region")
    if classifier.class_property not in columns:
        fail(f"Sample-trained classifier is missing classProperty {classifier.class_property!r}")
    for name in classifier.schema:
        if name not in columns:
            fail(f"Sample-trained classifier is missing input property {name!r}")

    grid = sample_spec["grid"]
    options = {key: grid[key] for key in ("scale", "crs") if grid[key] is not None}
    child_translator = Translator(
        list(graph.t.catalog.values()), graph.t.items, options,
    )
    child_graph = Graph(child_translator, work_owner=graph.work_owner)
    training_spec = _training_spec(classifier)

    # Reserve a conservative graph upper bound for both the fixed training
    # branch and target branch before compiling either.
    node_bound = (
        image_node_estimate(projected_image, options)
        + pixel_node_estimate(target_inputs, graph.t.options)
        + 4 + len(operations)
    )
    graph.reserve_nodes(node_bound, "Image.classify dynamic training graph")

    sample_image_ref, timed = child_graph.image(projected_image)
    if timed:
        fail("Classifier.train sample image must be spatial and have no time dimension")
    references = graph.import_auxiliary(child_graph)
    sample_image_ref = Graph._rewrite_imported_refs(sample_image_ref, references)
    sampler = graph.node(
        "local_ee_sample_regions", data=sample_image_ref, spec=sampled.spec,
    )
    sampler = emit_sampled_operations(graph, sampler, operations)
    return graph.node(
        "local_ee_train_minimum_distance", data=sampler,
        spec=training_spec,
    )
