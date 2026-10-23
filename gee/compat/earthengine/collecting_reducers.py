"""Finite, immutable Reducer.toList and Reducer.toCollection leaves."""
from __future__ import annotations

from dataclasses import dataclass

from . import collecting_reducer_results as results
from . import collecting_reducer_values as values
from .collecting_reducer_values import (
    MAX_COLLECTING_DEPTH,
    MAX_COLLECTING_INPUTS,
    MAX_COLLECTING_NAME_CHARS,
    MAX_COLLECTING_PROPERTIES,
    MAX_COLLECTING_ROWS,
    MAX_PUBLIC_BYTES,
    MAX_TRANSLATOR_WORK,
)
from .ir import fail, integer


COLLECTING_REDUCER_NAMES = frozenset({
    "Reducer.toList",
    "Reducer.toCollection",
})

_OUTPUT_NAMES = {
    "Reducer.toList": ("list",),
    "Reducer.toCollection": ("collection",),
}
_RESERVED_PROPERTY_NAMES = frozenset({".geo", ".id", "system:index"})


@dataclass(frozen=True, slots=True)
class CollectingReducerLeaf:
    """A detached, immutable reducer constructor and canonical parameters."""

    name: str
    tuple_size: int | None = None
    num_optional: int = 0
    property_names: tuple[str, ...] | None = None


def _property_names(translator, value) -> tuple[str, ...]:
    if type(value) is not list:
        fail("Reducer.toCollection propertyNames must be a list of 1 to 32 strings")
    if not 1 <= len(value) <= MAX_COLLECTING_INPUTS:
        fail("Reducer.toCollection propertyNames must contain 1 to 32 names")
    values._charge(translator, 1 + len(value), "Reducer.toCollection propertyNames scan")
    wire = [0]
    for name in value:
        values._text(translator, name, wire, "Reducer.toCollection property name",
                     MAX_COLLECTING_NAME_CHARS)
        if not name:
            fail("Reducer.toCollection property names cannot be empty")
        if name in _RESERVED_PROPERTY_NAMES:
            fail(f"Reducer.toCollection property name {name!r} is reserved")
    # Charge all text before hashing names or allocating their canonical tuple.
    values._charge(translator, len(value),
                   "Reducer.toCollection property-name uniqueness check")
    if len(set(value)) != len(value):
        fail("Reducer.toCollection propertyNames must be unique")
    return tuple(value)


def _validate_leaf(translator, leaf: CollectingReducerLeaf) -> tuple[int, tuple[str, ...]]:
    if type(leaf) is not CollectingReducerLeaf:
        fail("Expected an immutable collecting Reducer leaf")
    if type(leaf.name) is not str or leaf.name not in COLLECTING_REDUCER_NAMES:
        fail("Collecting Reducer leaf has an unsupported name")
    values._charge(translator, 1 + len(leaf.name),
                   "Collecting Reducer descriptor validation")
    if type(leaf.num_optional) is not int:
        fail("Collecting Reducer numOptional must be an integer")

    if leaf.name == "Reducer.toList":
        if leaf.property_names is not None:
            fail("Reducer.toList descriptor contains invalid propertyNames")
        if leaf.tuple_size is None:
            input_count = 1
        elif type(leaf.tuple_size) is int and 1 <= leaf.tuple_size <= MAX_COLLECTING_INPUTS:
            input_count = leaf.tuple_size
        else:
            fail("Reducer.toList tupleSize must be null or an integer from 1 to 32")
        if not 0 <= leaf.num_optional <= input_count:
            fail("Reducer.toList numOptional must be from 0 to its input count")
        return input_count, _OUTPUT_NAMES[leaf.name]

    if leaf.tuple_size is not None or type(leaf.property_names) is not tuple:
        fail("Reducer.toCollection descriptor has invalid parameters")
    names = leaf.property_names
    if not 1 <= len(names) <= MAX_COLLECTING_INPUTS:
        fail("Reducer.toCollection propertyNames must contain 1 to 32 names")
    values._charge(translator, 1 + len(names),
                   "Reducer.toCollection descriptor validation")
    wire = [0]
    for name in names:
        values._text(translator, name, wire, "Reducer.toCollection property name",
                     MAX_COLLECTING_NAME_CHARS)
        if not name:
            fail("Reducer.toCollection property names cannot be empty")
        if name in _RESERVED_PROPERTY_NAMES:
            fail(f"Reducer.toCollection property name {name!r} is reserved")
    values._charge(translator, len(names),
                   "Reducer.toCollection descriptor uniqueness check")
    if len(set(names)) != len(names):
        fail("Reducer.toCollection propertyNames must be unique")
    if not 0 <= leaf.num_optional <= len(names):
        fail("Reducer.toCollection numOptional must be from 0 to its input count")
    return len(names), _OUTPUT_NAMES[leaf.name]


def make_collecting_reducer(translator, name, args) -> CollectingReducerLeaf:
    """Build an immutable collecting reducer and reject unsupported arguments."""
    if type(name) is not str or name not in COLLECTING_REDUCER_NAMES:
        fail(f"Unsupported collecting Reducer constructor: {name}")
    if name == "Reducer.toList":
        translator.allowed(args, {"tupleSize", "numOptional"})
        tuple_size = args.get("tupleSize")
        if tuple_size is not None:
            tuple_size = integer(tuple_size, "Reducer.toList tupleSize", 1)
            if tuple_size > MAX_COLLECTING_INPUTS:
                fail("Reducer.toList tupleSize must be from 1 to 32")
        input_count = 1 if tuple_size is None else tuple_size
        num_optional = args.get("numOptional", 0)
        if num_optional is None:
            num_optional = 0
        num_optional = integer(num_optional, "Reducer.toList numOptional", 0)
        if num_optional > input_count:
            fail("Reducer.toList numOptional must be from 0 to its input count")
        leaf = CollectingReducerLeaf(name, tuple_size, num_optional, None)
    else:
        translator.allowed(args, {"propertyNames", "numOptional"})
        names = _property_names(translator, args.get("propertyNames"))
        num_optional = args.get("numOptional", 0)
        if num_optional is None:
            num_optional = 0
        num_optional = integer(num_optional, "Reducer.toCollection numOptional", 0)
        if num_optional > len(names):
            fail("Reducer.toCollection numOptional must be from 0 to its input count")
        leaf = CollectingReducerLeaf(name, None, num_optional, names)
    _validate_leaf(translator, leaf)
    return leaf


def describe_collecting_reducer(translator, leaf) -> tuple[int, tuple[str, ...]]:
    """Revalidate a descriptor and return its input arity and output names."""
    return _validate_leaf(translator, leaf)


def reduce_collecting_reducer(translator, leaf, records) -> list[tuple[str, object]]:
    """Apply a finite collecting leaf to owned, preflighted input records."""
    input_count, outputs = describe_collecting_reducer(translator, leaf)
    return results.reduce_records(translator, leaf, input_count, outputs, records)
