"""Finite scalar, variable, and supported Number-function semantics."""
from __future__ import annotations

import math
import re

from .ir import fail


MAX_EXPRESSION_WORK = 50_000
MAX_EXPRESSION_INTEGER = 2**53
MAX_VARIABLE_NODES = 10_000
MAX_VARIABLE_DEPTH = 32
MAX_VARIABLE_KEY_CHARS = 64
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_BINARY_CALLS = frozenset({
    "add", "subtract", "multiply", "divide", "mod", "pow",
    "eq", "neq", "gt", "gte", "lt", "lte",
})
_UNARY_CALLS = frozenset({"abs", "sqrt", "round", "floor", "ceil"})
_MATH_BINARY = frozenset({
    "hypot", "atan2", "min", "max", "first", "firstNonZero",
    "first_nonzero", "and", "or",
})
_MATH_TERNARY = frozenset({"clamp", "unitScale"})
_MATH_UNARY = frozenset({
    "sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh",
    "tanh", "log", "log10", "exp", "cbrt", "signum", "erf", "erfc",
    "gamma", "not",
})
_SPECIAL_UNARY = frozenset({"digamma", "trigamma", "erfInv", "erfcInv"})
FUNCTION_ARITY = {
    **{name: 2 for name in _BINARY_CALLS | _MATH_BINARY},
    **{name: 1 for name in _UNARY_CALLS | _MATH_UNARY | _SPECIAL_UNARY},
    **{name: 3 for name in _MATH_TERNARY},
}


def charge(translator, amount):
    if amount < 0 or translator.steps + amount > MAX_EXPRESSION_WORK:
        fail("Number.expression exceeds the shared 50000-step compilation work budget")
    translator.steps += amount


def number(value, label):
    if type(value) not in (int, float):
        fail(f"{label} must be a finite static Number")
    if type(value) is int and abs(value) > MAX_EXPRESSION_INTEGER:
        fail(f"{label} integer exceeds the exact Float64 domain")
    if type(value) is float and not math.isfinite(value):
        fail(f"{label} must be a finite static Number")
    return value


def validate_variables(translator, value):
    """Precharge and validate every nested vars value, including unused ones."""
    if value is None:
        return
    if type(value) is not dict:
        fail("Number.expression vars must be a dictionary or null")

    stack = [(value, 0, False, True)]
    active = set()
    nodes = 0
    scheduled = 0
    while stack:
        current, depth, leaving, root = stack.pop()
        if leaving:
            active.remove(id(current))
            continue
        if not root:
            nodes += 1
            if nodes > MAX_VARIABLE_NODES:
                fail("Number.expression vars exceed 10000 static values")
            charge(translator, 1)
        if type(current) is dict:
            if depth > MAX_VARIABLE_DEPTH:
                fail("Number.expression vars nesting exceeds 32")
            identity = id(current)
            if identity in active:
                fail("Number.expression vars contain a cycle")
            child_count = len(current)
            if scheduled + child_count > MAX_VARIABLE_NODES:
                fail("Number.expression vars exceed 10000 static values")
            scheduled += child_count
            # Reserve child scheduling before inspecting entries. Then count
            # bounded key characters before regex validation or stack growth.
            charge(translator, child_count)
            key_chars = 0
            for key in current:
                if type(key) is not str:
                    fail("Number.expression vars keys must be identifier names")
                length = len(key)
                if length > MAX_VARIABLE_KEY_CHARS:
                    fail("Number.expression vars keys exceed 64 characters")
                key_chars += length
            charge(translator, key_chars)
            active.add(identity)
            stack.append((current, depth, True, False))
            for key, item in current.items():
                if not _NAME.fullmatch(key):
                    fail("Number.expression vars keys must be identifier names")
                stack.append((item, depth + 1, False, False))
        else:
            number(current, "Number.expression vars value")


def lookup(variables, path):
    value = variables
    for part in path:
        if type(value) is not dict or part not in value:
            fail(f"Unknown Number.expression variable: {'.'.join(path)}")
        value = value[part]
    return number(value, f"Number.expression variable {'.'.join(path)}")


def truth(value):
    return value != 0


def _checked(value, label="Number.expression result"):
    return number(value, label)


def _power(left, right):
    if type(left) is int and type(right) is int and right >= 0:
        # This lower bound safely rejects enormous powers before allocation,
        # while leaving near-boundary results to the exact integer check.
        if (abs(left).bit_length() - 1) * right > 53:
            fail("Number.expression power exceeds the exact Float64 integer domain")
        return _checked(left ** right)
    try:
        return _checked(math.pow(float(left), float(right)))
    except (ArithmeticError, ValueError):
        fail("Number.expression power must produce a finite real result")


def binary(operator, left, right):
    try:
        if operator == "+":
            result = left + right
        elif operator == "-":
            result = left - right
        elif operator == "*":
            result = left * right
        elif operator == "/":
            if right == 0:
                result = 0
            elif type(left) is int and type(right) is int:
                result = left // right
            else:
                result = left / right
        elif operator == "%":
            if right == 0:
                fail("Number.expression modulus by zero has no finite result")
            if type(left) is int and type(right) is int:
                result = abs(left) % abs(right)
                if left < 0:
                    result = -result
            else:
                result = math.fmod(left, right)
        elif operator == "**":
            return _power(left, right)
        elif operator == "==":
            return int(left == right)
        elif operator == "!=":
            return int(left != right)
        elif operator == "<":
            return int(left < right)
        elif operator == "<=":
            return int(left <= right)
        elif operator == ">":
            return int(left > right)
        elif operator == ">=":
            return int(left >= right)
        elif operator == "^":
            return int(truth(left) != truth(right))
        else:
            fail(f"Unsupported Number.expression operator: {operator}")
    except (ArithmeticError, TypeError, ValueError):
        fail(f"Number.expression operator {operator} must produce a finite real result")
    return _checked(result)


def _round(value):
    if type(value) is int or abs(value) >= 2**52:
        return value
    lower = math.floor(value)
    return lower + int(value - lower >= 0.5)


def call(translator, name, values):
    if name in _BINARY_CALLS:
        operator = {
            "add": "+", "subtract": "-", "multiply": "*", "divide": "/",
            "mod": "%", "pow": "**", "eq": "==", "neq": "!=",
            "gt": ">", "gte": ">=", "lt": "<", "lte": "<=",
        }[name]
        return binary(operator, *values)
    if name in _UNARY_CALLS:
        value = values[0]
        try:
            if name == "abs":
                result = abs(value)
            elif name == "sqrt":
                result = math.sqrt(value)
            elif name == "round":
                result = _round(value)
            elif name == "floor":
                result = math.floor(value)
            else:
                result = math.ceil(value)
        except (ArithmeticError, TypeError, ValueError):
            fail(f"Number.expression function {name} has no finite real result")
        return _checked(result)
    if name in _MATH_UNARY | _MATH_BINARY | _MATH_TERNARY:
        from .number_math import invoke_number_math

        operation = "Number." + name
        if name in _MATH_UNARY:
            arguments = {"input": values[0]}
        elif name in _MATH_BINARY:
            arguments = {"left": values[0], "right": values[1]}
        else:
            arguments = dict(zip(("number", "min", "max"), values))
        return _checked(invoke_number_math(translator, operation, arguments))
    if name in _SPECIAL_UNARY:
        from .static_special_math import invoke_static_special_math

        return _checked(invoke_static_special_math(
            translator, "Number." + name, {"input": values[0]},
        ))
    fail(f"Unsupported Number.expression function: {name}")


def result(value):
    return _checked(value)
