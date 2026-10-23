"""Bounded finite scalar evaluator for the pinned ``Number.expression`` API."""
from __future__ import annotations

import math

from .ir import fail
from .number_expression_parser import (
    MAX_EXPRESSION_DEPTH,
    MAX_EXPRESSION_TEXT,
    NumberExpressionParser,
)
from .number_expression_values import (
    FUNCTION_ARITY,
    binary,
    charge,
    call,
    lookup,
    number,
    result,
    truth,
    validate_variables,
)


NUMBER_EXPRESSION_FUNCTIONS = frozenset({"Number.expression"})


def _tree_precharge(root):
    """Count bounded AST and path work before variable/function validation."""
    stack = [(root, 1)]
    nodes = 0
    path_steps = 0
    while stack:
        node, depth = stack.pop()
        if depth > MAX_EXPRESSION_DEPTH:
            fail("Number.expression nesting exceeds 64")
        nodes += 1
        kind = node[0]
        if kind == "variable":
            if len(node[1]) > 33:
                fail("Number.expression member path exceeds 32 nested dictionaries")
            path_steps += len(node[1])
        elif kind == "unary":
            stack.append((node[2], depth + 1))
        elif kind == "binary":
            stack.extend(((node[2], depth + 1), (node[3], depth + 1)))
        elif kind == "conditional":
            stack.extend((child, depth + 1) for child in node[1:])
        elif kind == "call":
            stack.extend((child, depth + 1) for child in node[2])
    # The tree is walked once for prevalidation and again for evaluation.
    return nodes + 2 * path_steps


def _validate_tree(node, variables):
    """Check every branch, even those evaluation will short-circuit."""
    kind = node[0]
    if kind == "variable":
        lookup(variables, node[1])
    elif kind in {"number", "constant"}:
        return
    elif kind == "unary":
        _validate_tree(node[2], variables)
    elif kind == "binary":
        _validate_tree(node[2], variables)
        _validate_tree(node[3], variables)
    elif kind == "conditional":
        for child in node[1:]:
            _validate_tree(child, variables)
    elif kind == "call":
        if node[1] not in FUNCTION_ARITY:
            fail(f"Unsupported Number.expression function: {node[1]}")
        arity = FUNCTION_ARITY[node[1]]
        if len(node[2]) != arity:
            fail(f"Number.expression function {node[1]} expects {arity} argument(s)")
        for child in node[2]:
            _validate_tree(child, variables)
    else:
        fail("Invalid Number.expression syntax tree")


def _evaluate(translator, node, variables):
    kind = node[0]
    if kind == "number":
        return node[1]
    if kind == "constant":
        return math.pi if node[1] == "PI" else math.e
    if kind == "variable":
        return lookup(variables, node[1])
    if kind == "unary":
        value = _evaluate(translator, node[2], variables)
        if node[1] == "+":
            return value
        if node[1] == "-":
            return number(-value, "Number.expression result")
        return int(not truth(value))
    if kind == "binary":
        operator = node[1]
        left = _evaluate(translator, node[2], variables)
        if operator == "&&":
            return int(truth(left) and truth(_evaluate(translator, node[3], variables)))
        if operator == "||":
            return int(truth(left) or truth(_evaluate(translator, node[3], variables)))
        return binary(operator, left, _evaluate(translator, node[3], variables))
    if kind == "conditional":
        condition = _evaluate(translator, node[1], variables)
        selected = node[2] if truth(condition) else node[3]
        return _evaluate(translator, selected, variables)
    if kind == "call":
        values = [_evaluate(translator, item, variables) for item in node[2]]
        return call(translator, node[1], values)
    fail("Invalid Number.expression syntax tree")


def invoke_number_expression(translator, name, arguments):
    """Evaluate a bounded static numeric expression, never arbitrary source."""
    if name not in NUMBER_EXPRESSION_FUNCTIONS:
        fail(f"Unsupported static Number expression: {name}")
    translator.allowed(arguments, {"expression", "vars"})
    if "expression" not in arguments:
        fail("Number.expression requires expression")
    text = arguments["expression"]
    if type(text) is not str or len(text) > MAX_EXPRESSION_TEXT:
        fail("Number.expression must be a string of at most 20000 characters")
    # Charge the complete source scan once before strip/lexing it.
    charge(translator, len(text))
    variables = arguments.get("vars")
    validate_variables(translator, variables)
    parser = NumberExpressionParser(text)
    # Reserve both parser and evaluator work before parsing into a tree.
    charge(translator, 2 * parser.token_count)
    tree = parser.parse()
    charge(translator, _tree_precharge(tree))
    scope = variables if variables is not None else {}
    _validate_tree(tree, scope)
    return result(_evaluate(translator, tree, scope))
