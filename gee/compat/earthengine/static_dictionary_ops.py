"""Finite static Dictionary algorithms from the pinned Earth Engine SDK.

Where the SDK metadata gives no collision rule, this adapter uses explicit
local policies: duplicate fromLists keys keep the last value; rename requires
all source keys to exist and rejects duplicate destinations; overwrite=True
replaces a pre-existing destination. These choices do not claim Google parity.
"""
from __future__ import annotations

import json
import math

import numpy as np

from .array_core import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray
from .geometry_values import GEOMETRY_TYPES, decode_geometry
from .ir import Function, fail, integer
from .static_dictionary_values import (
    MAX_STATIC_BYTES,
    MAX_STATIC_VALUES,
    _array_list_bytes,
    _measure,
    charge,
    clone_entries,
    clone_value,
    measure_entries,
    natural_keys,
    require_dictionary,
    require_string,
    require_string_list,
)


DICTIONARY_EXTRA_FUNCTIONS = frozenset({
    "Dictionary.combine", "Dictionary.fromLists", "Dictionary.rename",
    "Dictionary.size", "Dictionary.map", "Dictionary.toArray",
    "Dictionary.getNumber", "Dictionary.getString", "Dictionary.getArray",
    "Dictionary.getGeometry",
})


_ARGUMENTS = {
    "Dictionary.combine": ({"first", "second"}, {"overwrite"}),
    "Dictionary.fromLists": ({"keys", "values"}, set()),
    "Dictionary.rename": ({"dictionary", "from", "to"}, {"overwrite"}),
    "Dictionary.size": ({"dictionary"}, set()),
    "Dictionary.map": ({"dictionary", "baseAlgorithm"}, set()),
    "Dictionary.toArray": ({"dictionary"}, {"keys", "axis"}),
    "Dictionary.getNumber": ({"dictionary", "key"}, set()),
    "Dictionary.getString": ({"dictionary", "key"}, set()),
    "Dictionary.getArray": ({"dictionary", "key"}, set()),
    "Dictionary.getGeometry": ({"dictionary", "key"}, set()),
}


def _arguments(translator, name, arguments):
    required, optional = _ARGUMENTS[name]
    translator.allowed(arguments, required | optional)
    missing = required - arguments.keys()
    if missing:
        fail(f"{name} requires {', '.join(sorted(missing))}")


def _boolean(value, label, default):
    if value is None:
        return default
    if type(value) is not bool:
        fail(f"{label} must be a boolean")
    return value


def _dictionary(translator, value, label="dictionary"):
    require_dictionary(translator, value, label)
    return value


def _copy_plan(translator, entries):
    copy_work, _ = measure_entries(translator, entries)
    charge(translator, copy_work)
    return clone_entries(entries)


def _combine(translator, a):
    first = _dictionary(translator, a["first"], "first")
    second = _dictionary(translator, a["second"], "second")
    overwrite = _boolean(a.get("overwrite"), "Dictionary.combine overwrite", True)
    charge(translator, len(first) + len(second))
    plan = [(key, value) for key, value in first.items() if value is not None]
    positions = {key: index for index, (key, _) in enumerate(plan)}
    for key, value in second.items():
        if value is None:
            continue
        if key not in positions:
            positions[key] = len(plan)
            plan.append((key, value))
        elif overwrite:
            plan[positions[key]] = (key, value)
    return _copy_plan(translator, plan)


def _from_lists(translator, a):
    keys, values = a["keys"], a["values"]
    require_string_list(translator, keys, "Dictionary.fromLists keys")
    if type(values) is not list or len(values) > MAX_STATIC_VALUES:
        fail("Dictionary.fromLists values must be a list of at most 10000 values")
    _measure(translator, values)
    if len(keys) != len(values):
        fail("Dictionary.fromLists keys and values must have equal lengths")
    charge(translator, len(keys))
    charge(translator, sum(len(key) for key in keys))
    positions = {}
    plan = []
    for key, value in zip(keys, values):
        index = positions.get(key)
        if index is None:
            positions[key] = len(plan)
            plan.append((key, value))
        else:
            # Dictionary construction follows ordinary last-value-wins mapping
            # semantics while retaining the first insertion position.
            plan[index] = (key, value)
    return _copy_plan(translator, plan)


def _rename(translator, a):
    dictionary = _dictionary(translator, a["dictionary"])
    sources, targets = a["from"], a["to"]
    require_string_list(translator, sources, "Dictionary.rename from")
    require_string_list(translator, targets, "Dictionary.rename to")
    if len(sources) != len(targets):
        fail("Dictionary.rename from and to lists must have equal lengths")
    overwrite = _boolean(a.get("overwrite"), "Dictionary.rename overwrite", False)
    charge(translator, len(dictionary) + len(sources) + len(targets))
    charge(translator, sum(len(key) for key in sources) + sum(len(key) for key in targets))
    if len(set(sources)) != len(sources):
        fail("Dictionary.rename source keys must be unique")
    if len(set(targets)) != len(targets):
        fail("Dictionary.rename destination keys must be unique")
    missing = [key for key in sources if key not in dictionary]
    if missing:
        fail(f"Dictionary.rename key does not exist: {missing[0]!r}")
    source_set = set(sources)
    conflicts = [key for key in targets if key in dictionary and key not in source_set]
    if conflicts and not overwrite:
        fail(f"Dictionary.rename destination already exists: {conflicts[0]!r}")
    renames = dict(zip(sources, targets))
    plan = [(key, value) for key, value in dictionary.items()
            if key not in source_set and key not in conflicts]
    plan.extend((renames[key], dictionary[key]) for key in sources)
    return _copy_plan(translator, plan)


def _validate_map_function(translator, function):
    if (type(function) is not Function or type(function.names) is not list
            or len(function.names) != 2
            or any(type(name) is not str for name in function.names)):
        fail("Dictionary.map requires a serialized two-argument Function")
    for name in function.names:
        require_string(translator, name, "Dictionary.map argument name")
    charge(translator, len(function.names))
    charge(translator, sum(len(name) for name in function.names))
    if len(set(function.names)) != 2:
        fail("Dictionary.map argument names must be unique")
    if type(function.env) is not dict:
        fail("Dictionary.map closure must be a static environment")
    require_dictionary(translator, function.env, "Dictionary.map closure")
    return function


def _map(translator, a):
    dictionary = _dictionary(translator, a["dictionary"])
    function = _validate_map_function(translator, a["baseAlgorithm"])
    charge(translator, len(dictionary) + 1)
    result = {}
    payload = 2
    for key, value in dictionary.items():
        charge(translator, 2 + len(function.env))
        environment = {**function.env, **dict(zip(function.names, (key, value)))}
        mapped = translator.evaluate(function.body, environment, depth=1)
        if mapped is None:
            continue  # Dictionary.map's documented null result drops the key.
        entry_overhead = 2 if not result else 4
        key_work, key_bytes = _measure(
            translator, key,
            byte_limit=max(0, MAX_STATIC_BYTES - payload - entry_overhead),
        )
        value_work, value_bytes = _measure(
            translator, mapped,
            byte_limit=max(0, MAX_STATIC_BYTES - payload - entry_overhead - key_bytes),
        )
        if payload + entry_overhead + key_bytes + value_bytes > MAX_STATIC_BYTES:
            fail("Computed Dictionary exceeds 1 MB")
        charge(translator, key_work + value_work + 1)
        result[key] = clone_value(mapped)
        payload += entry_overhead + key_bytes + value_bytes
    return result


def _to_array(translator, a):
    dictionary = _dictionary(translator, a["dictionary"])
    keys = a.get("keys")
    if keys is None:
        keys = natural_keys(translator, dictionary)
    else:
        require_string_list(translator, keys, "Dictionary.toArray keys")
        charge(translator, len(keys))
        charge(translator, sum(len(key) for key in keys))
    axis = a.get("axis")
    axis = 0 if axis is None else integer(axis, "Dictionary.toArray axis")
    charge(translator, len(keys))
    selected = []
    for key in keys:
        if key not in dictionary:
            fail(f"Dictionary.toArray key does not exist: {key!r}")
        selected.append(dictionary[key])
    if not selected:
        if axis != 0:
            fail("Dictionary.toArray axis must be 0 for an empty value list")
        charge(translator, 1)
        result = StaticArray(np.empty((0,), dtype=np.float64))
        result.data.flags.writeable = False
        return result

    charge(translator, len(selected))
    arrays = type(selected[0]) is StaticArray
    source_shape = selected[0].data.shape if arrays else ()
    rank = len(source_shape)
    dtype = selected[0].data.dtype if arrays else (
        np.dtype("int64") if type(selected[0]) is int else np.dtype("float64")
    )
    for value in selected:
        if arrays:
            if type(value) is not StaticArray or value.data.shape != source_shape:
                fail("Dictionary.toArray ee.Array values must have matching shapes")
            value_dtype = value.data.dtype
        else:
            if type(value) not in (int, float):
                if type(value) is StaticArray:
                    fail("Dictionary.toArray cannot mix ee.Array and scalar values")
                fail("Dictionary.toArray requires numeric values")
            value_dtype = np.dtype("int64") if type(value) is int else np.dtype("float64")
        dtype = np.result_type(dtype, value_dtype)
    # The pinned Dictionary.toArray metadata documents an insertion axis but
    # does not promise negative-index normalization. Keep the finite adapter's
    # supported surface explicit instead of inferring NumPy behavior here.
    normalized_axis = axis
    if normalized_axis < 0 or normalized_axis > rank:
        fail("Dictionary.toArray axis is outside the output rank")
    output_shape = (*source_shape[:normalized_axis], len(selected),
                    *source_shape[normalized_axis:])
    output_rank = rank + 1
    output_cells = math.prod(output_shape)
    if output_rank > MAX_ARRAY_RANK or output_cells > MAX_ARRAY_CELLS:
        fail("Dictionary.toArray result exceeds the Array rank/cell budget")
    input_cells = len(selected) * math.prod(source_shape) if arrays else len(selected)
    charge(translator, input_cells + output_cells + len(selected) + output_rank)
    numeric_bytes = 0
    if arrays:
        for value in selected:
            for scalar in value.data.flat:
                numeric_bytes += len(json.dumps(dtype.type(scalar).item(), allow_nan=False))
    else:
        for value in selected:
            numeric_bytes += len(json.dumps(dtype.type(value).item(), allow_nan=False))
    payload = _array_list_bytes(output_shape) + numeric_bytes
    if payload > MAX_STATIC_BYTES:
        fail("Dictionary.toArray result exceeds 1 MB")
    # Reserve the NumPy allocation and materialization before running the kernel.
    if arrays:
        data = np.stack([value.data for value in selected], axis=normalized_axis)
    else:
        data = np.asarray(selected, dtype=dtype)
    data.flags.writeable = False
    return StaticArray(data)


def _typed_get(translator, name, a):
    dictionary = _dictionary(translator, a["dictionary"])
    require_string(translator, a["key"], f"{name} key")
    key = a["key"]
    charge(translator, len(key))
    if key not in dictionary:
        fail(f"{name}: dictionary does not contain key: {key!r}")
    value = dictionary[key]
    if name == "Dictionary.getNumber":
        if type(value) not in (int, float):
            fail("Dictionary.getNumber requires a numeric value")
        return value
    if name == "Dictionary.getString":
        if type(value) is not str:
            fail("Dictionary.getString requires a string value")
        return value
    if name == "Dictionary.getArray":
        if type(value) is not StaticArray:
            fail("Dictionary.getArray requires a static ee.Array value")
        work, _ = _measure(translator, value)
        charge(translator, work)
        return clone_value(value)
    if name == "Dictionary.getGeometry":
        kind = value.get("type") if type(value) is dict else None
        if type(kind) is not str or kind not in GEOMETRY_TYPES:
            fail("Dictionary.getGeometry requires a GeoJSON geometry value")
        work, _ = _measure(translator, value)
        charge(translator, work)
        geometry = decode_geometry(value)
        # The translator already decodes static Geometry values. Rechecking the
        # owned result catches malformed direct IR fixtures before JSON output.
        _measure(translator, geometry)
        return geometry
    raise AssertionError(name)


def invoke_dictionary_extra(translator, name, arguments):
    """Evaluate one explicitly supported finite static Dictionary algorithm."""
    if name not in DICTIONARY_EXTRA_FUNCTIONS:
        fail(f"Unsupported static Dictionary operation: {name}")
    _arguments(translator, name, arguments)
    if name == "Dictionary.combine":
        return _combine(translator, arguments)
    if name == "Dictionary.fromLists":
        return _from_lists(translator, arguments)
    if name == "Dictionary.rename":
        return _rename(translator, arguments)
    if name == "Dictionary.size":
        return len(_dictionary(translator, arguments["dictionary"]))
    if name == "Dictionary.map":
        return _map(translator, arguments)
    if name == "Dictionary.toArray":
        return _to_array(translator, arguments)
    return _typed_get(translator, name, arguments)
