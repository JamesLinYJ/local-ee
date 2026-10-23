"""Lazy bounded operations on RF-classified FeatureCollections."""
from __future__ import annotations

from dataclasses import replace

from ...runtime_table_spec import PROCESS, runtime_columns
from ...sample_table_spec import (
    MAX_OPERATION_BYTES,
    MAX_OPERATIONS,
    prepare_sample_filter,
    prepare_sample_limit,
)
from .feature_values import charge
from .ir import Filter, SampledFeatures, fail
from .random_column import prepare_random_column
from .runtime_feature_ir import RFClassifiedFeatureTable
from .sampled_feature_ops import _filter_work


_SUPPORTED = frozenset({"Collection.filter", "Collection.limit", "Collection.randomColumn"})


def _operations(table, translator, label):
    operations = table.operations
    if type(operations) is not tuple or len(operations) > MAX_OPERATIONS:
        fail(f"{label} supports at most 16 ordered table operations")
    charge(translator, 8 + len(operations))
    if any(type(operation) is not str or len(operation) > MAX_OPERATION_BYTES
           for operation in operations):
        fail(f"{label} contains a malformed or oversized operation spec")
    return operations


def _source_operations(table, translator, label):
    if isinstance(table.source, SampledFeatures):
        operations = table.source.operations
        if type(operations) is not tuple or len(operations) > MAX_OPERATIONS:
            fail(f"{label} sampled source supports at most 16 ordered operations")
        charge(translator, 8 + len(operations))
        if any(type(operation) is not str or len(operation) > MAX_OPERATION_BYTES
               for operation in operations):
            fail(f"{label} sampled source has malformed or oversized operations")
        # The sampled producer validated each append. The graph boundary later
        # revalidates the full origin and operation specs before lowering it.
        return operations
    if type(table.source) is dict and table.source.get("type") == "FeatureCollection":
        return ()
    fail(f"{label} has an unsupported classification source")


def validated_classified_schema(table, translator, label="Classified feature table"):
    """Revalidate immutable classification and operation lineage before use."""
    if not isinstance(table, RFClassifiedFeatureTable):
        fail(f"{label} has a malformed runtime feature table")
    if type(table.spec) is not str:
        fail(f"{label} has a malformed classification specification")
    operations = _operations(table, translator, label)
    source_operations = _source_operations(table, translator, label)
    if len(source_operations) + len(operations) > MAX_OPERATIONS:
        fail("Classified FeatureCollection supports at most 16 combined sample and table operations")
    if type(table.columns) is not tuple or len(table.columns) > 256:
        fail(f"{label} has malformed logical columns")
    if table.row_count is not None and (
        type(table.row_count) is not int or not 0 <= table.row_count <= 1000
    ):
        fail(f"{label} has an invalid known row count")
    if isinstance(table.source, SampledFeatures):
        if table.rows is not None:
            fail(f"{label} sampled source cannot contain inline rows")
    elif type(table.rows) is not str:
        fail(f"{label} inline source is missing its canonical rows")

    # The classification schema and operation specs are the bounded source of
    # all output names. Charge that scan and the copied header list first.
    charge(translator, 8 + 6 * (len(table.spec)
                                + sum(map(len, operations))))
    try:
        columns = runtime_columns(table.spec, operations,
                                  charge=lambda amount: charge(translator, amount))
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"{label} has an invalid transformed schema: {exc}")
    charge(translator, len(columns) + 1)
    if tuple(columns) != table.columns:
        fail(f"{label} columns differ from its base specification and operations")
    return columns, operations, source_operations


def invoke_classified_feature_operation(translator, name, arguments):
    """Append one canonical operation without predicting or copying table rows."""
    table = arguments.get("collection")
    if not isinstance(table, RFClassifiedFeatureTable):
        table = next((arguments.get(key) for key in ("collection1", "collection2")
                      if isinstance(arguments.get(key), RFClassifiedFeatureTable)), None)
    if not isinstance(table, RFClassifiedFeatureTable):
        fail("Classified FeatureCollection operation requires a classified table")
    if name not in _SUPPORTED:
        fail("RF-classified FeatureCollections support only filter, unsorted limit, and randomColumn; map, sort, merge, and retraining are unsupported")

    _columns, operations, source_operations = validated_classified_schema(
        table, translator, "RF-classified FeatureCollection",
    )
    if len(operations) + len(source_operations) >= MAX_OPERATIONS:
        fail("Classified FeatureCollection supports at most 16 combined sample and table operations")

    if name == "Collection.filter":
        translator.allowed(arguments, {"collection", "filter"})
        filt = arguments.get("filter")
        if not isinstance(filt, Filter):
            fail("Classified FeatureCollection.filter requires a serialized ee.Filter")
        charge(translator, 6 * _filter_work(filt))
        try:
            operation = prepare_sample_filter(filt)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"Unsupported classified FeatureCollection filter: {exc}")
    elif name == "Collection.limit":
        translator.allowed(arguments, {"collection", "limit", "key", "ascending"})
        if arguments.get("key") is not None:
            fail("Classified FeatureCollection.limit does not support sorting")
        if type(arguments.get("ascending", True)) is not bool:
            fail("Collection ascending must be a boolean")
        count = arguments.get("limit")
        if count is not None and (type(count) is not int or not 0 <= count <= 1000):
            fail("Classified FeatureCollection limit must be null or an integer from 0 to 1000")
        charge(translator, 128)
        try:
            operation = prepare_sample_limit(count)
        except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
            fail(f"Unsupported classified FeatureCollection limit: {exc}")
    else:
        operation = prepare_random_column(translator, arguments)

    if type(operation) is not str or len(operation) > MAX_OPERATION_BYTES:
        fail("Classified FeatureCollection operation exceeds 16384 characters")
    charge(translator, 8 + 6 * len(operation))
    next_operations = (*operations, operation)
    # Validate sequential randomColumn rowKeys against the headers produced by
    # all earlier operations before returning the new immutable IR value.
    charge(translator, 8 + 6 * (len(table.spec)
                                + sum(map(len, next_operations))))
    try:
        next_columns = runtime_columns(table.spec, next_operations,
                                       charge=lambda amount: charge(translator, amount))
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Classified FeatureCollection operation has an invalid schema: {exc}")
    charge(translator, len(next_columns) + 1)
    return replace(table, columns=tuple(next_columns), operations=next_operations)


__all__ = ["PROCESS", "invoke_classified_feature_operation", "validated_classified_schema"]
