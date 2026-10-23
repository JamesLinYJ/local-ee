"""Bounded bridge from trusted Smile RF models to public explanation values."""
from __future__ import annotations


MAX_NATIVE_EXPLANATION_BYTES = 4096
MAX_EXPLANATION_SPEC_BYTES = 16_384


def _precharge(projection_text, trainer_text):
    """Reserve all bounded parse, wire and owned-copy work before decoding."""
    from .ee_smile_rf_training import (
        MAX_RF_RUNTIME_WORK, _RuntimeWork, _WireScan, _utf8_size,
    )

    projection_bytes = _utf8_size(projection_text, MAX_EXPLANATION_SPEC_BYTES,
                                  "RF explanation specification")
    trainer_bytes = _utf8_size(trainer_text, MAX_EXPLANATION_SPEC_BYTES,
                               "Smile RF trainer specification")
    reserve = projection_bytes * 2 + trainer_bytes * 2 + MAX_NATIVE_EXPLANATION_BYTES * 3
    if reserve > MAX_RF_RUNTIME_WORK:
        raise ValueError("RF explanation exceeds the 150000-step object-work budget")
    work, wire = _RuntimeWork(), _WireScan()
    work.charge(reserve)
    wire.charge(reserve)


def _explain_jvm(java_model):
    """Read the three bounded values through the pinned Smile factory."""
    try:
        from openeogeotrellis.utils import get_jvm

        result = get_jvm().local.ee.smile.LocalEeSmileRfFactory.explain(java_model)
    except Exception as exc:
        raise RuntimeError("Pinned Smile RF explanation factory is unavailable or failed") from exc
    if type(result) is not str:
        raise RuntimeError("Pinned Smile RF explanation factory did not return JSON text")
    return result


def _validated_model_spec(model, projection):
    from gee.smile_rf_spec import decode_rf_spec

    trainer = decode_rf_spec(model.spec)
    if (type(model.schema) is not tuple or tuple(trainer["schema"]) != model.schema
            or model.class_property != trainer["class_property"]):
        raise ValueError("Smile RF model metadata differs from its audited trainer specification")
    if (projection["schema"] != trainer["schema"]
            or projection["trees"] != trainer["number_of_trees"]):
        raise ValueError("RF explanation schema or tree count differs from its trained model")
    return trainer


def local_ee_smile_rf_explain(args, env):
    """Project actual Smile forest values or preserve dry-run lineage only."""
    from .ee_process_adapters import _checked_args
    from .ee_smile_rf import PendingSmileRfModel, TrainedSmileRfModel
    from .ee_rf_validation_runtime import checked_model, model_schema
    from .ee_smile_rf_training import _dry_run_tracer
    from .ee_explanation_result import PendingRFExplanationResult, RuntimeRFExplanationResult
    from gee.rf_explanation_spec import (
        decode_explanation_spec, decode_native_explanation, project_explanation,
    )

    args = _checked_args(args, "local_ee_smile_rf_explain", {"model", "spec"})
    model = args["model"]
    if type(model) not in (PendingSmileRfModel, TrainedSmileRfModel):
        raise ValueError("RF explanation requires a direct trusted Smile RF trainer model")
    model = checked_model(model)
    model_schema(model)
    trainer_text = model.spec
    _precharge(args["spec"], trainer_text)
    projection = decode_explanation_spec(args["spec"])
    _validated_model_spec(model, projection)
    tracer = _dry_run_tracer(env)

    if type(model) is PendingSmileRfModel:
        if tracer is None or model.data_tracer is not tracer:
            raise ValueError("Pending RF explanation does not belong to this dry run")
        return PendingRFExplanationResult(args["spec"], model.traces, tracer)
    if tracer is not None:
        return PendingRFExplanationResult(args["spec"], data_tracer=tracer)

    native_text = _explain_jvm(model._java_model)
    envelope = decode_native_explanation(native_text, projection)
    value = project_explanation(envelope, projection)
    return RuntimeRFExplanationResult(value, args["spec"])
