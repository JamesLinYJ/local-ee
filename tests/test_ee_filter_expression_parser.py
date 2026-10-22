"""Bounded Filter.expression parser semantics and rejection limits."""
import pytest

from gee.compat.earthengine.filter_expression import parse_filter_expression
from gee.compat.earthengine.ir import Filter, UnsupportedEEError


class Translator:
    def __init__(self, steps=0):
        self.steps = steps


def test_comparison_operators_lower_to_existing_filter_ir():
    cases = {
        "score > 3": Filter("greaterThan", {"leftField": "score", "rightValue": 3}),
        "score >= 3": Filter("not", {"filter": Filter(
            "lessThan", {"leftField": "score", "rightValue": 3})}),
        "3 <= score": Filter("not", {"filter": Filter(
            "lessThan", {"leftField": "score", "rightValue": 3})}),
        "label != 'class \\'a\\''": Filter("not", {"filter": Filter(
            "equals", {"leftField": "label", "rightValue": "class 'a'"})}),
        "system:time_start == 123": Filter(
            "equals", {"leftField": "system:time_start", "rightValue": 123}),
        "true == enabled": Filter("equals", {"leftField": "enabled", "rightValue": True}),
        "1 < score": Filter("greaterThan", {"leftField": "score", "rightValue": 1}),
    }
    for expression, expected in cases.items():
        assert parse_filter_expression(Translator(), expression) == expected


def test_boolean_precedence_and_parentheses_are_preserved():
    parsed = parse_filter_expression(
        Translator(), "a == 1 || b == 2 && !(c < 3)",
    )
    assert parsed.name == "or"
    first, second = parsed.args["filters"]
    assert first == Filter("equals", {"leftField": "a", "rightValue": 1})
    assert second.name == "and"
    child1, child2 = second.args["filters"]
    assert child1 == Filter("equals", {"leftField": "b", "rightValue": 2})
    assert child2 == Filter("not", {"filter": Filter(
        "lessThan", {"leftField": "c", "rightValue": 3})})
    grouped = parse_filter_expression(Translator(), "(a == 1 || b == 2) && c == 3")
    assert grouped.name == "and"
    assert grouped.args["filters"][0].name == "or"


@pytest.mark.parametrize("expression", [
    "", "score", "score + 1 > 2", "score > 1 > 0", "score == null",
    "a.b == 1", "foo(1) == 2", "score == NaN", "score == Infinity",
    "score == 9007199254740993", "score == 1e999", "score == 'unterminated",
    "score == 'bad\\q'", "score == 1; system:delete == true",
])
def test_unsupported_expression_forms_fail_closed(expression):
    with pytest.raises(UnsupportedEEError):
        parse_filter_expression(Translator(), expression)


def test_expression_limits_and_work_are_checked_before_lexing():
    with pytest.raises(UnsupportedEEError, match="4096 characters"):
        parse_filter_expression(Translator(), "x" * 4097)
    assert parse_filter_expression(
        Translator(), "!" * 16 + "x == 1",
    ).name == "not"
    assert parse_filter_expression(
        Translator(), "(" * 16 + "x == 1" + ")" * 16,
    ).name == "equals"
    with pytest.raises(UnsupportedEEError, match="depth limit"):
        parse_filter_expression(Translator(), "(" * 17 + "x == 1" + ")" * 17)
    with pytest.raises(UnsupportedEEError, match="depth limit"):
        parse_filter_expression(Translator(), "!" * 17 + "x == 1")
    too_many_tokens = " && ".join(["x == 1"] * 70)
    with pytest.raises(UnsupportedEEError, match="256 tokens"):
        parse_filter_expression(Translator(), too_many_tokens)
    translator = Translator(50000 - 3)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        parse_filter_expression(translator, "x == 1")
    assert translator.steps == 50000 - 3


def test_filter_node_count_and_non_ascii_identifier_restrictions():
    too_many_nodes = " && ".join(["x==1"] * 64)
    with pytest.raises(UnsupportedEEError, match="64 filter nodes"):
        parse_filter_expression(Translator(), too_many_nodes)
    with pytest.raises(UnsupportedEEError, match="unsupported character"):
        parse_filter_expression(Translator(), "温度 > 1")
