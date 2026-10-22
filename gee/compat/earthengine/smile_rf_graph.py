"""Lower trusted Smile RF Pixel nodes to audited training/prediction nodes."""
from __future__ import annotations

from ...sampling_spec import decode_sampling_spec, sampling_columns
from ...smile_rf_spec import decode_rf_spec
from .array_core import charge_array
from .ir import (
    Image,
    Pixel,
    SampledFeatures,
    TrainedSmileRandomForest,
    fail,
)


RF_ROWS = "local_ee_train_smile_rf_rows"
RF_SAMPLES = "local_ee_train_smile_rf_samples"
RF_CLASSIFY = "local_ee_smile_rf"


def _target_work(graph, inputs, schema):
    from .sampled_training import image_work_estimate

    image = Image([(str(index), pixel) for index, pixel in enumerate(inputs)], {})
    return (image_work_estimate(image) + len(schema)
            + sum(map(len, schema)) + 8)


def _target_node_bound(graph, inputs):
    from .sampled_training import pixel_node_estimate

    # Include input expression DAGs, schema-order merges, the predictor, final
    # output band label, and export grid/region nodes before mutating the graph.
    return (pixel_node_estimate(inputs, graph.t.options)
            + 2 * len(inputs) + 2
            + int(graph.t.options.get("scale") is not None
                  or graph.t.options.get("crs") is not None)
            + int(graph.t.options.get("region") is not None))


def _training_model(graph, classifier, inputs):
    if classifier.rows is not None:
        work = (_target_work(graph, inputs, classifier.schema)
                + len(classifier.training_spec) + len(classifier.rows) + 8)
        charge_array(graph.t, work)
        graph.reserve_nodes(
            _target_node_bound(graph, inputs) + 1,
            "Smile RandomForest literal training graph",
        )
        decode_rf_spec(classifier.training_spec)
        return graph.node(
            RF_ROWS, rows=classifier.rows, spec=classifier.training_spec,
        )

    sampled = classifier.samples
    if not isinstance(sampled, SampledFeatures) or not isinstance(sampled.image, Image):
        fail("Smile RandomForest has no fixed sampleRegions image")
    from .decoder import Translator
    from .graph import Graph
    from .sampled_feature_ops import (
        emit_sampled_operations,
        validate_sampled_operations,
    )
    from .sampled_training import image_node_estimate, image_work_estimate

    operations = validate_sampled_operations(
        sampled, graph.t, "Smile RandomForest sample-table operation chain",
    )
    operation_work = sum(6 * len(operation) for operation in operations)
    target_image = Image(
        [(str(index), pixel) for index, pixel in enumerate(inputs)], {},
    )
    work = (
        2 * len(sampled.spec.encode("utf-8"))
        + 2 * len(classifier.training_spec.encode("utf-8"))
        + operation_work
        + len(classifier.schema) + sum(map(len, classifier.schema))
        + len(classifier.class_property)
        + image_work_estimate(sampled.image)
        + image_work_estimate(target_image)
        + 16
    )
    charge_array(graph.t, work)
    try:
        sample_spec = decode_sampling_spec(sampled.spec)
        decode_rf_spec(classifier.training_spec)
        columns = set(sampling_columns(sample_spec)) - {"system:index", ".geo"}
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Smile RandomForest has an invalid sample or model specification: {exc}")
    if not sample_spec["regions"]["features"]:
        fail("Smile RandomForest requires at least one training region")
    if not {classifier.class_property, *classifier.schema} <= columns:
        fail("Smile RandomForest training properties are missing from the sample table")

    # Recompile this fixed source through an independent translator. Only its
    # declared sampling grid may enter the child; target map/export options and
    # target source caches stay on the parent graph.
    grid = sample_spec["grid"]
    options = {key: grid[key] for key in ("scale", "crs") if grid[key] is not None}
    child_translator = Translator(
        list(graph.t.catalog.values()), graph.t.items, options,
    )
    child_graph = Graph(child_translator)
    node_bound = (
        image_node_estimate(sampled.image, options)
        + _target_node_bound(graph, inputs)
        + 2 + len(operations)
    )
    graph.reserve_nodes(node_bound, "Smile RandomForest sample and prediction graph")

    sample_image_ref, timed = child_graph.image(sampled.image)
    if timed:
        fail("Smile RandomForest sampleRegions image must be spatial")
    references = graph.import_auxiliary(child_graph)
    sample_image_ref = Graph._rewrite_imported_refs(sample_image_ref, references)
    table = graph.node(
        "local_ee_sample_regions", data=sample_image_ref, spec=sampled.spec,
    )
    table = emit_sampled_operations(graph, table, operations)
    return graph.node(RF_SAMPLES, data=table, spec=classifier.training_spec)


def compile_smile_rf_pixel(graph, pixel):
    """Compile schema-selected input bands and a trusted RF producer chain."""
    if not isinstance(pixel, Pixel) or pixel.op != "smile_rf_classify" or len(pixel.args) != 2:
        fail("Internal Smile RandomForest Pixel is malformed")
    inputs, classifier = pixel.args
    if (type(inputs) is not tuple or not 1 <= len(inputs) <= 8
            or not isinstance(classifier, TrainedSmileRandomForest)
            or len(inputs) != len(classifier.schema)):
        fail("Smile RandomForest inputs must match its 1..8 band schema")

    if ((classifier.rows is None) == (classifier.samples is None)
            or type(classifier.training_spec) is not str):
        fail("Smile RandomForest training IR is malformed")
    model = _training_model(graph, classifier, inputs)
    data = None
    timed = None
    for band_name, input_pixel in zip(classifier.schema, inputs):
        if not isinstance(input_pixel, Pixel):
            fail("Smile RandomForest inputs must be scalar raster pixels")
        reference, label, has_time = graph.expression(input_pixel)
        if label is None or reference is None:
            fail("Image.classify requires bound raster input bands")
        if timed is not None and timed != has_time:
            fail("Image.classify schema bands have incompatible time dimensions")
        timed = has_time
        reference = graph.rename_band(reference, band_name)
        data = reference if data is None else graph.node(
            "merge_cubes", cube1=data, cube2=reference,
        )

    result = graph.node(RF_CLASSIFY, data=data, model=model)
    return result, "v", bool(timed)
