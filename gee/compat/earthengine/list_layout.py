"""Bounded static layout operations for typed Earth Engine List values."""
from __future__ import annotations

from .array_core import charge_array
from .ir import fail, integer


MAX_LIST_VALUES = 10_000
MAX_LIST_DEPTH = 96
MAX_LIST_SCAN = 50_000

LIST_LAYOUT_FUNCTIONS = frozenset({
    "List.zip", "List.unzip", "List.flatten", "List.repeat",
    "List.reverse", "List.set", "List.swap",
})


def _list(value, label):
    if not isinstance(value, list):
        fail(f"{label} requires a static List")
    if len(value) > MAX_LIST_VALUES:
        fail(f"{label} exceeds {MAX_LIST_VALUES} top-level values")
    return value


def _required(args, name, operation):
    if name not in args:
        fail(f"{operation} requires {name}")
    return args[name]


def _position(value, length, label):
    position = integer(value, label)
    if position < 0:
        position += length
    if position < 0 or position >= length:
        fail(f"{label} is outside the List bounds")
    return position


def _flatten(translator, root):
    root = _list(root, "List.flatten")
    scan_count = 0
    leaf_count = 0

    def inspect(value, depth):
        nonlocal scan_count, leaf_count
        if depth > MAX_LIST_DEPTH:
            fail(f"List.flatten exceeds depth {MAX_LIST_DEPTH}")
        scan_count += 1
        if scan_count > MAX_LIST_SCAN:
            fail(f"List.flatten exceeds {MAX_LIST_SCAN} scanned values")
        charge_array(translator, 1)
        if isinstance(value, list):
            if len(value) > MAX_LIST_VALUES:
                fail(f"List.flatten sublist exceeds {MAX_LIST_VALUES} values")
            charge_array(translator, len(value))
            for child in value:
                inspect(child, depth + 1)
        else:
            leaf_count += 1
            if leaf_count > MAX_LIST_VALUES:
                fail(f"List.flatten output exceeds {MAX_LIST_VALUES} values")

    # First count and validate without building the output. Every visited node
    # is charged before it is inspected; the second walk is fully precharged.
    inspect(root, 0)
    charge_array(translator, scan_count + leaf_count + 1)
    result = []

    def emit(value, depth):
        if isinstance(value, list):
            for child in value:
                emit(child, depth + 1)
        else:
            result.append(value)

    emit(root, 0)
    return result


def invoke_list_layout(translator, name, args):
    """Evaluate only the pinned bounded List layout algorithms."""
    if name not in LIST_LAYOUT_FUNCTIONS:
        fail(f"Unsupported Earth Engine algorithm: {name}")

    if name == "List.zip":
        translator.allowed(args, {"list", "other"})
        left = _list(_required(args, "list", name), name)
        right = _list(_required(args, "other", name), name)
        length = min(len(left), len(right))
        charge_array(translator, 1 + 3 * length)
        return [[left[index], right[index]] for index in range(length)]

    if name == "List.unzip":
        translator.allowed(args, {"list"})
        outer = _list(_required(args, "list", name), name)
        if not outer:
            charge_array(translator, 1)
            return []
        charge_array(translator, len(outer))
        width = None
        for inner in outer:
            if not isinstance(inner, list):
                fail("List.unzip requires every element to be a static List")
            if len(inner) > MAX_LIST_VALUES:
                fail(f"List.unzip inner list exceeds {MAX_LIST_VALUES} values")
            width = len(inner) if width is None else min(width, len(inner))
        width = width or 0
        work = width * (len(outer) + 1)
        charge_array(translator, max(1, work))
        return [[inner[index] for inner in outer] for index in range(width)]

    if name == "List.flatten":
        translator.allowed(args, {"list"})
        return _flatten(translator, _required(args, "list", name))

    if name == "List.repeat":
        translator.allowed(args, {"value", "count"})
        value = _required(args, "value", name)
        count = integer(_required(args, "count", name), "List.repeat count", 0)
        if count > MAX_LIST_VALUES:
            fail(f"List.repeat count exceeds {MAX_LIST_VALUES}")
        charge_array(translator, max(1, count))
        return [value] * count

    if name == "List.reverse":
        translator.allowed(args, {"list"})
        values = _list(_required(args, "list", name), name)
        charge_array(translator, max(1, len(values)))
        return list(reversed(values))

    if name == "List.set":
        translator.allowed(args, {"list", "index", "element"})
        values = _list(_required(args, "list", name), name)
        index = _position(_required(args, "index", name), len(values), "List.set index")
        element = _required(args, "element", name)
        charge_array(translator, max(1, len(values)))
        result = list(values)
        result[index] = element
        return result

    translator.allowed(args, {"list", "pos1", "pos2"})
    values = _list(_required(args, "list", name), name)
    first = _position(_required(args, "pos1", name), len(values), "List.swap pos1")
    second = _position(_required(args, "pos2", name), len(values), "List.swap pos2")
    charge_array(translator, max(1, len(values)))
    result = list(values)
    result[first], result[second] = result[second], result[first]
    return result
