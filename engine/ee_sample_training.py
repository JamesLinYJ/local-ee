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

    def __init__(self):
        self.steps = 0

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
    context = _TrainingContext()
    classifier = StaticMinimumDistance(metric=training_spec["metric"])
    trained = _train(context, {
        "classifier": classifier,
        "features": table.data,
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
