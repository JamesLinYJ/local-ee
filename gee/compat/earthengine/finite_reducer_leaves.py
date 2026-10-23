"""Closed descriptors for additional finite table reducers, never raster IR."""
from __future__ import annotations

from dataclasses import dataclass

from .ir import fail


@dataclass(frozen=True)
class FiniteReducerLeaf:
    """No mutable arguments or executable payload enter a reducer tree."""

    name: str


def finite_leaf_outputs():
    from .finite_reducer_numeric import NUMERIC_REDUCER_OUTPUTS
    from .finite_reducer_discrete import DISCRETE_REDUCER_OUTPUTS

    return {**NUMERIC_REDUCER_OUTPUTS, **DISCRETE_REDUCER_OUTPUTS}


def handles_finite_reducer(name):
    return name.startswith("Reducer.") and name[8:] in finite_leaf_outputs()


def finite_leaf_inputs(name):
    return 0 if name == "countEvery" else 1


def validate_finite_leaf(translator, leaf, input_count, outputs):
    from .composed_reducer_spec import _charge

    if type(leaf) is not FiniteReducerLeaf or type(leaf.name) is not str:
        fail("Finite reducer leaf has invalid fields")
    if len(leaf.name) > 64:
        fail("Finite reducer leaf name exceeds its bounded length")
    if translator is not None:
        _charge(translator, 1 + len(leaf.name))
    expected = finite_leaf_outputs().get(leaf.name)
    if expected is None or input_count != finite_leaf_inputs(leaf.name) or outputs != expected:
        fail("Finite reducer leaf has invalid name, input arity or outputs")


def invoke_finite_reducer(translator, name, arguments):
    from .composed_reducer_spec import ReducerSpec, _tree_stats

    translator.allowed(arguments, set())
    suffix = name[8:]
    outputs = finite_leaf_outputs().get(suffix)
    if outputs is None:
        fail(f"Unsupported finite reducer: {name}")
    spec = ReducerSpec("leaf", finite_leaf_inputs(suffix), outputs, leaf=FiniteReducerLeaf(suffix))
    _tree_stats(spec, translator)
    return spec


def reduce_finite_leaf(translator, leaf, records):
    from .composed_reducer_spec import _charge
    from .finite_reducer_numeric import NUMERIC_REDUCER_OUTPUTS, reduce_numeric_leaf
    from .finite_reducer_discrete import DISCRETE_REDUCER_OUTPUTS, reduce_discrete_leaf

    outputs = finite_leaf_outputs().get(leaf.name)
    validate_finite_leaf(translator, leaf, finite_leaf_inputs(leaf.name), outputs)
    _charge(translator, 1 + len(records))
    values = [None] * len(records) if leaf.name == "countEvery" else [row[0] for row in records]
    if leaf.name in NUMERIC_REDUCER_OUTPUTS:
        return reduce_numeric_leaf(translator, leaf.name, values)
    if leaf.name in DISCRETE_REDUCER_OUTPUTS:
        return reduce_discrete_leaf(translator, leaf.name, values)
    fail("Unsupported finite reducer leaf")
