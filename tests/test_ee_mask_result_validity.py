"""Arithmetic-result cleanup deliberately differs from strict source validity."""
from __future__ import annotations

from pathlib import Path

import pytest

from engine import ee_mask_weights
from gee.mask_weights_spec import (
    MASK_WEIGHT_ARITIES,
    decode_mask_weights_spec,
    mask_weights_process_spec,
    mask_weights_spec,
)
from ee_sampling_bridge_helpers import _dry_cube


ROOT = Path(__file__).resolve().parents[1]


def test_result_value_is_a_canonical_one_band_operation():
    wire = mask_weights_spec("result_value")

    assert wire == '{"op":"result_value","v":1}'
    assert len(wire) <= 128
    assert decode_mask_weights_spec(wire) == {"op": "result_value", "v": 1}
    assert MASK_WEIGHT_ARITIES["result_value"] == 1
    description = mask_weights_process_spec()["description"]
    assert "result_value" in description and "maps NaN or either Infinity to NoData" in description


def test_result_value_uses_existing_single_band_bridge_and_preserves_trace():
    cube, source, tracer = _dry_cube(bands=("computed",), temporal=True)

    result = ee_mask_weights.local_ee_mask_weights(
        {"data": cube, "spec": mask_weights_spec("result_value")}, env=None
    )

    assert result.metadata.band_names == ["v"]
    assert result.metadata.has_temporal_dimension()
    assert result._traces[0].get_source() is source
    assert result._data_tracer is tracer


def test_result_value_rejects_a_second_operand_band():
    cube, _, _ = _dry_cube(bands=("computed", "other"))

    with pytest.raises(ValueError, match="exactly 1"):
        ee_mask_weights.local_ee_mask_weights(
            {"data": cube, "spec": mask_weights_spec("result_value")}, env=None
        )


def test_result_value_does_not_relax_strict_source_validity():
    numeric = (ROOT / "engine/ee_mask_weights_numeric.scala").read_text(encoding="utf-8")

    assert 'case "validity" => validityWeight' in numeric
    assert 'case "result_value" => finiteResultValue' in numeric
    assert 'require(value.isNaN || value.isFinite' in numeric
    assert "if (value.isFinite) value else Double.NaN" in numeric
