"""Evaluation of supported static Number, String, List and Dictionary calls."""
from __future__ import annotations

import math

from .array_core import charge_array
from .ir import Collection, Function, Image, UnsupportedEEError, fail, integer
from .static_dictionary import dictionary_value
from .static_equality import contains_value, distinct_values
from .static_sequence import sequence
from .string_values import invoke_string


def scalar_power(left, right):
    """Reject enormous integer exponentiation before allocating its result."""
    if (type(left) is int and type(right) is int and right > 0 and abs(left) > 1
            and (abs(left).bit_length() - 1) * right > 1023):
        fail("Scalar power exceeds the finite Float64 materialization budget")
    result = left ** right
    try:
        if isinstance(result, complex) or not math.isfinite(result):
            fail("Scalar power must produce a finite real number")
    except OverflowError:
        fail("Scalar power exceeds finite Float64 range")
    return result


def invoke_static(translator, name, a):
    """Evaluate a decoded static algorithm using the translator's validators."""
    kind, op = name.split(".", 1)
    argument_names = {
        "String.cat": {"string1", "string2"},
        "String.length": {"string"},
        "String.compareTo": {"string1", "string2"},
        "List.get": {"list", "index"},
        "List.length": {"list"},
        "List.size": {"list"},
        "List.contains": {"list", "element"},
        "List.add": {"list", "element"},
        "List.cat": {"list1", "list2"},
        "List.sequence": {"start", "end", "step", "count"},
        "List.slice": {"list", "start", "end", "step"},
        "List.distinct": {"list"},
        "List.sort": {"list", "keys"},
        "List.map": {"list", "baseAlgorithm", "dropNulls"},
        "List.iterate": {"list", "function", "first"},
        "Dictionary.get": {"dictionary", "key", "defaultValue"},
        "Dictionary.keys": {"dictionary"},
        "Dictionary.values": {"dictionary", "keys"},
        "Dictionary.contains": {"dictionary", "key"},
        "Dictionary.set": {"dictionary", "key", "value"},
    }
    if kind == "Number":
        translator.allowed(
            a,
            {"left", "right"} if op in {
                "add", "subtract", "multiply", "divide", "pow", "mod",
                "eq", "neq", "gt", "gte", "lt", "lte",
            } else {"input"},
        )
    elif name in argument_names:
        translator.allowed(a, argument_names[name])
    vals = list(a.values())
    value = a.get("input", a.get(kind.lower(), a.get("left", vals[0] if vals else None)))
    if kind == "Number":
        if any(isinstance(x, (Image, Collection)) for x in vals):
            fail("Expected a static Number")
        if op in {"sin", "cos"}:
            if "input" not in a:
                fail(f"Number.{op} requires input")
            number = a["input"]
            if (type(number) not in (int, float)
                    or type(number) is int and abs(number) > 2 ** 53
                    or type(number) is float and not math.isfinite(number)):
                fail(f"Number.{op} requires a finite static numeric input; integers must be exact Float64")
            charge_array(translator, 1)
            # Radians, using the host's Float64 libm argument reduction. This
            # is a documented local numeric policy, not Google parity.
            return (math.sin if op == "sin" else math.cos)(number)
        right = a.get("right")
        funcs = {
            "add": lambda: value + right,
            "subtract": lambda: value - right,
            "multiply": lambda: value * right,
            "divide": lambda: value / right if right else 0,
            "pow": lambda: scalar_power(value, right),
            "mod": lambda: value % right,
            "eq": lambda: value == right,
            "neq": lambda: value != right,
            "gt": lambda: value > right,
            "gte": lambda: value >= right,
            "lt": lambda: value < right,
            "lte": lambda: value <= right,
            "abs": lambda: abs(value),
            "round": lambda: math.floor(value + .5),
            "floor": lambda: math.floor(value),
            "ceil": lambda: math.ceil(value),
            "sqrt": lambda: math.sqrt(value),
            "toInt": lambda: int(value),
            "int": lambda: int(value),
        }
        if op in funcs:
            try:
                return funcs[op]()
            except UnsupportedEEError:
                raise
            except (ArithmeticError, TypeError, ValueError):
                fail(f"Invalid static Number.{op} operands")
    if kind == "String":
        return invoke_string(translator, name, a)
    if kind == "List":
        value = a.get("list", value)
        if op == "get":
            try:
                return value[integer(a["index"], "List index")]
            except (IndexError, TypeError):
                fail("List index out of range")
        if op in {"length", "size"}:
            return len(value)
        if op == "contains":
            return contains_value(translator, value, a["element"])
        if op == "add":
            if len(value) >= 10000:
                fail("Computed list exceeds 10000 values")
            return value + [a["element"]]
        if op == "cat":
            if len(a["list1"]) + len(a["list2"]) > 10000:
                fail("Computed list exceeds 10000 values")
            return a["list1"] + a["list2"]
        if op in {"map", "iterate"}:
            if not isinstance(value, list) or len(value) > 1000:
                fail("List.map/iterate supports at most 1000 inline values")
            fun = a["baseAlgorithm" if op == "map" else "function"]
            if not isinstance(fun, Function) or len(fun.names) != (1 if op == "map" else 2):
                fail("Invalid serialized list callback")
            result = [] if op == "map" else a.get("first")
            for item in value:
                args = [item] if op == "map" else [item, result]
                mapped = translator.evaluate(fun.body, {**fun.env, **dict(zip(fun.names, args))})
                if op == "iterate":
                    result = mapped
                elif mapped is not None:
                    result.append(mapped)
                elif not a.get("dropNulls", False):
                    fail("List.map returned null; set dropNulls=true")
            return result
        if op == "slice":
            step = integer(a.get("step", 1), "List slice step", 1)
            start = integer(a.get("start", 0), "List slice start")
            end = None if a.get("end") is None else integer(a["end"], "List slice end")
            return value[start:end:step]
        if op == "distinct":
            return distinct_values(translator, value)
        if op == "sort":
            keys = a.get("keys", value)
            if len(keys) != len(value):
                fail("List.sort keys must match list length")
            return [v for _, v in sorted(zip(keys, value), key=lambda x: x[0])]
        if op == "sequence":
            return sequence(a)
    if kind == "Dictionary":
        return dictionary_value(op, a)
    fail(f"Unsupported static operation: {name}")
