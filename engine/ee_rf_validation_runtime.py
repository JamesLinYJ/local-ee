"""Shared bounded helpers for trusted RF feature validation handlers."""
from __future__ import annotations

import json
from typing import Any

from .ee_sampling_result import PendingSampledTable, SampledFeatureTable
from .ee_smile_rf import (
    PendingSmileRfModel,
    TrainedSmileRfModel,
    _MODEL_TOKEN,
    _predict_jvm_rows,
)
from .ee_smile_rf_training import (
    MAX_RF_RUNTIME_WORK,
    MAX_RF_ROWS_JSON_BYTES,
    _RuntimeWork,
    _WireScan,
    _dry_run_tracer,
    _sample_prior_work,
    _utf8_size,
)


class OperationBudget(_RuntimeWork):
    """Cumulative bounded work and wire scans for one validation operation."""

    def __init__(self, steps=0):
        if type(steps) is not int or not 0 <= steps <= MAX_RF_RUNTIME_WORK:
            raise ValueError("RF validation exceeds the 150000-step object-work budget")
        self.steps = steps
        self.wire = _WireScan()
        self.audited_columns = None

    def charge(self, amount=1):
        if (type(amount) is not int or amount < 0
                or self.steps + amount > MAX_RF_RUNTIME_WORK):
            raise ValueError("RF validation exceeds the 150000-step object-work budget")
        self.steps += amount

    def allowed(self, arguments, names):
        unknown = set(arguments) - set(names)
        if unknown:
            raise ValueError(f"Unsupported runtime confusion arguments: {sorted(unknown)}")


def checked(args, process, expected):
    from .ee_process_adapters import _checked_args

    return _checked_args(args, process, expected)


def checked_model(value):
    if type(value) is TrainedSmileRfModel and value._token is _MODEL_TOKEN:
        if (type(value.training_row_count) is not int or not 2 <= value.training_row_count <= 1000
                or type(value.class_count) is not int or not 2 <= value.class_count <= 64):
            raise ValueError("Smile RF model is missing validated training-row/class metadata")
        return value
    if type(value) is PendingSmileRfModel:
        return value
    raise ValueError("RF feature operations require an exact trusted trained or pending model")


def model_schema(model):
    schema = model.schema
    if (type(schema) is not tuple or not 1 <= len(schema) <= 8
            or any(type(name) is not str for name in schema)
            or len(set(schema)) != len(schema)):
        raise ValueError("Smile RF model has an invalid ordered input schema")
    return schema


def merge_traces(tracer, *sources):
    traces = []
    source_tracers = []
    for source in sources:
        source_tracer = getattr(source, "data_tracer", None)
        if source_tracer is not None:
            source_tracers.append(source_tracer)
        for trace in getattr(source, "traces", ()):
            if all(trace is not existing for existing in traces):
                traces.append(trace)
    if tracer is not None and any(source_tracer is not tracer for source_tracer in source_tracers):
        raise ValueError("Pending RF references must belong to the current dry run")
    owner = tracer
    if owner is None and source_tracers and all(item is source_tracers[0] for item in source_tracers):
        owner = source_tracers[0]
    return tuple(traces), owner


def pending_table(columns, tracer, *sources):
    from .ee_json_result import PendingRuntimeTable

    if tracer is None:
        raise ValueError("Pending RF feature tables can only be used in their dry run")
    traces, owner = merge_traces(tracer, *sources)
    return PendingRuntimeTable(tuple(columns), traces=traces, data_tracer=owner)


def pending_matrix(tracer, *sources):
    from .ee_rf_validation_matrix import PendingRfConfusionMatrix

    if tracer is None:
        raise ValueError("Pending RF confusion matrices can only be used in their dry run")
    traces, owner = merge_traces(tracer, *sources)
    return PendingRfConfusionMatrix(traces=traces, data_tracer=owner)


def decoded_classify_spec(text, wire):
    from gee.rf_validation_spec import decode_classify_spec

    size = _utf8_size(text, 16_384, "RF classification specification")
    wire.charge(size * 2)
    return decode_classify_spec(text)


def sampled_table_state(table, work):
    if type(table) not in (SampledFeatureTable, PendingSampledTable):
        raise ValueError("RF sample classification requires an audited sampler/filter/limit table")
    prior_work = _sample_prior_work(table)
    if work.steps < prior_work:
        work.charge(prior_work - work.steps)
    from .ee_sample_table_ops import _table_state

    # Prior sample work is already reflected in sample_operation_work. Recheck
    # the stored origin and operation texts from a fresh counter, then account
    # for this new validation scan in the RF operation's separate work budget.
    audit_work = OperationBudget()
    _, _, origin_spec, derived_columns = _table_state(table, audit_work)
    work.charge(audit_work.steps)
    columns = table.columns
    if (type(columns) not in (list, tuple) or not columns
            or len(columns) > 256 or len(set(columns)) != len(columns)):
        raise ValueError("RF input table has an invalid audited column schema")
    if tuple(columns) != tuple(derived_columns):
        raise ValueError("RF input table columns differ from its declared operation schema")
    work.sampled_origin_spec = origin_spec
    return tuple(columns)


def source_columns(classify_spec):
    # The prediction column is penultimate, immediately before reserved .geo.
    return [*classify_spec["columns"][:-2], ".geo"]


def query_wire_upper_bound(row_count, width):
    # Every allowed integer has <=16 characters and every finite Float64 has
    # <=25 in Python's shortest JSON spelling; punctuation is included.
    prefix = len('{"rows":[')
    suffix = len('],"version":1}')
    row_size = 2 + max(0, width - 1) + 26 * width
    return prefix + suffix + row_count * row_size + max(0, row_count - 1)


def json_string_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def classified_json_size(input_text, features, predictions, output_name):
    size = len(input_text.encode("utf-8"))
    key_size = json_string_size(output_name)
    for feature, prediction in zip(features, predictions):
        properties = feature["properties"]
        size += (1 if properties else 0) + key_size + 1 + len(str(prediction))
    return size


def prediction_rows(data, model, classify_spec, work):
    from gee.rf_validation_spec import prepare_query_rows

    schema = model_schema(model)
    features = data["features"]
    if len(features) > 1_000:
        raise ValueError("RF feature classification supports at most 1000 rows")
    expected_columns = source_columns(classify_spec)
    audited_columns = getattr(work, "audited_columns", None)
    if audited_columns is not None and tuple(expected_columns) != tuple(audited_columns):
        raise ValueError("RF classification columns differ from the audited input table schema")
    output_name = classify_spec["output_name"]
    work.charge(len(features) * (len(expected_columns) + len(schema) + 3))
    rows = []
    inferred = {"system:index", ".geo"}
    for feature in features:
        properties = feature["properties"]
        if type(properties) is not dict:
            raise ValueError("RF feature classification requires object properties")
        work.charge(len(properties))
        for name in properties:
            work.charge(len(name) + 1)
            if name != "system:index":
                inferred.add(name)
        if output_name in properties:
            raise ValueError(f"RF classification output property already exists: {output_name}")
        values = []
        for name in schema:
            if name not in properties:
                raise ValueError(f"RF feature is missing classifier property: {name}")
            if properties[name] is None:
                raise ValueError(f"RF classifier property is null: {name}")
            values.append(properties[name])
        rows.append(values)

    # A known-empty collection has no feature property union to compare. Its
    # declared columns still come from the classifier contract (and, for
    # sampled input, were independently revalidated against the sample spec).
    if features and (len(expected_columns) != len(inferred) or set(expected_columns) != inferred):
        raise ValueError("RF classification columns differ from the FeatureCollection schema")

    upper_bound = query_wire_upper_bound(len(rows), len(schema))
    if upper_bound > MAX_RF_ROWS_JSON_BYTES:
        raise ValueError("RF feature query rows exceed the 1000000-byte limit")
    work.wire.charge(upper_bound * 3)
    query_text = prepare_query_rows(rows, len(schema))
    if len(query_text.encode("utf-8")) > upper_bound:
        raise RuntimeError("RF query-row wire exceeded its precharged upper bound")
    return rows, query_text, features


def actual_table(data, work, *, allow_runtime):
    from .ee_json_result import RuntimeFeatureTable, PendingRuntimeTable

    if type(data) in (PendingSampledTable, PendingRuntimeTable):
        return None, tuple(data.columns), True
    if type(data) is SampledFeatureTable:
        columns = sampled_table_state(data, work)
    elif allow_runtime and type(data) is RuntimeFeatureTable:
        columns = classified_runtime_columns(data, work)
    else:
        raise ValueError("RF matrix operations require an audited sampled or classified table")

    row_count = getattr(data, "row_count", None)
    if type(row_count) is not int or not 0 <= row_count <= 1_000:
        raise ValueError("RF runtime table exceeds 1000 rows")
    if row_count * len(columns) > 50_000:
        raise ValueError("RF runtime table exceeds 50000 row-by-column cells")
    copy_work = getattr(data, "data_copy_work", None)
    if type(copy_work) is not int or copy_work < 0:
        raise ValueError("RF runtime table is missing validated copy-work metadata")
    work.charge(row_count * len(columns) + copy_work)
    payload = data.data
    if type(data) is SampledFeatureTable:
        from .ee_sample_table_ops import validate_sample_collection_metadata

        validate_sample_collection_metadata(
            payload, getattr(work, "sampled_origin_spec", None), work.charge,
        )
    return payload, columns, False


def attach_lineage(result, tracer, *sources):
    traces, owner = merge_traces(tracer, *sources)
    result.traces = traces
    result.data_tracer = owner
    return result


def classified_runtime_columns(table, work):
    """Revalidate classified schema and inherit its completed table-op work."""
    from .ee_runtime_table_ops import (
        MAX_RUNTIME_TABLE_WORK, has_classification_origin,
        validate_runtime_table_origin,
    )

    if not has_classification_origin(table):
        return tuple(table.columns)
    prior = getattr(table, "runtime_operation_work", None)
    if type(prior) is not int or not 0 <= prior <= MAX_RUNTIME_TABLE_WORK:
        raise ValueError("Runtime classified table has invalid cumulative operation work")
    if work.steps < prior:
        work.charge(prior - work.steps)
    return validate_runtime_table_origin(table, work)


def classified_table_origin(
    table, specification, *, prior_sample_operation_count=0,
    prior_sample_operation_work=0, operations=(), operation_work=None,
):
    """Record exact classifier provenance and the inherited table-op budget."""
    from .ee_json_result import attach_classification_origin

    return attach_classification_origin(
        table, specification,
        prior_sample_operation_count=prior_sample_operation_count,
        prior_sample_operation_work=prior_sample_operation_work,
        operations=operations, operation_work=operation_work,
    )


def predict(model, query_text):
    return _predict_jvm_rows(model._java_model, query_text)


def dry_run_tracer(env):
    return _dry_run_tracer(env)


def utf8_size(text, maximum, label):
    return _utf8_size(text, maximum, label)
