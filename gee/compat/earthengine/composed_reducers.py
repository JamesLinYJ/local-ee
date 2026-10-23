"""Reducer constructors backed by the closed composed-reducer descriptor."""
from __future__ import annotations

from .composed_reducer_spec import (
    MAX_REDUCER_INPUTS,
    MAX_REDUCER_NAME_CHARS,
    MAX_REDUCER_NODES,
    MAX_REDUCER_OUTPUTS,
    _COMPOSED_FUNCTIONS,
    ReducerSpec,
    ScalarReducerLeaf,
    _charge,
    _name,
    _spec,
    _tree_stats,
    as_reducer_spec,
    handles_composed_reducer,
    is_reducer_spec,
    normalize_reducer_spec,
    reducer_inputs,
    reducer_outputs,
    validate_reducer_spec,
)
from .ir import fail, integer


def invoke_composed_reducer(translator, name, arguments):
    """Build a reducer descriptor or return a fresh static output-name list."""
    if name not in _COMPOSED_FUNCTIONS:
        fail(f"Unsupported composed reducer operation: {name}")
    a = arguments
    if name == "Reducer.combine":
        translator.allowed(a, {"reducer1", "reducer2", "outputPrefix", "sharedInputs"})
        left = _spec(translator, a.get("reducer1"))
        right = _spec(translator, a.get("reducer2"))
        prefix = _name(translator, "" if a.get("outputPrefix") is None else a["outputPrefix"],
                       "Reducer.combine outputPrefix")
        shared = a.get("sharedInputs")
        if shared is None:
            shared = False
        if type(shared) is not bool:
            fail("Reducer.combine sharedInputs must be boolean or null")
        if shared and left.input_count != right.input_count:
            fail("Reducer.combine sharedInputs requires reducers with equal input counts")
        inputs = left.input_count if shared else left.input_count + right.input_count
        if inputs > MAX_REDUCER_INPUTS:
            fail("Composed Reducer supports at most 32 inputs")
        output_count = len(left.outputs) + len(right.outputs)
        if output_count > MAX_REDUCER_OUTPUTS:
            fail("Composed Reducer supports at most 256 outputs")
        output_work = output_count
        for item in right.outputs:
            if len(prefix) + len(item) > MAX_REDUCER_NAME_CHARS:
                fail("Reducer.combine output name exceeds the bounded length")
            output_work += len(prefix) + len(item)
        _charge(translator, output_work)
        outputs = left.outputs + tuple(prefix + item for item in right.outputs)
        spec = ReducerSpec(
            "combine", inputs, outputs, left=left, right=right,
            shared_inputs=shared, output_prefix=prefix,
        )
    elif name == "Reducer.group":
        translator.allowed(a, {"reducer", "groupField", "groupName"})
        child = _spec(translator, a.get("reducer"))
        field = integer(a.get("groupField", 0), "Reducer.group groupField", 0)
        inputs = child.input_count + 1
        if inputs > MAX_REDUCER_INPUTS:
            fail("Composed Reducer supports at most 32 inputs including group fields")
        if field >= inputs:
            fail("Reducer.group groupField is outside the reducer input arity")
        group_name = _name(
            translator, "group" if a.get("groupName") is None else a["groupName"],
            "Reducer.group groupName",
        )
        spec = ReducerSpec(
            "group", inputs, ("groups",), child=child,
            group_field=field, group_name=group_name,
        )
    elif name == "Reducer.setOutputs":
        translator.allowed(a, {"reducer", "outputs"})
        child = _spec(translator, a.get("reducer"))
        outputs = a.get("outputs")
        if type(outputs) is not list or len(outputs) != len(child.outputs):
            fail("Reducer.setOutputs requires one name or null per reducer output")
        if len(outputs) > MAX_REDUCER_OUTPUTS:
            fail("Reducer.setOutputs supports at most 256 outputs")
        _charge(translator, len(outputs))
        normalized = []
        for item in outputs:
            if item is None:
                normalized.append(None)
            else:
                normalized.append(_name(translator, item, "Reducer.setOutputs name"))
        selection = tuple(normalized)
        _charge(translator, len(selection))
        names = []
        for item in selection:
            if item:
                names.append(item)
        spec = ReducerSpec(
            "setOutputs", child.input_count, tuple(names),
            child=child, output_selection=selection,
        )
    else:
        translator.allowed(a, {"reducer"})
        reducer = _spec(translator, a.get("reducer"))
        _tree_stats(reducer, translator)
        _charge(translator, 1 + len(reducer.outputs))
        return list(reducer.outputs)

    _tree_stats(spec, translator)
    return spec
