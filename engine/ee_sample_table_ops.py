"""Bounded trusted operations on sampled tables."""
from __future__ import annotations

import re
from typing import Any

from .ee_sampling_result import PendingSampledTable, SampledFeatureTable


MAX_SAMPLE_TABLE_WORK = 50_000
MAX_SAMPLE_OPERATION_BYTES = 16_384
MAX_SAMPLE_TABLE_OPERATIONS = 16
_SAMPLE_INDEX = re.compile(r"f(0|[1-9][0-9]{0,2})_r(0|[1-9][0-9]{0,15})_c(0|[1-9][0-9]{0,15})\Z")
_RANDOM_OPERATION_MARKER = '"operation":"random_column"'


class _SampleOperationContext:
    """Small work counter accepted by the existing feature predicate engine."""

    def __init__(self, steps: int):
        if type(steps) is not int or not 0 <= steps <= MAX_SAMPLE_TABLE_WORK:
            raise ValueError("Sampled feature operation exceeds the 50000-step work budget")
        self._steps = steps

    @property
    def steps(self) -> int:
        return self._steps

    @steps.setter
    def steps(self, value: int) -> None:
        if type(value) is not int or value < 0 or value > MAX_SAMPLE_TABLE_WORK:
            raise ValueError("Sampled feature operation exceeds the 50000-step work budget")
        self._steps = value

    @staticmethod
    def allowed(arguments: dict, names: set[str]) -> None:
        unknown = set(arguments) - names
        if unknown:
            raise ValueError(f"Unsupported sampled feature filter arguments: {sorted(unknown)}")

    def matches(self, predicate, feature):
        from gee.compat.earthengine.filtering import matches_filter

        return matches_filter(self, predicate, feature)

    def charge(self, amount: int = 1) -> None:
        self.steps = self.steps + amount


def _read_operation(text: Any, context: _SampleOperationContext):
    from gee.sample_table_spec import decode_sample_operation, decode_sample_predicate
    from gee.compat.earthengine.ir import Filter

    if type(text) is not str:
        raise ValueError("local_ee_sample_table_op spec must be canonical JSON text")
    if len(text) > MAX_SAMPLE_OPERATION_BYTES:
        raise ValueError("Sample table operation exceeds the 16384-byte limit")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Sample table operation must be valid UTF-8") from exc
    if len(encoded) > MAX_SAMPLE_OPERATION_BYTES:
        raise ValueError("Sample table operation exceeds the 16384-byte limit")
    context.charge(len(encoded))  # Charge before parsing or allocating the operation.
    operation = decode_sample_operation(text)
    if operation["operation"] == "filter":
        predicate = decode_sample_predicate(operation["predicate"])
        if not isinstance(predicate, Filter):
            raise ValueError("Sample table filter decoder returned an invalid predicate")
        operation = {**operation, "predicate": predicate}
    elif operation["operation"] == "limit":
        count = operation["count"]
        if count is not None and (type(count) is not int or not 0 <= count <= 1000):
            raise ValueError("Sample table limit count must be null or an integer from 0 to 1000")
    elif operation["operation"] == "random_column":
        # decode_sample_operation has already applied the exact random spec
        # validator; the immutable wire dictionary is consumed by the hasher.
        pass
    else:
        raise ValueError("Unsupported sampled table operation")
    return operation


def _schema_shape_work(operations: tuple[str, ...]) -> int:
    # Canonical JSON specs sort keys and escape embedded quotes, so this marker
    # counts only the exact operation field. The schema helper still validates
    # every spec before using the estimate.
    random_count = sum(_RANDOM_OPERATION_MARKER in item for item in operations)
    return 256 * (1 + random_count)


def _table_state(table, context: _SampleOperationContext):
    from gee.sampling_spec import MAX_BYTES, decode_sampling_spec
    from gee.sample_table_schema import sampled_columns

    sample_spec = getattr(table, "sample_spec", None)
    if type(sample_spec) is not str or getattr(table, "sample_spec_verified", False) is not True:
        raise ValueError("Sampled feature table is missing its original sampling specification")
    if len(sample_spec) > MAX_BYTES:
        raise ValueError("Original sample specification exceeds the 1000000-byte limit")
    try:
        sample_spec_bytes = sample_spec.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("Original sample specification must be valid UTF-8") from exc
    if len(sample_spec_bytes) > MAX_BYTES:
        raise ValueError("Original sample specification exceeds the 1000000-byte limit")
    context.charge(len(sample_spec_bytes))
    spec = decode_sampling_spec(sample_spec)
    operations = getattr(table, "sample_operations", ())
    if (type(operations) is not tuple or len(operations) > MAX_SAMPLE_TABLE_OPERATIONS
            or any(type(item) is not str for item in operations)):
        raise ValueError("Sampled feature operation chain exceeds 16 operations")
    operation_scan_work = 0
    for item in operations:
        if len(item) > MAX_SAMPLE_OPERATION_BYTES:
            raise ValueError("Prior sample operation exceeds the 16384-byte limit")
        try:
            operation_bytes = item.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("Prior sample operation must be valid UTF-8") from exc
        if len(operation_bytes) > MAX_SAMPLE_OPERATION_BYTES:
            raise ValueError("Prior sample operation exceeds the 16384-byte limit")
        operation_scan_work += 2 * len(operation_bytes) + 1
    # The shared schema helper validates and decodes the canonical chain.
    # Reserve those scans and one bounded header pass per randomColumn before
    # it builds any schema. Filters and limits do not alter the header.
    context.charge(operation_scan_work + _schema_shape_work(operations))
    columns = sampled_columns(spec, operations)
    declared_columns = (table.columns if type(table) is PendingSampledTable
                        else getattr(table, "_columns", None))
    if type(declared_columns) is not tuple or declared_columns != tuple(columns):
        raise ValueError("Sampled feature table columns differ from its declared operation schema")
    return sample_spec, operations, spec, columns


def validate_sample_collection_metadata(data: Any, origin_spec: dict | None, charge) -> None:
    """Require the exact collection-level metadata declared by the sampler."""
    if type(data) is not dict:
        raise ValueError("Sampled data must be a FeatureCollection object")
    charge(len(data) + 3)
    expected_fields = {"type", "features"}
    if origin_spec is not None and origin_spec.get("version") == 2:
        expected_fields.add("properties")
    if set(data) != expected_fields or data.get("type") != "FeatureCollection":
        raise ValueError("Sampled FeatureCollection fields differ from declared sampler metadata")
    if "properties" not in expected_fields:
        return
    metadata = data["properties"]
    expected_bands = origin_spec.get("bands")
    if type(metadata) is not dict:
        raise ValueError("Image.sample FeatureCollection metadata must be an object")
    charge(len(metadata) + (len(expected_bands) if type(expected_bands) is list else 1))
    if (set(metadata) != {"band_order"} or type(metadata["band_order"]) is not list
            or metadata["band_order"] != expected_bands):
        raise ValueError("Image.sample band_order metadata differs from declared source bands")


def _generated_sample_index(feature: dict, source_count: int) -> str | None:
    """Expose only IDs produced by the bounded sampler as system:index."""
    identifier = feature.get("id")
    if type(identifier) is not str or len(identifier) > 64:
        return None
    match = _SAMPLE_INDEX.fullmatch(identifier)
    if match is None:
        return None
    feature_index, row, column = (int(value) for value in match.groups())
    if feature_index >= source_count or row > 2**53 or column > 2**53:
        return None
    return identifier


def _apply_features(
    features: list[dict], operation: dict, context: _SampleOperationContext,
    source_count: int,
):
    if operation["operation"] == "limit":
        context.charge(len(features))
        count = operation["count"]
        return features if count is None else features[:count]

    from gee.compat.earthengine.feature_filters import matches_feature_filter

    kept = []
    predicate = operation["predicate"]
    for feature in features:
        context.charge()
        properties = feature["properties"]
        index = _generated_sample_index(feature, source_count)
        if index is not None:
            if "system:index" in properties:
                raise ValueError("Sampled feature properties cannot override reserved system:index")
            context.charge(len(properties) + 2)
            view = {**feature, "properties": {**properties, "system:index": index}}
        else:
            view = feature
        # Only literal True passes; the existing filter IR's UNKNOWN sentinel
        # therefore behaves as a non-match for missing/null ordered fields.
        if matches_feature_filter(context, predicate, view) is True:
            kept.append(feature)
    return kept


def _result_table(table, data, columns, sample_spec, operations, operation_text, context):
    chain = (*operations, operation_text)
    common = {
        "sample_spec": sample_spec,
        "sample_spec_verified": True,
        "traces": tuple(getattr(table, "traces", ())),
        "data_tracer": getattr(table, "data_tracer", None),
        "sample_operations": chain,
        "sample_operation_work": context.steps,
    }
    if type(table) is PendingSampledTable:
        result = PendingSampledTable(
            columns=tuple(columns),
            sample_spec=sample_spec,
            traces=common["traces"],
            data_tracer=common["data_tracer"],
        )
        result.sample_spec_verified = True
        result.sample_operations = chain
        result.sample_operation_work = context.steps
        return result
    # The result constructor validates, deep-copies, and caches work over the
    # full nested FeatureCollection (including unselected properties and
    # geometry). Measure that owned structure before constructing it, then
    # charge the same conservative node/slot bound used by SampledFeatureTable
    # before its deep copy can allocate.
    output_copy_work = SampledFeatureTable._measure_copy_work(data)
    context.charge(len(data["features"]) * len(columns) + output_copy_work)
    result = SampledFeatureTable(data=data, columns=list(columns))
    for name, value in common.items():
        setattr(result, name, value)
    return result


def local_ee_sample_table_op(args, env):
    """Apply one canonical filter, limit, or randomColumn to a sampled table."""
    from .ee_process_adapters import _checked_args

    args = _checked_args(args, "local_ee_sample_table_op", {"data", "spec"})
    table = args["data"]
    if type(table) not in (SampledFeatureTable, PendingSampledTable):
        raise ValueError("Sample table operations require an actual or pending sampled table")
    context = _SampleOperationContext(getattr(table, "sample_operation_work", 0))
    sample_spec, operations, origin_spec, _ = _table_state(table, context)
    if len(operations) >= MAX_SAMPLE_TABLE_OPERATIONS:
        raise ValueError("Sampled feature operation chain already contains 16 operations")
    operation_text = args["spec"]
    operation = _read_operation(operation_text, context)
    from gee.sample_table_schema import sampled_columns

    # Validate row keys against the schema immediately before this operation,
    # including columns produced by earlier randomColumn operations.
    extended_chain = (*operations, operation_text)
    chain_scan_work = _schema_shape_work(extended_chain)
    for item in extended_chain:
        chain_scan_work += 2 * len(item.encode("utf-8")) + 1
    context.charge(chain_scan_work)
    result_columns = sampled_columns(origin_spec, extended_chain)
    if type(table) is PendingSampledTable:
        # Predicates were structurally decoded, but dry-run has no fabricated
        # rows on which to evaluate them.
        return _result_table(
            table, None, result_columns, sample_spec, operations, operation_text, context,
        )

    row_count = table.row_count
    if type(row_count) is not int or not 0 <= row_count <= 1000:
        raise ValueError("Actual sample table exceeds 1000 rows")
    columns = table.columns
    copy_work = table.data_copy_work
    if type(copy_work) is not int or copy_work < 0:
        raise ValueError("Actual sample table has invalid cached copy-work metadata")
    # ``data`` returns a complete deep copy, so charge the cached full-tree
    # bound before invoking its getter. Cell work remains separately charged.
    context.charge(row_count * len(columns) + copy_work)
    data = table.data
    if type(data) is not dict or data.get("type") != "FeatureCollection":
        raise ValueError("Actual sample table must contain a FeatureCollection")
    validate_sample_collection_metadata(data, origin_spec, context.charge)
    features = data.get("features")
    if type(features) is not list or len(features) > 1000:
        raise ValueError("Actual sample table exceeds 1000 rows")
    if operation["operation"] == "random_column":
        from gee.random_column_values import apply_random_column

        output = apply_random_column(features, operation, charge=context.charge)
    else:
        output = _apply_features(
            features, operation, context,
            source_count=len(origin_spec["regions"]["features"]),
        )
    result_data = {**data, "features": output}
    return _result_table(
        table, result_data, result_columns, sample_spec, operations, operation_text, context,
    )
