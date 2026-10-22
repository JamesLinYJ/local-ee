"""Versioned local random-column options; executable expressions are never accepted."""
from __future__ import annotations

import math

from .sampling_spec import _parse, encode_spec


ALGORITHM = "sha256-rowkeys-v1"
MAX_BYTES = 16_384
_KEYS = {"version", "operation", "algorithm", "column_name", "seed", "distribution", "row_keys"}


def _name(value, *, output=False):
    if (type(value) is not str or not value or len(value) > 256
            or "." in value or "\0" in value or (output and value == "system:index")):
        raise ValueError("randomColumn requires flat nonempty names <=256 characters without reserved output columns")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("randomColumn names must be valid UTF-8") from exc


def validate_random_column_spec(spec):
    if (type(spec) is not dict or set(spec) != _KEYS
            or type(spec["version"]) is not int or spec["version"] != 1
            or spec["operation"] != "random_column" or spec["algorithm"] != ALGORITHM):
        raise ValueError("Unsupported randomColumn specification fields or version")
    _name(spec["column_name"], output=True)
    seed = spec["seed"]
    if type(seed) is not int or not -(2**63) <= seed < 2**63:
        raise ValueError("randomColumn seed must be a signed 64-bit integer")
    if type(spec["distribution"]) is not str or spec["distribution"] not in {"uniform", "normal"}:
        raise ValueError("randomColumn distribution must be uniform or normal")
    keys = spec["row_keys"]
    if type(keys) is not list or len(keys) > 64:
        raise ValueError("randomColumn rowKeys requires0..64 unique flat property names")
    for name in keys:
        _name(name)
    if len(set(keys)) != len(keys):
        raise ValueError("randomColumn rowKeys must be unique")
    if len(encode_spec(spec).encode("utf-8")) > MAX_BYTES:
        raise ValueError("randomColumn operation exceeds16384 UTF-8 bytes")
    return spec


def decode_random_column_spec(text):
    if type(text) is not str or len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("randomColumn operation must be canonical JSON <=16384 bytes")
    return validate_random_column_spec(_parse(text))


def prepare_random_column_spec(column_name="random", seed=0, distribution="uniform", row_keys=None):
    if type(seed) is float and math.isfinite(seed) and seed.is_integer():
        seed = int(seed)
    spec = {"version": 1, "operation": "random_column", "algorithm": ALGORITHM,
            "column_name": column_name, "seed": seed, "distribution": distribution,
            "row_keys": ["system:index"] if row_keys is None else row_keys.copy() if type(row_keys) is list else row_keys}
    validate_random_column_spec(spec)
    return encode_spec(spec)
