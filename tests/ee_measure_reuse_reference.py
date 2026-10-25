"""Check every original metric column against frozen independent references."""
from __future__ import annotations

import json
import math

import pytest


def _coordinates(value):
    return json.loads(value) if isinstance(value, str) else value


def _scalar_bound(data, workflow, expected, method):
    reference = expected.get("control_ids", {}).get(method)
    if workflow["route"] == "default_wgs84" and reference is not None:
        record = data["frozen_wgs84_controls"][reference]
        return max(record["absolute_tolerance"],
                   record["relative_tolerance"] * abs(record["expected"]))
    tolerance = data["tolerances"]["planar_and_zero_scalars"]
    return max(tolerance["absolute"], tolerance["relative"] * abs(expected["metrics"][method]))


def assert_properties(data, workflow, properties, expected, *, csv=False):
    selectors = workflow["config"]["csv_selectors"]
    expected_keys = set(selectors if csv else selectors[:-1])
    assert set(properties) == expected_keys
    assert properties["system:index"] == expected["id"]
    assert properties["feature_id"] == expected["id"]
    assert properties["label"] == expected["name"]
    assert int(properties["source_rank"]) == expected["source_rank"]
    modes = ("default", "null") if workflow["route"] == "default_wgs84" else ("epsg4326",)
    for method in ("area", "length", "perimeter"):
        wanted = expected["metrics"][method]
        for owner in ("geometry", "feature"):
            for mode in modes:
                name = f"{owner}_{method}_{mode}"
                value = float(properties[name])
                assert math.isfinite(value)
                assert abs(value - wanted) <= _scalar_bound(data, workflow, expected, method), (
                    expected["name"], name, value, wanted,
                )
    centroid_mode = "default" if workflow["route"] == "default_wgs84" else "epsg4326"
    tolerance = data["tolerances"]["centroid_property"]
    for owner in ("geometry", "feature"):
        actual = _coordinates(properties[f"{owner}_centroid_{centroid_mode}"])
        assert actual == pytest.approx(expected["centroid"], rel=tolerance["relative"],
                                       abs=tolerance["absolute"])


def assert_point(data, geometry, expected):
    assert set(geometry) == {"type", "coordinates"}
    assert geometry["type"] == "Point"
    tolerance = data["tolerances"]["centroid_output_geometry"]
    assert geometry["coordinates"] == pytest.approx(
        expected["centroid"], rel=tolerance["relative"], abs=tolerance["absolute"],
    )


def assert_full_value(data, workflow, value):
    assert value["type"] == "FeatureCollection"
    rows = value["features"]
    assert len(rows) == workflow["config"]["rows"] == len(workflow["expected_rows"])
    for row, expected in zip(rows, workflow["expected_rows"], strict=True):
        assert row["type"] == "Feature"
        assert_properties(data, workflow, row["properties"], expected)
        assert_point(data, row["geometry"], expected)


def assert_full_csv(data, workflow, rows):
    assert len(rows) == workflow["config"]["rows"] == len(workflow["expected_rows"])
    assert list(rows[0]) == workflow["config"]["csv_selectors"]
    for row, expected in zip(rows, workflow["expected_rows"], strict=True):
        assert_properties(data, workflow, row, expected, csv=True)
        assert_point(data, json.loads(row[".geo"]), expected)
