"""Tokenizer and bounded Pratt parser for the Number.expression subset."""
from __future__ import annotations

import math
import re

from .ir import fail


MAX_EXPRESSION_TEXT = 20_000
MAX_EXPRESSION_TOKENS = 4_000
MAX_EXPRESSION_DEPTH = 64
_LEXER = re.compile(
    r"\s*(?:(\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)"
    r"|([A-Za-z_][A-Za-z0-9_]*)|(\*\*|&&|\|\||==|!=|<=|>=|[+*/%<>()\.,!?^:-]))"
)
_PRECEDENCE = {
    "||": 2, "^": 3, "&&": 4, "==": 5, "!=": 5,
    "<": 6, "<=": 6, ">": 6, ">=": 6,
    "+": 7, "-": 7, "*": 8, "/": 8, "%": 8, "**": 9,
}


def _literal(text):
    if "." not in text and "e" not in text.lower():
        digits = text.lstrip("0") or "0"
        if len(digits) > 16 or int(digits) > 2**53:
            fail("Number.expression integer literal exceeds the exact Float64 domain")
        return int(digits)
    try:
        value = float(text)
    except (ValueError, OverflowError):
        fail("Number.expression has an invalid numeric literal")
    if not math.isfinite(value):
        fail("Number.expression numeric literals must be finite")
    return value


class NumberExpressionParser:
    """Parse a closed scalar grammar; the result is inert tagged tuples."""

    def __init__(self, text):
        if type(text) is not str or len(text) > MAX_EXPRESSION_TEXT:
            fail("Number.expression must be a string of at most 20000 characters")
        # The public evaluator charges the original text length before this scan.
        text = text.strip()
        self.tokens = []
        pos = 0
        while pos < len(text):
            match = _LEXER.match(text, pos)
            if not match:
                fail(f"Unsupported Number.expression syntax near character {pos}")
            number, name, symbol = match.groups()
            if number is not None:
                self.tokens.append(("number", _literal(number)))
            elif name is not None:
                self.tokens.append(("name", name))
            else:
                self.tokens.append(("symbol", symbol))
            if len(self.tokens) > MAX_EXPRESSION_TOKENS:
                fail("Number.expression has more than 4000 tokens")
            pos = match.end()
        if not self.tokens:
            fail("Number.expression cannot be empty")
        self.token_count = len(self.tokens)
        self.tokens.append(("end", "<end>"))
        self.index = 0
        self.depth = 0

    def peek(self):
        return self.tokens[self.index][1]

    def take(self, expected=None):
        token = self.tokens[self.index]
        if expected is not None and token[1] != expected:
            fail(f"Expected {expected!r} in Number.expression")
        self.index += 1
        return token

    def parse(self):
        result = self.expression()
        self.take("<end>")
        return result

    def expression(self, minimum=0):
        self.depth += 1
        if self.depth > MAX_EXPRESSION_DEPTH:
            fail("Number.expression nesting exceeds 64")
        try:
            left = self.prefix()
            while True:
                operator = self.peek()
                precedence = _PRECEDENCE.get(operator, -1)
                if precedence < minimum:
                    break
                self.take()
                right = self.expression(precedence if operator == "**" else precedence + 1)
                left = ("binary", operator, left, right)
            if minimum <= 1 and self.peek() == "?":
                self.take("?")
                yes = self.expression()
                self.take(":")
                no = self.expression(1)
                left = ("conditional", left, yes, no)
            return left
        finally:
            self.depth -= 1

    def prefix(self):
        kind, value = self.take()
        if kind == "symbol" and value in {"+", "-", "!"}:
            return ("unary", value, self.expression(9))
        if kind == "symbol" and value == "(":
            result = self.expression()
            self.take(")")
            return result
        if kind == "number":
            return ("number", value)
        if kind != "name":
            fail("Expected a number, variable, function, or parenthesized expression")
        if value == "Math":
            self.take(".")
            constant = self.take()
            if constant != ("name", "PI") and constant != ("name", "E"):
                fail("Only Math.PI and Math.E constants are supported")
            return ("constant", constant[1])
        if self.peek() == "(":
            self.take("(")
            arguments = []
            if self.peek() != ")":
                while True:
                    arguments.append(self.expression())
                    if self.peek() != ",":
                        break
                    self.take(",")
            self.take(")")
            return ("call", value, tuple(arguments))
        path = [value]
        while self.peek() == ".":
            self.take(".")
            member = self.take()
            if member[0] != "name" or member[1].startswith("__"):
                fail("Number.expression only supports static dictionary member names")
            path.append(member[1])
        return ("variable", tuple(path))
