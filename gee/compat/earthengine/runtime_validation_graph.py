"""Lower runtime RF feature tables and confusion values to local processes."""
from __future__ import annotations

from ...rf_validation_spec import (
    decode_classify_spec,
    decode_feature_rows,
    decode_matrix_spec,
    decode_metric_spec,
)
from .array_core import charge_array
from .decoder import Translator
from .graph import Graph
from .ir import SampledFeatures, fail
from .runtime_feature_ir import (
    RFClassifiedFeatureTable,
    RuntimeConfusionValue,
    RuntimeFeatureErrorMatrix,
    RuntimeRFTrainingConfusion,
)
from .sampled_feature_ops import emit_sampled_operations, validate_sampled_operations
from ...sampling_spec import decode_sampling_spec, sampling_columns
from .smile_rf_graph import RF_SAMPLES, compile_smile_rf_model


_SAMPLE_REGIONS = "local_ee_sample_regions"
_CLASSIFY_ROWS = "local_ee_smile_rf_classify_rows"
_CLASSIFY_SAMPLES = "local_ee_smile_rf_classify_samples"
_RF_CONFUSION = "local_ee_smile_rf_confusion"
_ERROR_MATRIX = "local_ee_error_matrix"
_CONFUSION_VALUE = "local_ee_confusion_value"


def _sampled_table_ref(graph, sampled, label):
    """Compile a fixed-grid sample table into the current graph."""
    from .sampled_training import image_node_estimate, image_work_estimate

    operations = validate_sampled_operations(sampled, graph.t, label)
    charge_array(graph.t, 2 * len(sampled.spec) + 2 * sum(map(len, operations)) + 8)
    try:
        spec = decode_sampling_spec(sampled.spec)
        columns = sampling_columns(spec)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"{label} has an invalid sample-table specification: {exc}")

    grid = spec["grid"]
    options = {key: grid[key] for key in ("scale", "crs") if grid[key] is not None}
    child = Translator(list(graph.t.catalog.values()), graph.t.items, options)
    child_graph = Graph(child)
    estimated_nodes = image_node_estimate(sampled.image, options) + 1 + len(operations)
    graph.reserve_nodes(estimated_nodes, label)
    charge_array(
        graph.t,
        len(columns) + image_work_estimate(sampled.image) + len(sampled.spec) + 1,
    )
    image_ref, timed = child_graph.image(sampled.image)
    if timed:
        fail(f"{label} requires a spatial Image without a time dimension")
    references = graph.import_auxiliary(child_graph)
    image_ref = Graph._rewrite_imported_refs(image_ref, references)
    table_ref = graph.node(_SAMPLE_REGIONS, data=image_ref, spec=sampled.spec)
    return emit_sampled_operations(graph, table_ref, operations)


def _classified_table_ref(graph, table):
    try:
        classify_spec = decode_classify_spec(table.spec)
        if classify_spec["columns"] != list(table.columns):
            fail("Smile RF feature table schema differs from its specification")
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Smile RF feature table specification is invalid: {exc}")
    model_ref = compile_smile_rf_model(graph, table.classifier)
    if isinstance(table.source, SampledFeatures):
        if table.source is table.classifier.samples:
            # Resubstitution predictions over the exact table used to train
            # this model consume the trainer's existing sample-table node.
            # Re-sampling the same source would duplicate the fixed-grid
            # graph and its work charges without changing its rows.
            trainer_id = model_ref.get("from_node")
            trainer = graph.graph.get(trainer_id)
            data_ref = (trainer.get("arguments", {}).get("data")
                        if trainer and trainer.get("process_id") == RF_SAMPLES
                        else None)
            if type(data_ref) is not dict or set(data_ref) != {"from_node"}:
                fail("Smile RF training table is missing its reusable sample-table node")
        else:
            data_ref = _sampled_table_ref(
                graph, table.source, "Smile RF feature prediction sample table",
            )
        if table.rows is not None:
            fail("Smile RF sampled prediction cannot contain inline row data")
        charge_array(graph.t, len(table.spec) + len(table.columns))
        return graph.node(
            _CLASSIFY_SAMPLES, data=data_ref, spec=table.spec, model=model_ref,
        )
    if type(table.rows) is not str:
        fail("Smile RF feature prediction rows are missing their canonical payload")
    try:
        decode_feature_rows(table.rows)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Smile RF feature prediction rows are invalid: {exc}")
    charge_array(graph.t, len(table.spec) + len(table.columns))
    return graph.node(
        _CLASSIFY_ROWS, rows=table.rows, spec=table.spec, model=model_ref,
    )


def _matrix_ref(graph, matrix):
    if isinstance(matrix, RuntimeRFTrainingConfusion):
        model_ref = compile_smile_rf_model(graph, matrix.classifier)
        return graph.node(_RF_CONFUSION, model=model_ref)
    if isinstance(matrix, RuntimeFeatureErrorMatrix):
        try:
            decode_matrix_spec(matrix.spec)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"Runtime errorMatrix specification is invalid: {exc}")
        table = matrix.table
        if isinstance(table, RFClassifiedFeatureTable):
            data_ref = _classified_table_ref(graph, table)
        elif isinstance(table, SampledFeatures):
            data_ref = _sampled_table_ref(
                graph, table, "FeatureCollection.errorMatrix sample table",
            )
        else:
            fail("Runtime errorMatrix has an unsupported feature table")
        charge_array(graph.t, len(matrix.spec) + 1)
        return graph.node(_ERROR_MATRIX, data=data_ref, spec=matrix.spec)
    fail("ConfusionMatrix accessor requires a supported runtime matrix")


def _source_ids(graph):
    return list(dict.fromkeys(
        [item_id for source in graph.sources for item_id in source.ids]
        + graph.auxiliary_source_item_ids
    ))


def _base_result(graph, reference, bands):
    return {
        "process_graph": graph.finish(reference),
        "bands": bands,
        "warnings": list(graph.t.warnings),
        "source_item_ids": _source_ids(graph),
    }


def compile_runtime_table(table, translator):
    """Produce the lazy result envelope for FeatureCollection.classify."""
    if not isinstance(table, RFClassifiedFeatureTable):
        fail("Internal runtime feature table is malformed")
    graph = Graph(translator)
    reference = _classified_table_ref(graph, table)
    return {"kind": "runtime_table", **_base_result(graph, reference, list(table.columns))}


def compile_runtime_value(value, translator):
    """Produce one owned JSON value from an explicit confusion accessor."""
    if not isinstance(value, RuntimeConfusionValue):
        fail("Internal runtime confusion value is malformed")
    try:
        decode_metric_spec(value.spec)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Runtime ConfusionMatrix specification is invalid: {exc}")
    graph = Graph(translator)
    matrix_ref = _matrix_ref(graph, value.matrix)
    reference = graph.node(_CONFUSION_VALUE, data=matrix_ref, spec=value.spec)
    return {"kind": "runtime_value", **_base_result(graph, reference, [])}
