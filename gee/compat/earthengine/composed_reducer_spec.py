"""Closed immutable reducer descriptors and bounded tree validation."""
from __future__ import annotations

from dataclasses import dataclass

from .ir import Reducer, fail, integer
from .table_reducers import MAX_TABLE_INPUTS, TableReducer
from .finite_reducer_leaves import FiniteReducerLeaf


MAX_REDUCER_NODES = 64
MAX_REDUCER_DEPTH = 16
MAX_REDUCER_INPUTS = MAX_TABLE_INPUTS
MAX_REDUCER_OUTPUTS = 256
MAX_REDUCER_NAME_CHARS = 10_000

_SCALAR_OUTPUTS = {
    "sum": "sum",
    "mean": "mean",
    "min": "min",
    "max": "max",
    "count": "count",
    "first": "first",
    "last": "last",
    "median": "median",
    "sd": "stdDev",
}
_COMPOSED_FUNCTIONS = frozenset({
    "Reducer.combine", "Reducer.group", "Reducer.setOutputs", "Reducer.getOutputs",
    "Reducer.repeat", "Reducer.forEach",
})


@dataclass(frozen=True)
class ScalarReducerLeaf:
    """A detached scalar leaf; mutable IR Reducer objects never enter a spec."""

    name: str


@dataclass(frozen=True)
class ReducerSpec:
    """An immutable, closed reducer tree; it never represents a raster kernel."""

    kind: str
    input_count: int
    outputs: tuple[str, ...]
    leaf: ScalarReducerLeaf | TableReducer | FiniteReducerLeaf | None = None
    child: "ReducerSpec | None" = None
    left: "ReducerSpec | None" = None
    right: "ReducerSpec | None" = None
    shared_inputs: bool = False
    output_prefix: str = ""
    group_field: int = 0
    group_name: str = "group"
    output_selection: tuple[str | None, ...] | None = None
    repeat_count: int | None = None
    for_each_names: tuple[str, ...] | None = None


def handles_composed_reducer(name):
    return name in _COMPOSED_FUNCTIONS


def is_reducer_spec(value):
    return type(value) is ReducerSpec


def _charge(translator, amount):
    if amount < 0 or translator.steps + amount > 50_000:
        fail("Composed reducers exceed the shared 50000-step compilation work budget")
    translator.steps += amount


def _name(translator, value, label, allow_empty=True):
    if type(value) is not str or (not allow_empty and not value):
        fail(f"{label} must be a string")
    if len(value) > MAX_REDUCER_NAME_CHARS:
        fail(f"{label} exceeds the bounded reducer name length")
    _charge(translator, 1 + len(value))
    return value


def _leaf(translator, value):
    if type(value) is Reducer:
        # Snapshot mutable IR fields before building the closed descriptor.
        name, unweighted = value.name, value.unweighted
        if type(name) is not str or type(unweighted) is not bool:
            fail("Composed Reducer scalar leaf has invalid fields")
        if len(name) > MAX_REDUCER_NAME_CHARS:
            fail("Composed Reducer scalar leaf name is too long")
        _charge(translator, 1 + len(name))
        if unweighted:
            fail("Unweighted reducer inputs are unsupported in bounded table reductions")
        if name not in _SCALAR_OUTPUTS:
            fail(f"Composed reducers do not support scalar reducer {name}")
        scalar = ScalarReducerLeaf(name)
        return ReducerSpec("leaf", 1, (_SCALAR_OUTPUTS[name],), leaf=scalar)
    if type(value) is TableReducer:
        name, num_x, num_y = value.name, value.num_x, value.num_y
        if type(name) is not str or type(num_x) is not int or type(num_y) is not int:
            fail("Composed Reducer regression leaf has invalid fields")
        if len(name) > MAX_REDUCER_NAME_CHARS:
            fail("Composed Reducer regression leaf name is too long")
        _charge(translator, 1 + len(name))
        if name == "linearFit":
            if (num_x, num_y) != (1, 1):
                fail("Composed Reducer linearFit leaf must have one x and one y input")
            outputs = ("scale", "offset")
        elif name == "linearRegression":
            if num_x < 1 or num_y < 1:
                fail("Composed Reducer regression input arity is invalid")
            outputs = ("coefficients", "residuals")
        else:
            fail(f"Composed reducers do not support table reducer {name}")
        inputs = num_x + num_y
        if not 1 <= inputs <= MAX_REDUCER_INPUTS:
            fail("Composed reducer input arity must be between 1 and 32")
        return ReducerSpec("leaf", inputs, outputs, leaf=value)
    fail("Expected a supported scalar or regression Reducer")


def _tree_stats(spec, translator=None):
    """Lazily import the validator to keep descriptor types dependency-light."""
    from .composed_reducer_validation import validate_tree

    return validate_tree(spec, translator)



def normalize_reducer_spec(translator, value):
    """Normalize a reducer and return its validated descriptor node count."""
    if type(value) is ReducerSpec:
        return value, _tree_stats(value, translator)
    spec = _leaf(translator, value)
    return spec, _tree_stats(spec, translator)


def _spec(translator, value):
    return normalize_reducer_spec(translator, value)[0]


def as_reducer_spec(translator, value):
    """Normalize a supported legacy leaf or validate a composed descriptor."""
    return normalize_reducer_spec(translator, value)[0]


def validate_reducer_spec(spec, translator=None):
    """Preflight the entire descriptor and return its occurrence node count."""
    return _tree_stats(spec, translator)


def reducer_inputs(value):
    """Return the bounded input arity of an existing or composed Reducer."""
    if type(value) is ReducerSpec:
        _tree_stats(value)
        return value.input_count
    if type(value) in (TableReducer, Reducer):
        spec = _leaf(_NullTranslator(), value)
        _tree_stats(spec)
        return spec.input_count
    fail("Expected a supported scalar, regression, or composed Reducer")


def reducer_outputs(value):
    """Return output names after validating the entire descriptor."""
    if type(value) is not ReducerSpec:
        value = _leaf(_NullTranslator(), value)
    _tree_stats(value)
    return tuple(value.outputs)


class _NullTranslator:
    """Budget seam for static reducer metadata queries without a translator."""

    steps = 0
