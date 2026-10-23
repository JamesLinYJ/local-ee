"""Pinned snake-case Number integer aliases for canonical dispatch."""
from __future__ import annotations


NUMBER_INTEGER_ALIAS_MAP = {
    "Number.bitwise_and": "Number.bitwiseAnd",
    "Number.bitwise_not": "Number.bitwiseNot",
    "Number.bitwise_or": "Number.bitwiseOr",
    "Number.bitwise_xor": "Number.bitwiseXor",
    "Number.left_shift": "Number.leftShift",
    "Number.right_shift": "Number.rightShift",
}
NUMBER_INTEGER_ALIAS_FUNCTIONS = frozenset(NUMBER_INTEGER_ALIAS_MAP)


def canonical_integer_name(name: str) -> str:
    """Map one pinned snake-case alias to its audited camel-case operation.

    Returning unrecognized or already canonical names unchanged lets dispatch
    normalize aliases without importing the legacy ``gee.ee_integer`` helper.
    """
    return NUMBER_INTEGER_ALIAS_MAP.get(name, name)
