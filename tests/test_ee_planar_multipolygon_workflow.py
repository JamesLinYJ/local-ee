"""Original full-formula references and unchanged-MultiPolygon CSV evidence."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from ee_measures_workflow import load_fixture, physical_measurement_collection
from ee_multipolygon_reference import numeric_expected
from ee_multipolygon_sdk import (
    configured_ee, encoded, fixture, receipt, targeted_collection, wire_hash,
)
from ee_multipolygon_workflow import export_and_read
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from table_export_support import install
from ee_measure_reuse_reference import assert_full_value
from ee_measure_reuse_sdk import fixture as reuse_fixture


def test_original_sixrow_planar_formula_keeps_exact_wire_and_all_reference_values():
    data = fixture()
    original = data["original_sixrow_planar_formula"]
    with OfflineGuard() as guard:
        ee = configured_ee()
        collection = physical_measurement_collection(ee, load_fixture(), original["route"])
        wire = encoded(ee, collection)
        assert wire == original["wire"]
        assert wire_hash(wire) == original["canonical_wire_sha256"]
        observed = {"wire_sha256": wire_hash(wire), "rows": original["rows"],
                    "original_error": original["error"], "formula_unchanged": True}
        try:
            observed["value"] = compile_expression(wire, [], {})["value"]
            observed["accepted"] = True
        except UnsupportedEEError as error:
            observed.update(accepted=False, error=type(error).__name__ + ": " + str(error))
        observed["offline_guard"] = guard.evidence()
        receipt("original-sixrow-current", observed)
        assert observed["accepted"], observed.get("error")
        frozen = reuse_fixture()
        record = frozen["workflows"]["planar_multipolygon_full6"]
        assert wire == record["wire"]
        assert_full_value(frozen, record, observed["value"])
    assert guard.evidence()["attempt_count"] == 0


def _assert_original_feature(actual, name, case, rank):
    assert actual["type"] == "Feature"
    assert actual["geometry"] == case["geometry"]
    properties = actual["properties"]
    assert properties["label"] == name
    assert properties["source_rank"] == rank
    assert properties["nested"] == {"labels": [name, "preserved"], "rank": rank}
    assert properties["system:index"] == f"wave72-{name}"
    assert properties["feature_id"] == f"wave72-{name}"
    for method in ("area", "length", "perimeter", "centroid"):
        assert properties[method] == pytest.approx(
            numeric_expected(case["reference"], method), rel=2e-12, abs=2e-12,
        )


def test_targeted_feature_map_retains_multipolygon_ids_properties_through_worker_csv(
        monkeypatch, tmp_path):
    data = fixture()
    before = deepcopy(data)
    config = data["targeted_workflow"]
    with OfflineGuard() as guard:
        integration = install(monkeypatch, tmp_path)
        collection = targeted_collection(integration.ee, data)
        wire = encoded(integration.ee, collection)
        # Actual official getInfo adapter reaches in-process service dispatch.
        values = collection.getInfo()
        assert values["type"] == "FeatureCollection"
        names = config["input_features"]
        assert len(values["features"]) == len(names) == config["rows"] == 2
        for rank, (name, feature) in enumerate(zip(names, values["features"], strict=True)):
            _assert_original_feature(feature, name, data["cases"][name], rank)

        rows, evidence = export_and_read(integration, collection, config)
        evidence.update(offline_guard=guard.evidence(), sdk_wire=wire,
                        sdk_wire_sha256=wire_hash(wire), sdk_getinfo=values,
                        workflow="separate targeted two-row original MultiPolygon formula",
                        historical_sixrow_formula_is_not_this_workflow=True)
        receipt("targeted-worker-observed", evidence)
        assert len(rows) == config["rows"]
        assert list(rows[0]) == config["selectors"]
        for rank, (name, row) in enumerate(zip(names, rows, strict=True)):
            case = data["cases"][name]
            assert row["system:index"] == f"wave72-{name}"
            assert row["feature_id"] == f"wave72-{name}"
            assert row["label"] == name
            assert int(row["source_rank"]) == rank
            assert json.loads(row["nested"]) == {"labels": [name, "preserved"], "rank": rank}
            # The unchanged EE CSV boundary materializes effective polygon
            # parity before typed sidecars are lost in ordinary job JSON.
            output_geometry = json.loads(row[".geo"])
            assert output_geometry == {**case["geometry"], "evenOdd": True}
            assert output_geometry["type"] == "MultiPolygon"
            for method in ("area", "length", "perimeter"):
                assert float(row[method]) == pytest.approx(
                    numeric_expected(case["reference"], method), rel=2e-12, abs=2e-12,
                )
            assert json.loads(row["centroid"]) == pytest.approx(
                numeric_expected(case["reference"], "centroid"), rel=2e-12, abs=2e-12,
            )
        receipt("targeted-worker-readback", {**evidence, "assertions_passed": True})
    assert data == before
    assert guard.evidence()["attempt_count"] == 0
