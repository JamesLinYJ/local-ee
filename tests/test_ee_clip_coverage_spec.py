"""Canonical bounded geometry wire for the local geodesic clip producer."""
from __future__ import annotations

import json

import pytest

from gee.clip_coverage_spec import (
    MAX_POSITIONS,
    MAX_SPEC_BYTES,
    clip_coverage_process_spec,
    decode_clip_coverage_spec,
    prepare_clip_coverage_spec,
)


def polygon(coordinates=None):
    return {
        "type": "Polygon",
        "coordinates": coordinates or [[
            [10, 20], [11, 20], [11, 21], [10, 21],
        ]],
    }


def test_encoder_closes_rings_and_emits_sorted_compact_float64_positions():
    text = prepare_clip_coverage_spec(polygon())

    assert text == (
        '{"model":"great-circle","polygons":[[[[10.0,20.0],'
        '[11.0,20.0],[11.0,21.0],[10.0,21.0],[10.0,20.0]]]],"version":1}'
    )
    decoded = decode_clip_coverage_spec(text)
    ring = decoded["polygons"][0][0]
    assert ring[0] == ring[-1]
    assert all(type(value) is float for position in ring for value in position)


@pytest.mark.parametrize("bad", [
    '{"version":1,"model":"great-circle","polygons":[]}',
    '{"model":"great-circle","polygons":[],"version":1}',
    '{"model":"great-circle", "polygons":[],"version":1}',
    '{"model":"great-circle","model":"great-circle","polygons":[],"version":1}',
    '{"model":"great-circle","polygons":[],"version":true}',
    '{"model":"great-circle","polygons":[],"version":1.0}',
    '{"model":"great-circle","polygons":[],"version":1}\n',
    '{"model":"great-circle","polygons":[[[[0,0],[1,0],[0,1],[0,0]]]],"version":1}',
])
def test_decoder_rejects_noncanonical_or_invalid_wire(bad):
    with pytest.raises(ValueError):
        decode_clip_coverage_spec(bad)


@pytest.mark.parametrize("coordinates", [
    [[[0, 0], [180, 0], [0, 1], [0, 0]]],
    [[[0, 90], [1, 89], [0, 89], [0, 90]]],
    [[[0, 0], [181, 0], [0, 1], [0, 0]]],
])
def test_encoder_rejects_global_wrap_poles_and_out_of_range_coordinates(coordinates):
    with pytest.raises(ValueError):
        prepare_clip_coverage_spec(polygon(coordinates))


def test_native_wire_caps_and_process_accuracy_boundary_are_explicit():
    over_positions = [[float(index % 160) / 10, 1.0] for index in range(MAX_POSITIONS - 1)]
    over_positions.extend([over_positions[0].copy(), over_positions[1].copy()])
    with pytest.raises(ValueError, match="10000"):
        prepare_clip_coverage_spec(polygon([over_positions]))

    too_large = json.dumps({
        "model": "great-circle", "polygons": [], "version": 1,
        "unused": "x" * MAX_SPEC_BYTES,
    }, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="1000000"):
        decode_clip_coverage_spec(too_large)

    spec = clip_coverage_process_spec()
    assert spec["id"] == "local_ee_clip_coverage"
    assert "1e-6 pixel" in spec["description"]
    assert "not a formal" in spec["description"]
    assert "quantizer" in spec["description"]
