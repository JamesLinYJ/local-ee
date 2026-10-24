"""Canonical v1 spectral-unmix wire checks."""
import struct

import pytest

from gee.spectral_unmix_spec import (
    decode_spectral_unmix_spec,
    prepare_spectral_unmix_spec,
    spectral_unmix_component_count,
    spectral_unmix_input_count,
    spectral_unmix_process_spec,
)


def test_wire_round_trip_preserves_binary64_bits_and_independent_flags():
    encoded = prepare_spectral_unmix_spec(
        [[1, -0.0], [0.1, 2.0]], sumToOne=True, nonNegative=False,
    )
    assert encoded == (
        '{"endmembers":[["3ff0000000000000","8000000000000000"],'
        '["3fb999999999999a","4000000000000000"]],'
        '"nonNegative":false,"sumToOne":true,"v":1}'
    )
    decoded = decode_spectral_unmix_spec(encoded)
    assert spectral_unmix_component_count(decoded) == 2
    assert spectral_unmix_input_count(decoded) == 2
    assert struct.unpack(">d", bytes.fromhex(decoded["endmembers"][0][1]))[0] == 0.0


@pytest.mark.parametrize("endmembers", [
    [], [[]], [[1] * 9], [[1], [1, 2]], [[True]], [[float("inf")]],
    [[float("nan")]], [[2**53 + 1]], [["1"]],
])
def test_prepare_rejects_bad_shapes_and_nonfinite_or_inexact_coefficients(endmembers):
    with pytest.raises(ValueError):
        prepare_spectral_unmix_spec(endmembers)


@pytest.mark.parametrize("sum_to_one,non_negative", [
    (None, False), (0, False), (False, 1), (False, None),
])
def test_prepare_requires_explicit_boolean_constraints(sum_to_one, non_negative):
    with pytest.raises(ValueError, match="booleans"):
        prepare_spectral_unmix_spec([[1.0]], sum_to_one, non_negative)


@pytest.mark.parametrize("text", [
    '{"v":1,"endmembers":[["3ff0000000000000"]],"sumToOne":false,"nonNegative":false}',
    '{"endmembers":[["3FF0000000000000"]],"nonNegative":false,"sumToOne":false,"v":1}',
    '{"endmembers":[["7ff0000000000000"]],"nonNegative":false,"sumToOne":false,"v":1}',
    '{"endmembers":[[1.0]],"nonNegative":false,"sumToOne":false,"v":1}',
    '{"endmembers":[["3ff0000000000000"]],"nonNegative":false,"sumToOne":false,"v":1 }',
    '{"endmembers":[["3ff0000000000000"]],"nonNegative":false,"sumToOne":false,"v":1,"v":1}',
    '{"endmembers":[["3ff0000000000000"]],"nonNegative":0,"sumToOne":false,"v":1}',
    '{"endmembers":[[NaN]],"nonNegative":false,"sumToOne":false,"v":1}',
])
def test_decode_rejects_noncanonical_duplicate_or_invalid_wire(text):
    with pytest.raises(ValueError):
        decode_spectral_unmix_spec(text)


def test_process_schema_describes_the_shared_float64_cube_contract():
    process = spectral_unmix_process_spec()
    assert process["id"] == "local_ee_unmix"
    assert [parameter["name"] for parameter in process["parameters"]] == ["data", "spec"]
    assert process["parameters"][1]["schema"]["maxLength"] == 8_192
    assert "unmix0.." in process["returns"]["description"]
