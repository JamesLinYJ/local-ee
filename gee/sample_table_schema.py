"""Bounded schema lineage for immutable sampled-table operation chains."""
from __future__ import annotations

from .sample_table_spec import MAX_OPERATION_BYTES, MAX_OPERATIONS, decode_sample_operation
from .sampling_spec import MAX_COLUMNS, sampling_columns


def decode_operation_chain(operations):
    if type(operations) not in (tuple, list) or len(operations) > MAX_OPERATIONS:
        raise ValueError("Sample table supports at most16 operation specifications")
    work = 0
    result = []
    for text in operations:
        if type(text) is not str or len(text) > MAX_OPERATION_BYTES:
            raise ValueError("Sample table operation must be bounded canonical JSON")
        size = len(text.encode("utf-8"))
        work += 2 * size + 1
        if size > MAX_OPERATION_BYTES or work > 50_000:
            raise ValueError("Sample table schema exceeds bounded wire/50000-step work limits")
        result.append(decode_sample_operation(text))
    return result


def sampled_column_lineage(origin_spec, operations=()):
    columns = sampling_columns(origin_spec)
    changed = {}
    for operation in decode_operation_chain(operations):
        if operation["operation"] != "random_column":
            continue
        if not set(operation["row_keys"]) <= set(columns) - {".geo"}:
            raise ValueError("randomColumn rowKeys must exist in the current sample-table schema")
        name = operation["column_name"]
        changed[name] = operation["distribution"]
        if name not in columns:
            if len(columns) >= MAX_COLUMNS:
                raise ValueError("Sample table exceeds256 columns")
            columns.insert(len(columns) - 1, name)
    return columns, changed


def sampled_columns(origin_spec, operations=()):
    return sampled_column_lineage(origin_spec, operations)[0]


def randomized_columns(operations):
    return {operation["column_name"] for operation in decode_operation_chain(operations)
            if operation["operation"] == "random_column"}
