"""Runtime training bridge for the bounded EE minimum-distance classifier."""
from __future__ import annotations

from .ee_sampling_result import (
    PendingMinimumDistanceModel,
    PendingSampledTable,
    SampledFeatureTable,
)


MAX_CLASSIFIER_WORK = 50_000


class _TrainingContext:
    """Minimal budget interface consumed by the existing static EE trainer."""

    def __init__(self, steps: int = 0):
        if type(steps) is not int or not 0 <= steps <= MAX_CLASSIFIER_WORK:
            raise ValueError("Raster classifier training exceeds the 50000-step work budget")
        self.steps = steps

    def charge(self, amount: int = 1):
        if (type(amount) is not int or amount < 0
                or self.steps + amount > MAX_CLASSIFIER_WORK):
            raise ValueError("Raster classifier training exceeds the 50000-step work budget")
        self.steps += amount

    @staticmethod
    def allowed(args, names):
        unknown = set(args) - names
        if unknown:
            raise ValueError(f"Unsupported classifier training arguments: {sorted(unknown)}")


def _train_table(table: SampledFeatureTable, training_spec: dict) -> dict:
    from gee.compat.earthengine.classifier_model import encode_model, model_serialization_work
    from gee.compat.earthengine.minimum_distance import StaticMinimumDistance, _train

    schema = list(training_spec["schema"])
    required = {training_spec["class_property"], *schema}
    unknown = required - set(table.columns)
    if unknown:
        raise ValueError(f"Sample table is missing training property {sorted(unknown)[0]!r}")
    # Sample-table operations and exact model training share one runtime work
    # budget. Directly constructed trusted test tables have no operation cost.
    operation_work = getattr(table, "sample_operation_work", 0)
    context = _TrainingContext(operation_work)
    origin_spec = _audit_sample_table(table, context)
    copy_work = getattr(table, "data_copy_work", None)
    row_count = getattr(table, "row_count", None)
    if (type(copy_work) is not int or copy_work < 0
            or type(row_count) is not int or not 0 <= row_count <= 1000):
        raise ValueError("Sample table is missing validated copy-work metadata")
    context.charge(copy_work + row_count * len(table.columns))
    features = table.data
    from .ee_sample_table_ops import validate_sample_collection_metadata

    validate_sample_collection_metadata(features, origin_spec, context.charge)
    classifier = StaticMinimumDistance(metric=training_spec["metric"])
    trained = _train(context, {
        "classifier": classifier,
        "features": features,
        "classProperty": training_spec["class_property"],
        "inputProperties": schema,
        "subsampling": 1,
        "subsamplingSeed": 0,
    })
    serialization_work = model_serialization_work(trained)
    if context.steps + serialization_work > MAX_CLASSIFIER_WORK:
        raise ValueError("Raster classifier training exceeds the 50000-step work budget")
    context.steps += serialization_work
    return encode_model(trained)


def _audit_sample_table(table, context):
    operations = getattr(table, "sample_operations", ())
    verified = getattr(table, "sample_spec_verified", False)
    if (type(table) is SampledFeatureTable and hasattr(table, "sample_spec")
            and verified is not True):
        raise ValueError("Actual sampled table carries an unverified origin specification")
    has_sample_metadata = any(hasattr(table, name) for name in (
        "sample_spec", "sample_spec_verified", "sample_operations",
    ))
    if type(table) is SampledFeatureTable and not has_sample_metadata:
        # Directly constructed trusted v1 tables have no recoverable sampler
        # origin. Preserve their declared headers while keeping operation work
        # in the existing shared training budget.
        return None
    if (type(table) is PendingSampledTable
            and not hasattr(table, "sample_spec_verified")
            and not hasattr(table, "sample_operations")):
        # Legacy pending tables carry only schema/traces and cannot materialize
        # rows or authorize an operation until a verified origin is attached.
        return None
    if not has_sample_metadata:
        raise ValueError("Pending minimum-distance samples require a verified origin specification")
    if verified is not True or type(operations) is not tuple:
        raise ValueError("Sampled table requires a verified origin and operation chain")

    from .ee_sample_table_ops import _SampleOperationContext, _table_state

    audit = _SampleOperationContext(0)
    _, _, origin_spec, _ = _table_state(table, audit)
    context.charge(audit.steps)
    return origin_spec


def local_ee_train_minimum_distance(args, env):
    """Train exactly from an actual sampled table or expose a pending schema."""
    from .ee_process_adapters import _checked_args
    from gee.sampling_spec import decode_training_spec

    args = _checked_args(args, "local_ee_train_minimum_distance", {"data", "spec"})
    text = args["spec"]
    if type(text) is not str:
        raise ValueError("local_ee_train_minimum_distance spec must be canonical JSON text")
    training_spec = decode_training_spec(text)
    table = args["data"]
    if isinstance(table, PendingSampledTable):
        operation_work = getattr(table, "sample_operation_work", 0)
        context = _TrainingContext(operation_work)
        _audit_sample_table(table, context)
        schema = tuple(training_spec["schema"])
        required = {training_spec["class_property"], *schema}
        missing = required - set(table.columns)
        if missing:
            raise ValueError(f"Pending sample table is missing training property {sorted(missing)[0]!r}")
        return PendingMinimumDistanceModel(
            metric=training_spec["metric"],
            schema=schema,
            class_property=training_spec["class_property"],
            traces=table.traces,
            data_tracer=table.data_tracer,
        )
    if type(table) is not SampledFeatureTable:
        raise ValueError("Minimum-distance training requires an actual SampledFeatureTable")
    return _train_table(table, training_spec)
