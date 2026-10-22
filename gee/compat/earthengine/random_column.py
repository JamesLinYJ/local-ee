"""Compiler boundary for bounded inline and lazy sampled random columns."""
from __future__ import annotations

from ...random_column_spec import decode_random_column_spec, prepare_random_column_spec
from ...random_column_values import apply_random_column
from .feature_values import charge
from .ir import UnsupportedEEError, fail


def prepare_random_column(translator, arguments):
    """Validate arguments and precharge the canonical local operation spec."""
    translator.allowed(arguments, {
        "collection", "columnName", "seed", "distribution", "rowKeys",
    })
    column_name = arguments.get("columnName", "random")
    seed = arguments.get("seed", 0)
    distribution = arguments.get("distribution", "uniform")
    row_keys = arguments.get("rowKeys")

    # Charge names and bounded row-key shape before the shared encoder walks
    # them. Invalid non-list values cost one step and are rejected by it.
    work = 128 + (len(column_name) if type(column_name) is str else 1)
    if type(row_keys) is list:
        work += len(row_keys)
        work += sum(len(key) if type(key) is str else 1 for key in row_keys)
    elif row_keys is not None:
        work += 1
    charge(translator, work)
    try:
        spec = prepare_random_column_spec(
            column_name=column_name,
            seed=seed,
            distribution=distribution,
            row_keys=row_keys,
        )
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Collection.randomColumn has invalid arguments: {exc}")
    charge(translator, 6 * len(spec) + 1)
    return spec


def apply_inline_random_column(translator, features, spec):
    """Apply the trusted pure helper to already validated inline Features."""
    try:
        charge(translator, 6 * len(spec) + 1)
        decoded = decode_random_column_spec(spec)
        return apply_random_column(
            features, decoded,
            charge=lambda amount: charge(translator, amount),
        )
    except UnsupportedEEError:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as exc:
        fail(f"Collection.randomColumn cannot resolve its row keys: {exc}")
