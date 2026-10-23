"""Closed dispatch for parameterized finite statistical reducer families.

These leaves participate in the existing bounded reducer tree. They do not
authorize raster, sampled-table, weighted or arbitrary Python execution.
"""
from __future__ import annotations

from . import collecting_reducers, correlation_reducers, covariance_reducers, histogram_reducers
from .collecting_reducers import CollectingReducerLeaf
from .correlation_reducers import CorrelationReducerLeaf
from .covariance_reducers import CovarianceReducerLeaf
from .histogram_reducers import HistogramReducerLeaf
from .ir import fail


StatisticalReducerLeaf = (
    CollectingReducerLeaf | CorrelationReducerLeaf | CovarianceReducerLeaf | HistogramReducerLeaf
)
_FAMILIES = (
    (collecting_reducers, "collecting", CollectingReducerLeaf),
    (correlation_reducers, "correlation", CorrelationReducerLeaf),
    (covariance_reducers, "covariance", CovarianceReducerLeaf),
    (histogram_reducers, "histogram", HistogramReducerLeaf),
)
_BY_NAME = {
    name: (module, prefix)
    for module, prefix, _ in _FAMILIES
    for name in getattr(module, prefix.upper() + "_REDUCER_NAMES")
}
_BY_TYPE = {leaf_type: (module, prefix) for module, prefix, leaf_type in _FAMILIES}
STATISTICAL_REDUCER_NAMES = frozenset(_BY_NAME)


def is_statistical_leaf(leaf):
    return type(leaf) in _BY_TYPE


def _family(leaf):
    family = _BY_TYPE.get(type(leaf))
    if family is None:
        fail("Expected a closed finite statistical Reducer leaf")
    return family


class _MetadataBudget:
    """Even metadata-only queries retain the standard bounded work budget."""

    steps = 0


def describe_statistical_leaf(translator, leaf):
    module, prefix = _family(leaf)
    if translator is None:
        translator = _MetadataBudget()
    return getattr(module, f"describe_{prefix}_reducer")(translator, leaf)


def validate_statistical_leaf(translator, leaf, input_count, outputs):
    expected = describe_statistical_leaf(translator, leaf)
    if expected != (input_count, outputs):
        fail("Finite statistical Reducer has invalid input arity or output names")


def invoke_statistical_reducer(translator, name, arguments):
    from .composed_reducer_spec import ReducerSpec

    family = _BY_NAME.get(name)
    if family is None:
        fail(f"Unsupported finite statistical Reducer: {name}")
    module, prefix = family
    leaf = getattr(module, f"make_{prefix}_reducer")(translator, name, arguments)
    inputs, outputs = describe_statistical_leaf(translator, leaf)
    return ReducerSpec("leaf", inputs, outputs, leaf=leaf)


def reduce_statistical_leaf(translator, leaf, records):
    module, prefix = _family(leaf)
    return getattr(module, f"reduce_{prefix}_reducer")(translator, leaf, records)
