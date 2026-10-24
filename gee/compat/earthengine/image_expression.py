"""Validate the official second-order Image.parseExpression call signature."""
from __future__ import annotations

from .array_core import charge_array
from .ir import ParsedExpression, as_image, fail


def descriptor(translator, arguments):
    translator.allowed(arguments, {"expression", "argName", "vars"})
    if not {"expression", "argName", "vars"} <= arguments.keys():
        fail("Image.parseExpression requires expression, argName and vars")
    text, default, names = (arguments[key] for key in ("expression", "argName", "vars"))
    if type(text) is not str or len(text) > 20_000:
        fail("Image expression must be a string of at most 20000 characters")
    if type(default) is not str or type(names) is not list or not 1 <= len(names) <= 10_000:
        fail("Image.parseExpression needs a default argument and1..10000 variable names")
    charge_array(translator, 4 + 2 * len(names) + len(default))
    if any(type(name) is not str for name in names):
        fail("Image.parseExpression variable names must be strings")
    charge_array(translator, sum(map(len, names)))
    if len(set(names)) != len(names) or default not in names:
        fail("Image.parseExpression needs unique variables including its default argument")
    return ParsedExpression(text, default, tuple(names))


def invoke(translator, function, arguments):
    charge_array(translator, 2 + len(arguments) + len(function.variables))
    if set(arguments) != set(function.variables):
        fail("Image expression function argument names do not match its declared variables")
    # Validate every declared Image argument, including unused variables. This
    # keeps malformed descriptions from being laundered through a short formula.
    variables = {name: as_image(arguments[name]) for name in function.variables}
    from ...ee_expression import parse_expression

    return parse_expression(function.text, variables, function.default, translator)
