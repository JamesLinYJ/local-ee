"""Official full-formula requests reach actual worker CSV and preserve values."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from ee_measure_reuse_reference import assert_full_csv, assert_full_value
from ee_measure_reuse_sdk import encoded, fixture, original_collection, receipt, wire_hash
from ee_measure_reuse_workflow import (
    SUPPLEMENTAL_CONFIG, export_original, supplemental_ownership_collection,
)
from ee_measures_workflow import require_exact_measure_artifact
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import install


@pytest.mark.parametrize("name", (
    "wgs84_full4", "planar_multipolygon_full6", "planar_geometrycollection_full6",
))
def test_original_full_metric_map_getinfo_and_physical_csv_keep_every_column(
        name, monkeypatch, tmp_path):
    data = fixture()
    before = deepcopy(data)
    record = data["workflows"][name]
    with OfflineGuard() as guard:
        if record["route"] == "default_wgs84":
            require_exact_measure_artifact(monkeypatch)
        integration = install(monkeypatch, tmp_path)
        collection = original_collection(integration.ee, record)
        wire = encoded(integration.ee, collection)
        assert wire == record["wire"]
        value = collection.getInfo()
        assert_full_value(data, record, value)
        evaluate = next(request for request in integration.requests
                        if request["action"] == "evaluate")
        assert evaluate["expression"] == record["wire"]
        rows, evidence = export_original(integration, collection, record)
        assert_full_csv(data, record, rows)
        assert data == before
        evidence.update(
            workflow=name, original_full_formula=True,
            wire_sha256=wire_hash(wire), getinfo=value,
            all_original_columns_validated=True,
            offline_guard=guard.evidence(),
        )
        receipt(f"full-worker-{name}", evidence)
    assert guard.evidence()["attempt_count"] == 0


def test_supplemental_centroid_reuse_keeps_separate_feature_ids_and_nested_properties(
        monkeypatch, tmp_path):
    """Regression-only ownership fixture; never counted as a full-formula gain."""
    data = fixture()
    geometry = data["cases"]["planar_overlapping_multipolygon"]["geometry"]
    expected = next(row for row in data["workflows"]["planar_multipolygon_full6"]["expected_rows"]
                    if row["name"] == "planar_overlapping_multipolygon")["centroid"]
    with OfflineGuard() as guard:
        integration = install(monkeypatch, tmp_path)
        collection = supplemental_ownership_collection(integration.ee, geometry)
        wire = encoded(integration.ee, collection)
        assert wire_hash(wire) == "f3d33f941a807bcadedb49eb9806c0d2a6ccb3529484136c7c987417ce667b26"
        rows, evidence = export_original(
            integration, collection, {"config": SUPPLEMENTAL_CONFIG, "wire": wire},
        )
        assert len(rows) == 2
        assert list(rows[0]) == SUPPLEMENTAL_CONFIG["csv_selectors"]
        for rank, (name, row) in enumerate(zip(("left", "right"), rows, strict=True)):
            assert row["system:index"] == row["source_id"] == f"wave73-owner-{name}"
            assert row["label"] == name
            assert json.loads(row["nested"]) == {"owner": [name], "numbers": [rank, rank + 1]}
            assert json.loads(row["geometry_center"]) == expected
            assert json.loads(row[".geo"]) == {"type": "Point", "coordinates": expected}
        evidence.update(
            supplemental_regression_only=True, original_full_formula=False,
            baseline_already_accepted=True, wire_sha256=wire_hash(wire),
            offline_guard=guard.evidence(),
        )
        receipt("supplemental-ownership-worker", evidence)
    assert guard.evidence()["attempt_count"] == 0
