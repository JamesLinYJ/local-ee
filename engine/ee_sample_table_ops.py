"""Bounded trusted filter and stable limit operations on sampled tables."""
from __future__ import annotations

import re
from typing import Any

from .ee_sampling_result import PendingSampledTable, SampledFeatureTable


MAX_SAMPLE_TABLE_WORK = 50_000
MAX_SAMPLE_OPERATION_BYTES = 16_384
MAX_SAMPLE_TABLE_OPERATIONS = 16
_SAMPLE_INDEX = re.compile(r"f(0|[1-9][0-9]{0,2})_r(0|[1-9][0-9]{0,15})_c(0|[1-9][0-9]{0,15})\Z")


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
    else:
        raise ValueError("Unsupported sampled table operation")
    return operation


def _table_state(table, context: _SampleOperationContext):
    from gee.sampling_spec import MAX_BYTES, decode_sampling_spec, sampling_columns
    from gee.sample_table_spec import decode_sample_operation

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
    if list(table.columns) != sampling_columns(spec):
        raise ValueError("Sampled feature table columns differ from its original sample schema")
    operations = getattr(table, "sample_operations", ())
    if (type(operations) is not tuple or len(operations) >= MAX_SAMPLE_TABLE_OPERATIONS
            or any(type(item) is not str for item in operations)):
        raise ValueError("Sampled feature operation chain exceeds 16 operations")
    for item in operations:
        if len(item) > MAX_SAMPLE_OPERATION_BYTES:
            raise ValueError("Prior sample operation exceeds the 16384-byte limit")
        try:
            operation_bytes = item.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ValueError("Prior sample operation must be valid UTF-8") from exc
        if len(operation_bytes) > MAX_SAMPLE_OPERATION_BYTES:
            raise ValueError("Prior sample operation exceeds the 16384-byte limit")
        context.charge(len(operation_bytes))
        decode_sample_operation(item)
    return sample_spec, operations, spec


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


def _result_table(table, data, sample_spec, operations, operation_text, context):
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
            columns=tuple(table.columns),
            sample_spec=sample_spec,
            traces=common["traces"],
            data_tracer=common["data_tracer"],
        )
        result.sample_spec_verified = True
        result.sample_operations = chain
        result.sample_operation_work = context.steps
        return result
    context.charge(len(data["features"]) * len(table.columns))
    result = SampledFeatureTable(data=data, columns=list(table.columns))
    for name, value in common.items():
        setattr(result, name, value)
    return result


def local_ee_sample_table_op(args, env):
    """Apply one canonical filter/limit to a typed actual or pending table."""
    from .ee_process_adapters import _checked_args

    args = _checked_args(args, "local_ee_sample_table_op", {"data", "spec"})
    table = args["data"]
    if type(table) not in (SampledFeatureTable, PendingSampledTable):
        raise ValueError("Sample table operations require an actual or pending sampled table")
    context = _SampleOperationContext(getattr(table, "sample_operation_work", 0))
    sample_spec, operations, origin_spec = _table_state(table, context)
    operation_text = args["spec"]
    operation = _read_operation(operation_text, context)
    if type(table) is PendingSampledTable:
        # Predicates were structurally decoded, but dry-run has no fabricated
        # rows on which to evaluate them.
        return _result_table(table, None, sample_spec, operations, operation_text, context)

    row_count = table.row_count
    if type(row_count) is not int or not 0 <= row_count <= 1000:
        raise ValueError("Actual sample table exceeds 1000 rows")
    columns = table.columns
    context.charge(row_count * len(columns))
    data = table.data
    if type(data) is not dict or data.get("type") != "FeatureCollection":
        raise ValueError("Actual sample table must contain a FeatureCollection")
    features = data.get("features")
    if type(features) is not list or len(features) > 1000:
        raise ValueError("Actual sample table exceeds 1000 rows")
    output = _apply_features(
        features, operation, context,
        source_count=len(origin_spec["regions"]["features"]),
    )
    result_data = {**data, "features": output}
    return _result_table(table, result_data, sample_spec, operations, operation_text, context)
