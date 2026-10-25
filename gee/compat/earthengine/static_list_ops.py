"""Bounded, owned operations for finite static Earth Engine Lists."""
from __future__ import annotations

import math

from .array_core import MAX_ARRAY_CELLS, MAX_ARRAY_RANK, StaticArray, charge_array
from .geometry_components import own_component_geometry_bounded
from .geometry_values import GEOMETRY_TYPES, GeometryValue
from .ir import fail
from .static_equality import static_equal
from .static_list_text import join_values


MAX_LIST_VALUES = 10_000
LIST_EXTRA_FUNCTIONS = frozenset({
    "List.containsAll", "List.equals", "List.frequency", "List.indexOf",
    "List.indexOfSublist", "List.lastIndexOfSubList", "List.insert",
    "List.remove", "List.removeAll", "List.replace", "List.replaceAll",
    "List.rotate", "List.splice", "List.join", "List.getNumber",
    "List.getString", "List.getArray", "List.getGeometry",
})

_ARGUMENTS = {
    "List.containsAll": {"list", "other"},
    "List.equals": {"list", "other"},
    "List.frequency": {"list", "element"},
    "List.indexOf": {"list", "element"},
    "List.indexOfSublist": {"list", "target"},
    "List.lastIndexOfSubList": {"list", "target"},
    "List.insert": {"list", "index", "element"},
    "List.remove": {"list", "element"},
    "List.removeAll": {"list", "other"},
    "List.replace": {"list", "oldval", "newval"},
    "List.replaceAll": {"list", "oldval", "newval"},
    "List.rotate": {"list", "distance"},
    "List.splice": {"list", "start", "count", "other"},
    "List.join": {"list", "separator"},
    "List.getNumber": {"list", "index"},
    "List.getString": {"list", "index"},
    "List.getArray": {"list", "index"},
    "List.getGeometry": {"list", "index"},
}


def _required(args, key, name):
    if key not in args:
        fail(f"{name} requires {key}")
    return args[key]


def _list(translator, value, label):
    if type(value) is not list:
        fail(f"{label} requires a static List")
    if len(value) > MAX_LIST_VALUES:
        fail(f"{label} exceeds {MAX_LIST_VALUES} values")
    # Self-equality is the shared recursive static-value validator. It rejects
    # dynamic IR, opaque models, cycles, non-finite values and unsupported types.
    static_equal(translator, value, value, exact_integers=True)
    return value


def _raw_list(value, label):
    if type(value) is not list:
        fail(f"{label} requires a static List")
    if len(value) > MAX_LIST_VALUES:
        fail(f"{label} exceeds {MAX_LIST_VALUES} values")
    return value


def _value(translator, value):
    static_equal(translator, value, value, exact_integers=True)
    return value


def _copy(translator, values, extra=0):
    size = len(values) + extra
    if size > MAX_LIST_VALUES:
        fail(f"Computed List exceeds {MAX_LIST_VALUES} values")
    charge_array(translator, max(1, size))


def _integer(value, label, *, minimum=None):
    if type(value) not in (int, float):
        fail(f"{label} must be an integer")
    if type(value) is float and not math.isfinite(value):
        fail(f"{label} must be an integer")
    if abs(value) > 2**53 or int(value) != value:
        fail(f"{label} must be an exact integer within the Float64 domain")
    result = int(value)
    if minimum is not None and result < minimum:
        fail(f"{label} must be >= {minimum}")
    return result


def _position(index, length, label, *, insertion=False):
    index = _integer(index, label)
    if index < 0:
        index += length
    upper = length if insertion else length - 1
    if index < 0 or index > upper:
        fail(f"{label} is outside the List bounds")
    return index


def _find(translator, values, element, start=0, stop=None):
    stop = len(values) if stop is None else stop
    for index in range(start, stop):
        if static_equal(translator, values[index], element):
            return index
    return -1


def _sublist_match(translator, values, target, start):
    return all(static_equal(translator, values[start + offset], item)
               for offset, item in enumerate(target))


def _matches(translator, value, values):
    return _find(translator, values, value) >= 0


def invoke_list_extra(translator, name, args):
    """Evaluate one pinned static List operation with shared equality/work rules."""
    if name not in LIST_EXTRA_FUNCTIONS:
        fail(f"Unsupported Earth Engine algorithm: {name}")
    translator.allowed(args, _ARGUMENTS[name])

    if name == "List.equals":
        values = _raw_list(_required(args, "list", name), name)
        other = _raw_list(_required(args, "other", name), name)
        return static_equal(translator, values, other, exact_integers=True)

    values = _list(translator, _required(args, "list", name), name)
    if name == "List.join":
        separator = args.get("separator", "")
        _value(translator, separator)
        return join_values(translator, values, separator)

    if name.startswith("List.get") and name in {
        "List.getNumber", "List.getString", "List.getArray", "List.getGeometry",
    }:
        index = _position(_required(args, "index", name), len(values), f"{name} index")
        result = values[index]
        expected = {
            "List.getNumber": lambda item: type(item) is int or (type(item) is float and math.isfinite(item)),
            "List.getString": lambda item: type(item) is str,
            "List.getArray": lambda item: type(item) is StaticArray,
            "List.getGeometry": lambda item: type(item) in (dict, GeometryValue) and item.get("type") in GEOMETRY_TYPES,
        }[name]
        if not expected(result):
            fail(f"{name} value at index {index} has the wrong type")
        if name == "List.getArray":
            data = result.data
            if (data.size > MAX_ARRAY_CELLS or data.ndim > MAX_ARRAY_RANK
                    or data.dtype.kind not in "iuf"):
                fail("List.getArray requires a bounded static Array")
        if name == "List.getGeometry":
            result = own_component_geometry_bounded(translator, result)
        return result

    if name == "List.containsAll":
        other = _list(translator, _required(args, "other", name), name)
        return all(_matches(translator, item, values) for item in other)
    if name in {"List.frequency", "List.indexOf"}:
        element = _value(translator, _required(args, "element", name))
        frequency = 0
        for index, item in enumerate(values):
            if static_equal(translator, item, element):
                if name == "List.indexOf":
                    return index
                frequency += 1
        return frequency if name == "List.frequency" else -1
    if name in {"List.indexOfSublist", "List.lastIndexOfSubList"}:
        target = _list(translator, _required(args, "target", name), name)
        if not target:
            return 0 if name == "List.indexOfSublist" else len(values)
        starts = range(0, len(values) - len(target) + 1)
        if name == "List.lastIndexOfSubList":
            starts = range(len(values) - len(target), -1, -1)
        for start in starts:
            if _sublist_match(translator, values, target, start):
                return start
        return -1
    if name == "List.insert":
        index = _position(_required(args, "index", name), len(values), "List.insert index", insertion=True)
        element = _value(translator, _required(args, "element", name))
        _copy(translator, values, 1)
        result = []
        for position in range(index):
            result.append(values[position])
        result.append(element)
        for position in range(index, len(values)):
            result.append(values[position])
        return result
    if name in {"List.remove", "List.removeAll"}:
        if name == "List.remove":
            other = [_value(translator, _required(args, "element", name))]
        else:
            other = _list(translator, _required(args, "other", name), name)
            charge_array(translator, max(1, len(values)))
            removed = [_matches(translator, item, other) for item in values]
            _copy(translator, values)
            return [item for item, is_removed in zip(values, removed) if not is_removed]
        remove_index = _find(translator, values, other[0])
        _copy(translator, values)
        if name == "List.remove":
            return [item for index, item in enumerate(values) if index != remove_index]
    if name in {"List.replace", "List.replaceAll"}:
        old = _value(translator, _required(args, "oldval", name))
        new = _value(translator, _required(args, "newval", name))
        if name == "List.replace":
            index = _find(translator, values, old)
            _copy(translator, values)
            result = list(values)
            if index >= 0:
                result[index] = new
            return result
        charge_array(translator, max(1, len(values)))
        matches = [static_equal(translator, item, old) for item in values]
        _copy(translator, values)
        return [new if matched else item for item, matched in zip(values, matches)]
    if name == "List.rotate":
        distance = _integer(_required(args, "distance", name), "List.rotate distance")
        _copy(translator, values)
        if not values:
            return []
        split = (-distance) % len(values)
        return [values[(split + index) % len(values)] for index in range(len(values))]
    if name == "List.splice":
        start = _position(_required(args, "start", name), len(values), "List.splice start", insertion=True)
        count = _integer(_required(args, "count", name), "List.splice count", minimum=0)
        other = args.get("other")
        if other is None:
            other = []
        other = _list(translator, other, name)
        removed = min(count, len(values) - start)
        _copy(translator, values, len(other) - removed)
        result = []
        for index in range(start):
            result.append(values[index])
        result.extend(other)
        for index in range(start + removed, len(values)):
            result.append(values[index])
        return result

    fail(f"Unsupported static operation: {name}")
