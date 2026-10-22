"""Strict offline random-column wire schema and transformed sample headers."""
import json

import pytest

from ee_sampling_contract_helpers import _sample_object
from gee.random_column_spec import (
    decode_random_column_spec, prepare_random_column_spec, validate_random_column_spec,
)
from gee.sample_table_schema import randomized_columns, sampled_column_lineage, sampled_columns
from gee.sample_table_spec import decode_sample_operation, prepare_sample_limit
from gee.sampling_spec import encode_spec


def test_defaults_canonical_shared_dispatch_and_signed64_seed():
    text = prepare_random_column_spec()
    spec = decode_random_column_spec(text)
    assert spec == {"version": 1, "operation": "random_column", "algorithm": "sha256-rowkeys-v1",
                    "column_name": "random", "seed": 0, "distribution": "uniform",
                    "row_keys": ["system:index"]}
    assert decode_sample_operation(text) == spec
    assert encode_spec(spec) == text
    for seed in (-(2**63), 2**63 - 1):
        assert decode_random_column_spec(prepare_random_column_spec(seed=seed))["seed"] == seed
    assert decode_random_column_spec(prepare_random_column_spec(seed=-7.0))["seed"] == -7
    assert decode_random_column_spec(prepare_random_column_spec(row_keys=[]))["row_keys"] == []


@pytest.mark.parametrize("kwargs", [
    {"seed": True}, {"seed": None}, {"seed": .5}, {"seed": 2**63},
    {"seed": -(2**63)-1}, {"seed": float("inf")},
    {"column_name": ""}, {"column_name": "a.b"}, {"column_name": "system:index"},
    {"column_name": ".geo"}, {"column_name": "a\0b"}, {"column_name": "x"*257},
    {"column_name": "\ud800"}, {"distribution": "gaussian"}, {"distribution": True},
    {"row_keys": ["id", "id"]}, {"row_keys": [".geo"]}, {"row_keys": [False]},
    {"row_keys": "id"}, {"row_keys": [f"k{i}" for i in range(65)]},
])
def test_options_reject_unsupported_types_ranges_names(kwargs):
    with pytest.raises(ValueError):
        prepare_random_column_spec(**kwargs)


@pytest.mark.parametrize("mutation", [
    lambda s:s.update(version=True), lambda s:s.update(seed=1.0),
    lambda s:s.update(algorithm="other"), lambda s:s.update(extra="from_node"),
    lambda s:s.update(row_keys=None), lambda s:s.pop("seed"),
])
def test_wire_never_coerces_or_accepts_unknown_fields(mutation):
    spec = json.loads(prepare_random_column_spec())
    mutation(spec)
    with pytest.raises(ValueError):
        decode_sample_operation(encode_spec(spec))


def test_wire_parser_requires_one_canonical_duplicate_free_bounded_object():
    text = prepare_random_column_spec()
    for bad in (text+" ", text[:-1]+',"seed":0}', text.replace('"seed":0','"seed":NaN'),
                "x"*16385):
        with pytest.raises(ValueError):
            decode_random_column_spec(bad)
    spec = json.loads(text)
    spec["row_keys"] = [f"k{i}"+"😀"*250 for i in range(30)]
    with pytest.raises(ValueError,match="16384"):
        validate_random_column_spec(spec)


def test_schema_new_overwritten_and_dependent_columns_retain_header_order():
    origin = _sample_object(bands=["nir","red"],properties=["label"])
    operations = (
        prepare_random_column_spec("split"), prepare_random_column_spec("red",row_keys=["split"]),
        prepare_sample_limit(3), prepare_random_column_spec("split",distribution="normal",row_keys=["red"]),
    )
    columns, changed = sampled_column_lineage(origin, operations)
    assert columns == ["system:index","label","nir","red","split",".geo"]
    assert changed == {"split":"normal","red":"uniform"}
    assert randomized_columns(operations) == {"split","red"}
    assert sampled_columns(origin) == ["system:index","label","nir","red",".geo"]
    with pytest.raises(ValueError,match="rowKeys"):
        sampled_columns(origin,[prepare_random_column_spec(row_keys=["missing"])])
    with pytest.raises(ValueError,match="at most16"):
        sampled_columns(origin,[prepare_sample_limit(1)]*17)


def test_schema_column_limit_still_allows_overwrite_at_the_limit():
    names=[f"p{i}" for i in range(190)]
    bands=[f"b{i}" for i in range(64)]
    origin=_sample_object(properties=names,bands=bands)
    assert len(sampled_columns(origin,[prepare_random_column_spec("b0")])) == 256
    with pytest.raises(ValueError,match="256"):
        sampled_columns(origin,[prepare_random_column_spec()])
