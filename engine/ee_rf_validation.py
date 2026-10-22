"""Trusted Smile RF feature prediction and runtime validation handlers."""
from __future__ import annotations

from .ee_rf_validation_matrix import (
    PendingRfConfusionMatrix,
    RuntimeConfusionMatrix,
    confusion_from_native,
    error_matrix,
    evaluate_confusion,
)
from .ee_rf_validation_runtime import (
    OperationBudget,
    actual_table,
    attach_lineage,
    checked,
    checked_model,
    decoded_classify_spec,
    dry_run_tracer,
    pending_matrix,
    pending_table,
    prediction_rows,
    sampled_table_state,
    source_columns,
    utf8_size,
)
from .ee_sampling_result import PendingSampledTable, SampledFeatureTable
from .ee_smile_rf import PendingSmileRfModel, TrainedSmileRfModel, _confusion_jvm
from .ee_smile_rf_training import MAX_RF_ROWS_JSON_BYTES


def local_ee_smile_rf_classify_rows(args, env):
    """Predict inline canonical FeatureCollection rows with an actual Smile model."""
    from gee.rf_validation_spec import decode_feature_rows, decode_prediction_rows
    from .ee_json_result import RuntimeFeatureTable

    args = checked(args, "local_ee_smile_rf_classify_rows", {"rows", "spec", "model"})
    budget = OperationBudget()
    classify_spec = decoded_classify_spec(args["spec"], budget.wire)
    rows_text = args["rows"]
    row_bytes = utf8_size(rows_text, MAX_RF_ROWS_JSON_BYTES, "RF feature rows")
    budget.wire.charge(row_bytes * 4)
    data = decode_feature_rows(rows_text)
    model = checked_model(args["model"])
    rows, query_text, features = prediction_rows(data, model, classify_spec, budget)
    tracer = dry_run_tracer(env)
    if type(model) is PendingSmileRfModel or tracer is not None:
        if type(model) is PendingSmileRfModel and model.data_tracer is not tracer:
            raise ValueError("Pending Smile RF model does not belong to this dry run")
        return pending_table(classify_spec["columns"], tracer, model)

    if type(model) is not TrainedSmileRfModel:
        raise ValueError("RF feature classification requires an exact trusted trained model")
    prediction_upper = 32 + 5 * len(rows)
    budget.wire.charge(prediction_upper * 3)
    from .ee_rf_validation_runtime import predict

    prediction_text = predict(model, query_text)
    utf8_size(prediction_text, prediction_upper, "RF prediction envelope")
    predictions = decode_prediction_rows(
        prediction_text, len(rows), model.class_count,
    )["predictions"]
    from .ee_rf_validation_runtime import classified_json_size

    output_size = classified_json_size(
        rows_text, features, predictions, classify_spec["output_name"],
    )
    if output_size > 1_000_000:
        raise ValueError("RF classified FeatureCollection exceeds 1000000 UTF-8 bytes")
    # Reserve JSON serialization and the existing bounded CSV validation pass.
    budget.wire.charge(output_size + 1_000_000)
    for feature, label in zip(features, predictions):
        feature["properties"][classify_spec["output_name"]] = label
    copy_work = SampledFeatureTable._measure_copy_work(data)
    budget.charge(copy_work + len(features) * len(classify_spec["columns"]))
    result = RuntimeFeatureTable(data, list(classify_spec["columns"]))
    return attach_lineage(result, None, model)


def local_ee_smile_rf_classify_samples(args, env):
    """Predict an audited sampler/filter/limit table while retaining its rows."""
    from gee.rf_validation_spec import decode_prediction_rows
    from .ee_json_result import RuntimeFeatureTable

    args = checked(args, "local_ee_smile_rf_classify_samples", {"data", "spec", "model"})
    table = args["data"]
    if type(table) not in (SampledFeatureTable, PendingSampledTable):
        raise ValueError("RF sample classification requires an audited sampler/filter/limit table")
    prior = 0
    if type(table) in (SampledFeatureTable, PendingSampledTable):
        from .ee_smile_rf_training import _sample_prior_work

        prior = _sample_prior_work(table)
    budget = OperationBudget(prior)
    classify_spec = decoded_classify_spec(args["spec"], budget.wire)
    columns = sampled_table_state(table, budget)
    model = checked_model(args["model"])
    # Schema order is part of the audited sampler contract. The shared row
    # selector also checks that the actual feature union matches this table.
    expected = source_columns(classify_spec)
    if tuple(expected) != columns:
        raise ValueError("RF classification columns differ from the audited input table schema")
    for name in model.schema:
        if name not in columns:
            raise ValueError(f"RF audited table schema is missing classifier property: {name}")

    tracer = dry_run_tracer(env)
    if type(table) is PendingSampledTable or type(model) is PendingSmileRfModel or tracer is not None:
        sources = [table, model]
        if type(model) is PendingSmileRfModel and model.data_tracer is not tracer:
            raise ValueError("Pending Smile RF model does not belong to this dry run")
        if type(table) is PendingSampledTable and table.data_tracer is not tracer:
            raise ValueError("Pending RF samples do not belong to this dry run")
        return pending_table(classify_spec["columns"], tracer, *sources)

    if type(model) is not TrainedSmileRfModel:
        raise ValueError("RF sample classification requires an exact trusted trained model")
    if type(table) is not SampledFeatureTable:
        raise ValueError("RF sample classification requires a sampler/filter/limit table")
    budget.charge(table.data_copy_work + table.row_count * len(columns))
    data = table.data
    from .ee_sample_table_ops import validate_sample_collection_metadata

    validate_sample_collection_metadata(
        data, getattr(budget, "sampled_origin_spec", None), budget.charge,
    )
    budget.audited_columns = columns
    # Reserve the bounded table reads and both JSON/CSV representations before
    # walking the data or entering the JVM.
    budget.wire.charge(2_000_000)
    rows, query_text, features = prediction_rows(data, model, classify_spec, budget)
    prediction_upper = 32 + 5 * len(rows)
    budget.wire.charge(prediction_upper * 3)
    from .ee_rf_validation_runtime import predict

    prediction_text = predict(model, query_text)
    utf8_size(prediction_text, prediction_upper, "RF prediction envelope")
    predictions = decode_prediction_rows(
        prediction_text, len(rows), model.class_count,
    )["predictions"]
    for feature, label in zip(features, predictions):
        feature["properties"][classify_spec["output_name"]] = label
    copy_work = SampledFeatureTable._measure_copy_work(data)
    budget.charge(copy_work + len(features) * len(classify_spec["columns"]))
    result = RuntimeFeatureTable(data, list(classify_spec["columns"]))
    return attach_lineage(result, None, table, model)


def local_ee_smile_rf_confusion(args, env):
    """Return the real model's training-row resubstitution confusion matrix."""
    args = checked(args, "local_ee_smile_rf_confusion", {"model"})
    model = checked_model(args["model"])
    tracer = dry_run_tracer(env)
    if type(model) is PendingSmileRfModel or tracer is not None:
        if type(model) is PendingSmileRfModel and model.data_tracer is not tracer:
            raise ValueError("Pending Smile RF model does not belong to this dry run")
        return pending_matrix(tracer, model)
    if type(model) is not TrainedSmileRfModel:
        raise ValueError("Smile RF confusionMatrix requires an exact trusted trained model")

    budget = OperationBudget()
    # Reserve native output parsing and the detached matrix copy using the
    # validated model class count before asking the trusted factory.
    classes = model.class_count
    budget.charge(3 * classes * classes + 2 * classes)
    budget.wire.charge(16_384 * 3)
    text = _confusion_jvm(model._java_model)
    matrix = confusion_from_native(text, model.class_count, model.training_row_count)
    return matrix


def local_ee_error_matrix(args, env):
    """Build a bounded runtime error matrix over sampled or classified features."""
    from gee.rf_validation_spec import decode_matrix_spec
    from .ee_json_result import PendingRuntimeTable, RuntimeFeatureTable

    args = checked(args, "local_ee_error_matrix", {"data", "spec"})
    budget = OperationBudget()
    spec_text = args["spec"]
    spec_size = utf8_size(spec_text, 16_384, "RF error-matrix specification")
    budget.wire.charge(spec_size * 2)
    matrix_spec = decode_matrix_spec(spec_text)
    table = args["data"]
    if type(table) in (PendingSampledTable, PendingRuntimeTable):
        columns = sampled_table_state(table, budget) if type(table) is PendingSampledTable else tuple(table.columns)
        pending = True
        data = None
    elif type(table) in (SampledFeatureTable, RuntimeFeatureTable):
        data, columns, pending = actual_table(table, budget, allow_runtime=True)
    else:
        raise ValueError("Collection.errorMatrix requires an audited sampled or classified table")
    known_empty_runtime_table = type(table) is RuntimeFeatureTable and table.row_count == 0
    if not known_empty_runtime_table and matrix_spec["actual"] not in columns:
        raise ValueError(f"Collection.errorMatrix property is missing: {matrix_spec['actual']}")
    if not known_empty_runtime_table and matrix_spec["predicted"] not in columns:
        raise ValueError(f"Collection.errorMatrix property is missing: {matrix_spec['predicted']}")

    tracer = dry_run_tracer(env)
    if pending or tracer is not None:
        if pending and getattr(table, "data_tracer", None) is not tracer:
            raise ValueError("Pending RF feature table does not belong to this dry run")
        return pending_matrix(tracer, table)
    if type(data) is not dict or type(data.get("features")) is not list:
        raise ValueError("RF error matrix requires an actual bounded FeatureCollection")
    return error_matrix(
        data["features"], matrix_spec["actual"], matrix_spec["predicted"],
        matrix_spec["order"], budget,
    )


def local_ee_confusion_value(args, env):
    """Materialize one bounded matrix accessor as owned JSON or a dry-run value."""
    from gee.rf_validation_spec import decode_metric_spec
    from .ee_json_result import PendingRuntimeValue, RuntimeJsonResult

    args = checked(args, "local_ee_confusion_value", {"data", "spec"})
    spec_text = args["spec"]
    spec_size = utf8_size(spec_text, 16_384, "Runtime ConfusionMatrix specification")
    budget = OperationBudget()
    budget.wire.charge(spec_size * 2)
    metric_spec = decode_metric_spec(spec_text)
    matrix = args["data"]
    if type(matrix) is PendingRfConfusionMatrix:
        tracer = dry_run_tracer(env)
        if tracer is None or matrix.data_tracer is not tracer:
            raise ValueError("Pending RF confusion matrix does not belong to this dry run")
        return PendingRuntimeValue(traces=matrix.traces, data_tracer=tracer)
    if type(matrix) is not RuntimeConfusionMatrix:
        raise ValueError("ConfusionMatrix accessors require an RF confusion or errorMatrix result")
    tracer = dry_run_tracer(env)
    if tracer is not None:
        return PendingRuntimeValue(data_tracer=tracer)
    return RuntimeJsonResult(evaluate_confusion(matrix, metric_spec, budget))
