"""Pure, bounded parser for the pinned Filter.expression operator subset."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .ir import Filter, fail


MAX_EXPRESSION_CHARS = 4096
MAX_TOKENS = 256
MAX_NESTING = 16
MAX_FILTER_NODES = 64
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_IDENTIFIER_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENTIFIER_CONTINUE = _IDENTIFIER_START | frozenset("0123456789:")
_COMPARE = {">", ">=", "<", "<=", "==", "!="}


@dataclass(frozen=True)
class _Token:
    kind: str
    value: object
    offset: int


def _charge(translator, amount):
    if translator.steps + amount > 50000:
        fail("Filter.expression exceeds the 50000-step compilation work budget")
    translator.steps += amount


def _string_token(text, start, quote):
    chars = []
    index = start + 1
    escapes = {"\\": "\\", "'": "'", '"': '"', "/": "/",
               "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    while index < len(text):
        char = text[index]
        index += 1
        if char == quote:
            return "".join(chars), index
        if char == "\\":
            if index >= len(text):
                fail("Filter.expression has an incomplete string escape")
            escaped = text[index]
            index += 1
            if escaped == "u":
                digits = text[index:index + 4]
                if len(digits) != 4 or any(c not in "0123456789abcdefABCDEF" for c in digits):
                    fail("Filter.expression has an invalid Unicode escape")
                codepoint = int(digits, 16)
                index += 4
                if 0xD800 <= codepoint <= 0xDBFF:
                    if text[index:index + 2] != "\\u":
                        fail("Filter.expression has an unpaired Unicode surrogate")
                    low_digits = text[index + 2:index + 6]
                    if (len(low_digits) != 4
                            or any(c not in "0123456789abcdefABCDEF" for c in low_digits)):
                        fail("Filter.expression has an invalid Unicode escape")
                    low = int(low_digits, 16)
                    if not 0xDC00 <= low <= 0xDFFF:
                        fail("Filter.expression has an unpaired Unicode surrogate")
                    chars.append(chr(0x10000 + ((codepoint - 0xD800) << 10) + low - 0xDC00))
                    index += 6
                    continue
                if 0xDC00 <= codepoint <= 0xDFFF:
                    fail("Filter.expression has an unpaired Unicode surrogate")
                chars.append(chr(codepoint))
                continue
            if escaped not in escapes:
                fail("Filter.expression has an unsupported string escape")
            chars.append(escapes[escaped])
            continue
        if ord(char) < 0x20 or 0xD800 <= ord(char) <= 0xDFFF:
            fail("Filter.expression strings cannot contain control or surrogate characters")
        chars.append(char)
    fail("Filter.expression has an unterminated string literal")


def _lex(text):
    tokens = []
    index = 0
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        start = index
        if char in "'\"":
            value, index = _string_token(text, index, char)
            tokens.append(_Token("literal", value, start))
        elif char in _IDENTIFIER_START:
            index += 1
            while index < len(text) and text[index] in _IDENTIFIER_CONTINUE:
                index += 1
            value = text[start:index]
            if value == "true":
                tokens.append(_Token("literal", True, start))
            elif value == "false":
                tokens.append(_Token("literal", False, start))
            elif value in {"null", "NaN", "Infinity"}:
                fail("Filter.expression null and non-finite literals are unsupported")
            else:
                tokens.append(_Token("field", value, start))
        elif char.isdigit() or char == "." or char in "+-":
            match = _NUMBER.match(text, index)
            if match is None:
                fail(f"Filter.expression has an invalid number at character {index}")
            raw = match.group(0)
            index = match.end()
            if raw.lstrip("+-").isdigit():
                value = int(raw)
                if abs(value) > 2**53:
                    fail("Filter.expression integer literals must be exactly representable")
            else:
                value = float(raw)
                if not math.isfinite(value):
                    fail("Filter.expression numeric literals must be finite")
            tokens.append(_Token("literal", value, start))
        else:
            operator = next((candidate for candidate in (">=", "<=", "==", "!=", "&&", "||")
                             if text.startswith(candidate, index)), None)
            if operator is not None:
                tokens.append(_Token(operator, operator, start))
                index += len(operator)
            elif char in "><!()":
                tokens.append(_Token(char, char, start))
                index += 1
            else:
                fail(f"Filter.expression has an unsupported character at {index}")
        if len(tokens) > MAX_TOKENS:
            fail("Filter.expression supports at most 256 tokens")
    tokens.append(_Token("eof", None, len(text)))
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0

    def current(self):
        return self.tokens[self.index]

    def take(self, kind=None):
        token = self.current()
        if kind is not None and token.kind != kind:
            fail(f"Filter.expression expected {kind} at character {token.offset}")
        self.index += 1
        return token

    def parse(self):
        if self.current().kind == "eof":
            fail("Filter.expression cannot be empty")
        result = self.parse_or(0)
        if self.current().kind != "eof":
            if self.current().kind in _COMPARE:
                fail("Filter.expression does not support chained comparisons")
            fail(f"Filter.expression has unexpected input at character {self.current().offset}")
        if _node_count(result) > MAX_FILTER_NODES:
            fail("Filter.expression supports at most 64 filter nodes")
        return result

    def parse_or(self, depth):
        filters = [self.parse_and(depth)]
        while self.current().kind == "||":
            self.take()
            filters.append(self.parse_and(depth))
        if len(filters) == 1:
            return filters[0]
        if len(filters) > 64:
            fail("Filter.expression supports at most 64 operands per boolean operator")
        return Filter("or", {"filters": filters})

    def parse_and(self, depth):
        filters = [self.parse_unary(depth)]
        while self.current().kind == "&&":
            self.take()
            filters.append(self.parse_unary(depth))
        if len(filters) == 1:
            return filters[0]
        if len(filters) > 64:
            fail("Filter.expression supports at most 64 operands per boolean operator")
        return Filter("and", {"filters": filters})

    def parse_unary(self, depth):
        if self.current().kind == "!":
            token = self.take()
            if depth >= MAX_NESTING:
                fail("Filter.expression nesting exceeds the depth limit of 16")
            child = self.parse_unary(depth + 1)
            return Filter("not", {"filter": child})
        if self.current().kind == "(":
            token = self.take()
            if depth >= MAX_NESTING:
                fail("Filter.expression nesting exceeds the depth limit of 16")
            result = self.parse_or(depth + 1)
            self.take(")")
            return result
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_operand()
        operator = self.current()
        if operator.kind not in _COMPARE:
            fail(f"Filter.expression expected a comparison operator at character {operator.offset}")
        self.take()
        right = self.parse_operand()
        if self.current().kind in _COMPARE:
            fail("Filter.expression does not support chained comparisons")
        if left[0] == right[0] == "literal":
            fail("Filter.expression comparisons require at least one property name")
        if left[0] == "literal":
            left, right = right, left
            operator = _Token(_reverse_operator(operator.kind), operator.value, operator.offset)
        return _comparison(left, right, operator.kind)

    def parse_operand(self):
        token = self.current()
        if token.kind in {"field", "literal"}:
            self.take()
            return token.kind, token.value
        if token.kind == "eof":
            fail("Filter.expression is missing a comparison operand")
        fail(f"Filter.expression expected a property or literal at character {token.offset}")


def _reverse_operator(operator):
    return {">": "<", ">=": "<=", "<": ">", "<=": ">=",
            "==": "==", "!=": "!="}[operator]


def _comparison(left, right, operator):
    names = {">": "greaterThan", "<": "lessThan", "==": "equals"}
    if operator in {">=", "<=", "!="}:
        inner = {">=": "lessThan", "<=": "greaterThan", "!=": "equals"}[operator]
        name = inner
    else:
        name = names[operator]
    arguments = {
        "leftField" if left[0] == "field" else "leftValue": left[1],
        "rightField" if right[0] == "field" else "rightValue": right[1],
    }
    result = Filter(name, arguments)
    return Filter("not", {"filter": result}) if operator in {">=", "<=", "!="} else result


def _node_count(filt):
    if filt.name in {"and", "or"}:
        return 1 + sum(_node_count(child) for child in filt.args["filters"])
    if filt.name == "not":
        return 1 + _node_count(filt.args["filter"])
    return 1


def parse_filter_expression(translator, expression):
    """Parse supported Filter.expression syntax without evaluating input text."""
    if not isinstance(expression, str):
        fail("Filter.expression requires a string")
    if len(expression) > MAX_EXPRESSION_CHARS:
        fail("Filter.expression supports at most 4096 characters")
    # Reserve scan and parse work before creating token or AST lists.
    _charge(translator, len(expression) + 1)
    return _Parser(_lex(expression)).parse()
