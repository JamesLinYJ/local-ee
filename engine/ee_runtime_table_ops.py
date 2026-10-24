"""Bounded operations on actual and pending RF-classified FeatureCollections."""
from __future__ import annotations

from .ee_json_result import (
    PendingRuntimeTable,
    RuntimeFeatureTable,
    attach_classification_origin,
)
from .ee_runtime_table_lineage import (
    CACHE_ATTESTATION_WORK,
    cached_verified_columns,
    remember_verified_origin,
    table_columns,
)

MAX_RUNTIME_TABLE_WORK = 50_000
MAX_RUNTIME_TABLE_OPERATIONS = 16
MAX_RUNTIME_OPERATION_BYTES = 16_384


def has_classification_origin(table):
    """Return whether a table carries any of the classifier lineage fields."""
    return (
        getattr(table, "classification_origin_verified", False) is True
        or getattr(table, "classification_origin_spec", None) is not None
        or getattr(table, "runtime_operations", ()) != ()
        or getattr(table, "prior_sample_operation_count", None) is not None
        or getattr(table, "prior_sample_operation_work", None) is not None
        or getattr(table, "runtime_operation_work", None) is not None
    )


def _bounded_text(value, maximum, label, work):
    if type(value) is not str or len(value) > maximum:
        raise ValueError(f"{label} must be bounded UTF-8 text")
    # Charge the bounded character scan before allocating its UTF-8 encoding.
    work.charge(len(value))
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8") from exc
    if len(encoded) > maximum:
        raise ValueError(f"{label} exceeds {maximum} UTF-8 bytes")
    return encoded


def _derive_columns(origin_spec, operations, work):
    from gee.runtime_table_spec import runtime_columns

    origin_bytes = _bounded_text(
        origin_spec, MAX_RUNTIME_OPERATION_BYTES,
        "Classification origin specification", work,
    )
    operation_bytes = []
    for text in operations:
        operation_bytes.append(_bounded_text(
            text, MAX_RUNTIME_OPERATION_BYTES, "Runtime table operation", work,
        ))
    # Reserve the decoder scans before the shared helper parses the chain.
    # It charges actual header and row-key shapes before copying or inserting.
    work.charge(
        len(origin_bytes) + sum(2 * len(item) + 1 for item in operation_bytes)
    )
    columns = runtime_columns(origin_spec, operations, charge=work.charge)
    work.charge(len(columns))
    return tuple(columns)


def validate_runtime_table_origin(table, work):
    """Recheck classifier provenance, operation schema and cumulative limits."""
    if type(table) not in (RuntimeFeatureTable, PendingRuntimeTable):
        raise ValueError("Runtime table operations require an exact classified table")
    if getattr(table, "classification_origin_verified", False) is not True:
        raise ValueError("Runtime table is missing its verified classification origin")
    origin_spec = getattr(table, "classification_origin_spec", None)
    if type(origin_spec) is not str:
        raise ValueError("Runtime table has an invalid classification origin specification")
    prior_count = getattr(table, "prior_sample_operation_count", None)
    prior_work = getattr(table, "prior_sample_operation_work", None)
    operation_work = getattr(table, "runtime_operation_work", None)
    operations = getattr(table, "runtime_operations", None)
    if (type(prior_count) is not int or not 0 <= prior_count <= MAX_RUNTIME_TABLE_OPERATIONS
            or type(prior_work) is not int or not 0 <= prior_work <= MAX_RUNTIME_TABLE_WORK
            or type(operation_work) is not int
            or not prior_work <= operation_work <= MAX_RUNTIME_TABLE_WORK):
        raise ValueError("Runtime table has invalid inherited or cumulative operation work")
    if prior_count and prior_work == 0:
        raise ValueError("Runtime table inherited operation count/work metadata is inconsistent")
    if type(operations) is not tuple or len(operations) > MAX_RUNTIME_TABLE_OPERATIONS:
        raise ValueError("Runtime table operation chain must be a tuple of at most16 entries")
    if prior_count + len(operations) > MAX_RUNTIME_TABLE_OPERATIONS:
        raise ValueError("Combined sampled and classified table chain exceeds16 operations")
    if ((not operations and operation_work != prior_work)
            or (operations and operation_work <= prior_work)):
        raise ValueError("Runtime table inherited operation count/work metadata is inconsistent")

    declared = table_columns(table)
    if type(declared) is not tuple or len(declared) > 256:
        raise ValueError("Runtime classified table columns differ from its operation schema")
    expected = cached_verified_columns(
        table, declared, origin_spec, operations, prior_count, prior_work,
        operation_work, work,
    )
    if expected is None:
        expected = _derive_columns(origin_spec, operations, work)
        work.charge(len(declared))  # reserve the bounded schema comparison
        if declared != expected:
            raise ValueError("Runtime classified table columns differ from its operation schema")
        remember_verified_origin(table, work)
    return expected


def _advance_columns(columns, operation, work):
    if operation["operation"] != "random_column":
        work.charge(2 * len(columns))  # fresh list and tuple headers before copying
        return tuple(list(columns))
    row_keys = operation["row_keys"]
    name = operation["column_name"]
    # Validate the bounded key/header shape before set construction or copying.
    work.charge(
        3 * len(columns) + len(row_keys) + 3
        + sum(map(len, columns)) + sum(map(len, row_keys)) + len(name) + 1
    )
    if not set(row_keys) <= set(columns) - {".geo"}:
        raise ValueError("randomColumn rowKeys must exist in the current classified table schema")
    if name in columns:
        work.charge(2 * len(columns))
        return tuple(list(columns))
    if len(columns) >= 256:
        raise ValueError("Runtime feature table exceeds256 columns")
    work.charge(2 * len(columns) + 1)  # slice and new tuple slots before insertion
    return (*columns[:-1], name, ".geo")


def _validate_actual_payload(table, columns, work):
    row_count = table.row_count
    if type(row_count) is not int or not 0 <= row_count <= 1_000:
        raise ValueError("Runtime classified table exceeds 1000 rows")
    if row_count * len(columns) > 50_000:
        raise ValueError("Runtime classified table exceeds 50000 row-by-column cells")
    copy_work = table.data_copy_work
    if type(copy_work) is not int or copy_work < 0:
        raise ValueError("Runtime classified table is missing validated copy-work metadata")
    data = getattr(table, "_data", None)
    if (type(data) is not dict or data.get("type") != "FeatureCollection"
            or type(data.get("features")) is not list):
        raise ValueError("Runtime classified table must contain an actual FeatureCollection")
    if len(data["features"]) != row_count:
        raise ValueError("Runtime classified table row count differs from its stored FeatureCollection")
    measured = _measure_copy_work(data, work)
    if measured != copy_work:
        raise ValueError("Runtime classified table copy-work metadata is inconsistent")
    # Reserve row cells and the full owned copy before invoking ``data``.
    work.charge(row_count * len(columns) + copy_work)
    return row_count, copy_work


def _measure_copy_work(data, work):
    """Measure a bounded structure, charging each visit before traversal."""
    work.charge()  # traversal stack seed, before allocating it
    stack = [data]
    measured = 0
    while stack:
        value = stack.pop()
        work.charge(1)
        measured += 1
        if type(value) is dict:
            slots = len(value)
            work.charge(slots)
            measured += slots
            stack.extend(value.values())
        elif type(value) in (list, tuple):
            slots = len(value)
            work.charge(slots)
            measured += slots
            stack.extend(value)
    return measured


def _filter_view(feature, work):
    properties = feature["properties"]
    geometry = feature.get("geometry")
    if "system:index" in properties or "id" not in feature:
        return {"geometry": geometry, "properties": properties}
    # Literal FeatureCollection IDs are actual system:index values. Sampler
    # row-key patterns do not apply to classified literal features.
    work.charge(len(properties) + 2)
    return {"geometry": geometry,
            "properties": {**properties, "system:index": feature["id"]}}


def _filter_features(features, operation, work):
    from gee.compat.earthengine.feature_filters import matches_feature_filter

    work.charge(len(features))  # maximum retained-row list before allocation
    kept = []
    predicate = operation["predicate"]
    for feature in features:
        work.charge()
        if type(feature) is not dict:
            raise ValueError("Runtime table filters require actual Feature objects")
        properties = feature.get("properties")
        if type(properties) is not dict:
            raise ValueError("Runtime table filters require actual Feature properties")
        view = _filter_view(feature, work)
        if matches_feature_filter(work, predicate, view) is True:
            kept.append(feature)
    return kept


def _apply_operation(features, operation, work):
    name = operation["operation"]
    if name == "filter":
        return _filter_features(features, operation, work)
    if name == "limit":
        work.charge(len(features))
        count = operation["count"]
        return features if count is None else features[:count]
    if name == "random_column":
        from gee.random_column_values import apply_random_column

        return apply_random_column(features, operation, charge=work.charge)
    raise ValueError("Unsupported runtime classified table operation")


def local_ee_runtime_table_op(args, env):
    """Apply one audited filter, unsorted limit or randomColumn to a classified table."""
    from .ee_process_adapters import _checked_args
    from .ee_sample_table_ops import (
        MAX_SAMPLE_TABLE_OPERATIONS, _SampleOperationContext, _read_operation,
    )
    from .ee_rf_validation_runtime import dry_run_tracer, pending_table, attach_lineage

    args = _checked_args(args, "local_ee_runtime_table_op", {"data", "spec"})
    table = args["data"]
    if type(table) not in (RuntimeFeatureTable, PendingRuntimeTable):
        raise ValueError("Runtime table operations require an actual or pending classified table")
    initial_work = getattr(table, "runtime_operation_work", None)
    if type(initial_work) is not int or not 0 <= initial_work <= MAX_RUNTIME_TABLE_WORK:
        raise ValueError("Runtime table has invalid cumulative operation work")
    work = _SampleOperationContext(initial_work)
    columns = validate_runtime_table_origin(table, work)
    prior_count = table.prior_sample_operation_count
    operations = table.runtime_operations
    if prior_count + len(operations) >= MAX_SAMPLE_TABLE_OPERATIONS:
        raise ValueError("Combined sampled and classified table chain already contains16 operations")
    operation_text = args["spec"]
    _bounded_text(
        operation_text, MAX_RUNTIME_OPERATION_BYTES,
        "Runtime table operation", work,
    )
    operation = _read_operation(operation_text, work)
    extended = (*operations, operation_text)
    result_columns = _advance_columns(columns, operation, work)
    if columns[0] != "system:index" or result_columns[-1] != ".geo":
        raise ValueError("Runtime table operation produced invalid reserved headers")
    # Reserve the bounded attestation state before any result allocation; this
    # work is persisted with the next table so each chain step pays its share.
    work.charge(CACHE_ATTESTATION_WORK)

    tracer = dry_run_tracer(env)
    if type(table) is PendingRuntimeTable:
        if tracer is None or getattr(table, "data_tracer", None) is not tracer:
            raise ValueError("Pending runtime table does not belong to this dry run")
        result = PendingRuntimeTable(result_columns, table.traces, tracer)
        result = attach_classification_origin(
            result, table.classification_origin_spec,
            prior_sample_operation_count=prior_count,
            prior_sample_operation_work=table.prior_sample_operation_work,
            operations=extended, operation_work=work.steps,
        )
        remember_verified_origin(result, precharged=True)
        return result
    if tracer is not None:
        source_tracer = getattr(table, "data_tracer", None)
        if source_tracer is not None and source_tracer is not tracer:
            raise ValueError("Runtime classified table does not belong to this dry run")
        result = pending_table(result_columns, tracer, table)
        result = attach_classification_origin(
            result, table.classification_origin_spec,
            prior_sample_operation_count=prior_count,
            prior_sample_operation_work=table.prior_sample_operation_work,
            operations=extended, operation_work=work.steps,
        )
        remember_verified_origin(result, precharged=True)
        return result
    if getattr(table, "data_tracer", None) is not None:
        raise ValueError("Runtime classified table belongs to a different dry run")

    _, _ = _validate_actual_payload(table, columns, work)
    data = table.data
    features = data["features"]
    output = _apply_operation(features, operation, work)
    work.charge(len(data) + 3)  # reserve the result collection shell
    result_data = {**data, "features": output}
    copy_work = _measure_copy_work(result_data, work)
    work.charge(len(output) * len(result_columns) + copy_work)
    work.charge(2 * len(result_columns))  # caller list and constructor tuple
    result = RuntimeFeatureTable(result_data, list(result_columns))
    result = attach_lineage(result, None, table)
    result = attach_classification_origin(
        result, table.classification_origin_spec,
        prior_sample_operation_count=prior_count,
        prior_sample_operation_work=table.prior_sample_operation_work,
        operations=extended, operation_work=work.steps,
    )
    remember_verified_origin(result, precharged=True)
    return result
