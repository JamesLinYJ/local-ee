"""Evaluation of supported static Number, String, List and Dictionary calls."""
from __future__ import annotations

import math

from .ir import Collection, Function, Image, fail, integer


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
        right = a.get("right")
        funcs = {
            "add": lambda: value + right,
            "subtract": lambda: value - right,
            "multiply": lambda: value * right,
            "divide": lambda: value / right if right else 0,
            "pow": lambda: value ** right,
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
            except (ArithmeticError, TypeError, ValueError):
                fail(f"Invalid static Number.{op} operands")
    if kind == "String":
        if op == "cat":
            return str(a["string1"]) + str(a["string2"])
        if op == "length":
            return len(value)
        if op == "compareTo":
            return (value > a["string2"]) - (value < a["string2"])
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
            return a["element"] in value
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
            result = []
            for item in value:
                if item not in result:
                    result.append(item)
            return result
        if op == "sort":
            keys = a.get("keys", value)
            if len(keys) != len(value):
                fail("List.sort keys must match list length")
            return [v for _, v in sorted(zip(keys, value), key=lambda x: x[0])]
        if op == "sequence":
            if a.get("count") is not None:
                fail("List.sequence count parameter is unsupported")
            start, end, step = a.get("start", 0), a["end"], a.get("step", 1)
            if not step or abs((end - start) / step) > 10000:
                fail("List.sequence limit exceeded")
            length = max(0, int(math.floor((end - start) / step)) + 1)
            return [start + i * step for i in range(length)]
    if kind == "Dictionary":
        value = a.get("dictionary", value)
        if op == "get":
            return value.get(a["key"], a.get("defaultValue"))
        if op == "keys":
            return sorted(value)
        if op == "values":
            return [value[key] for key in (a.get("keys") or sorted(value))]
        if op == "contains":
            return a["key"] in value
        if op == "set":
            return {**value, a["key"]: a["value"]}
    fail(f"Unsupported static operation: {name}")
