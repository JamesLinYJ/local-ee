"""Schema lineage for bounded operations after trusted RF classification."""
from __future__ import annotations

from .rf_validation_spec import decode_classify_spec, prepare_classify_spec
from .sample_table_schema import decode_operation_chain


PROCESS = "local_ee_runtime_table_op"


def runtime_columns(classify_spec, operations=(), *, charge=None):
    """Validate the base declaration and derive sequential logical headers."""
    def reserve(amount):
        if charge is not None:
            charge(amount)

    if type(classify_spec) is dict:
        # Re-encode to apply the exact same field/name constraints as the wire.
        if set(classify_spec) != {"version", "output_name", "columns"}:
            raise ValueError("Invalid runtime classification specification fields")
        if type(classify_spec["version"]) is not int or classify_spec["version"] != 1:
            raise ValueError("Unsupported runtime classification specification version")
        headers = classify_spec["columns"]
        if type(headers) is not list or not 3 <= len(headers) <= 256:
            raise ValueError("Runtime classification requires3..256 columns")
        reserve(len(headers) + 1)
        classify_spec = prepare_classify_spec(
            classify_spec["output_name"], headers,
        )
    headers = decode_classify_spec(classify_spec)["columns"]
    reserve(len(headers) + 1)
    columns = list(headers)
    for operation in decode_operation_chain(operations):
        if operation["operation"] != "random_column":
            continue
        row_keys = operation["row_keys"]
        # Reserve actual scans, set construction, membership and a possible
        # shifted insertion before allocating or changing the header list.
        reserve(3 * len(columns) + len(row_keys) + 3
                + sum(map(len, columns)) + sum(map(len, row_keys)))
        if not set(row_keys) <= set(columns) - {".geo"}:
            raise ValueError("randomColumn rowKeys must exist in the current classified table schema")
        name = operation["column_name"]
        if name not in columns:
            if len(columns) >= 256:
                raise ValueError("Runtime feature table exceeds256 columns")
            columns.insert(len(columns) - 1, name)
    return columns
