"""Closed numeric reducer plans shared by raster and array adapters."""
from __future__ import annotations

from .composed_reducer_spec import (
    MAX_REDUCER_NAME_CHARS,
    MAX_REDUCER_OUTPUTS,
    ReducerSpec,
    ScalarReducerLeaf,
    validate_reducer_spec,
)
from .finite_reducer_leaves import FiniteReducerLeaf
from .ir import Reducer, fail


MAX_NUMERIC_REDUCER_WORK = 50_000

_LEGACY_OUTPUTS = {
    "sum": ("sum",),
    "mean": ("mean",),
    "min": ("min",),
    "max": ("max",),
    "count": ("count",),
    "first": ("first",),
    "last": ("last",),
    "median": ("median",),
    "sd": ("stdDev",),
}
_FINITE_OUTPUTS = {
    "product": ("product",),
    "stdDev": ("stdDev",),
    "variance": ("variance",),
    "sampleVariance": ("variance",),
    "minMax": ("min", "max"),
}
_SCALAR_OPERATIONS = {name: name for name in _LEGACY_OUTPUTS}
_SCALAR_OPERATIONS["sd"] = "sd"
_FINITE_OPERATIONS = {
    "product": ("product",),
    "stdDev": ("stdDev",),
    "variance": ("variance",),
    "sampleVariance": ("sampleVariance",),
    "minMax": ("min", "max"),
}


def _charge(translator, amount: int) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or amount < 0 or amount > MAX_NUMERIC_REDUCER_WORK
            or steps + amount > MAX_NUMERIC_REDUCER_WORK):
        fail("Raster numeric reducer exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _legacy_spec(translator, value: Reducer) -> ReducerSpec:
    if type(value) is not Reducer:
        fail("Raster numeric reduction requires a legacy Reducer or closed ReducerSpec")
    name, unweighted = value.name, value.unweighted
    if type(name) is not str or type(unweighted) is not bool:
        fail("Legacy numeric Reducer has invalid fields")
    if len(name) > MAX_REDUCER_NAME_CHARS:
        fail("Legacy numeric Reducer name exceeds its bounded length")
    _charge(translator, 1 + len(name))
    if unweighted:
        fail("Unweighted numeric raster reducers are unsupported")
    if name in _LEGACY_OUTPUTS:
        return ReducerSpec("leaf", 1, _LEGACY_OUTPUTS[name], leaf=ScalarReducerLeaf(name))
    if name in _FINITE_OUTPUTS:
        return ReducerSpec("leaf", 1, _FINITE_OUTPUTS[name], leaf=FiniteReducerLeaf(name))
    fail(f"Unsupported numeric raster Reducer: {name}")


def _operation_count(spec: ReducerSpec) -> tuple[int, int]:
    """Validate the allowed plan shape and count emitted/intermediate slots."""
    if spec.kind == "leaf":
        if spec.input_count != 1:
            fail("Numeric raster reducers require exactly one input per leaf")
        if type(spec.leaf) is ScalarReducerLeaf:
            name = spec.leaf.name
            if name not in _SCALAR_OPERATIONS:
                fail(f"Unsupported scalar numeric raster reducer: {name}")
            return len(_LEGACY_OUTPUTS[name]), len(_LEGACY_OUTPUTS[name])
        if type(spec.leaf) is FiniteReducerLeaf:
            name = spec.leaf.name
            if name not in _FINITE_OPERATIONS:
                fail(f"Non-numeric finite Reducer is unsupported in raster reduction: {name}")
            count = len(_FINITE_OPERATIONS[name])
            return count, count
        fail("Numeric raster Reducer leaves must be scalar numeric reducers")
    if spec.kind == "combine":
        if spec.shared_inputs is not True:
            fail("Numeric raster Reducer.combine requires sharedInputs=true")
        left_count, left_slots = _operation_count(spec.left)
        right_count, right_slots = _operation_count(spec.right)
        if left_count + right_count != len(spec.outputs):
            fail("Numeric raster Reducer.combine has an invalid output plan")
        return left_count + right_count, left_slots + right_slots + left_count + right_count
    if spec.kind == "setOutputs":
        child_count, child_slots = _operation_count(spec.child)
        if (type(spec.output_selection) is not tuple
                or len(spec.output_selection) != child_count):
            fail("Numeric raster Reducer.setOutputs has an invalid output plan")
        selected = sum(item is not None and item != "" for item in spec.output_selection)
        if selected != len(spec.outputs):
            fail("Numeric raster Reducer.setOutputs has an invalid output plan")
        return selected, child_slots + child_count
    if spec.kind in {"group", "repeat", "forEach"}:
        fail(f"Numeric raster reducers do not support {spec.kind} descriptors")
    fail(f"Unsupported numeric raster Reducer descriptor: {spec.kind}")


def _operations(spec: ReducerSpec) -> list[str]:
    if spec.kind == "leaf":
        if type(spec.leaf) is ScalarReducerLeaf:
            return [_SCALAR_OPERATIONS[spec.leaf.name]] * len(_LEGACY_OUTPUTS[spec.leaf.name])
        return list(_FINITE_OPERATIONS[spec.leaf.name])
    if spec.kind == "combine":
        return _operations(spec.left) + _operations(spec.right)
    child = _operations(spec.child)
    return [operation for operation, selected in zip(child, spec.output_selection)
            if selected is not None and selected != ""]


def numeric_outputs(translator, reducer) -> tuple[tuple[str, str], ...]:
    """Return validated ``(output_name, operation)`` pairs for one-input numeric reducers.

    Only scalar numeric leaves, shared-input combines, and output-selection wrappers
    are representable. The full descriptor and all derived names are charged before
    the emitted operation vector is allocated.
    """
    if type(reducer) is Reducer:
        spec = _legacy_spec(translator, reducer)
    elif type(reducer) is ReducerSpec:
        spec = reducer
    else:
        fail("Raster numeric reduction requires a legacy Reducer or closed ReducerSpec")

    validate_reducer_spec(spec, translator)
    if type(spec.input_count) is not int or spec.input_count != 1:
        fail("Numeric raster reducers require exactly one input")
    output_slots, intermediate_slots = _operation_count(spec)
    if (not 1 <= output_slots <= MAX_REDUCER_OUTPUTS
            or len(spec.outputs) != output_slots):
        fail("Numeric raster reducers require at least one and at most 256 outputs")

    output_chars = 0
    seen_names = set()
    for output in spec.outputs:
        if type(output) is not str or not output or len(output) > MAX_REDUCER_NAME_CHARS:
            fail("Numeric raster reducer output names must be nonempty bounded strings")
        if output in seen_names:
            fail("Numeric raster reducer output names must be unique")
        seen_names.add(output)
        output_chars += len(output)

    # The composed validator already precharges every descriptor and every
    # combine-prefix concatenation. Reserve the operation walk and final names
    # before producing any output list or raster band-name concatenation.
    _charge(translator, intermediate_slots + output_slots + output_chars)
    operations = _operations(spec)
    if len(operations) != len(spec.outputs):
        fail("Numeric raster reducer output plan does not match its descriptor")
    return tuple(zip(spec.outputs, operations))
