"""Exact original full formulas compute within the unchanged shared budget."""
from __future__ import annotations

from copy import deepcopy

import pytest

from ee_measure_reuse_reference import assert_full_value
from ee_measure_reuse_sdk import (
    configured_ee, encoded, fixture, javascript_wires, original_collection,
    receipt, wire_hash,
)
from ee_measures_workflow import require_exact_measure_artifact
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


WORKFLOWS = ("wgs84_full4", "planar_multipolygon_full6",
             "planar_geometrycollection_full6")


@pytest.mark.parametrize("name", WORKFLOWS)
@pytest.mark.parametrize("client", ("python", "javascript"))
def test_exact_original_full_client_formula_matches_all_independent_references(
        name, client, monkeypatch):
    data = fixture()
    before = deepcopy(data)
    record = data["workflows"][name]
    with OfflineGuard() as guard:
        if record["route"] == "default_wgs84":
            require_exact_measure_artifact(monkeypatch)
        if client == "python":
            ee = configured_ee()
            wire = encoded(ee, original_collection(ee, record))
            assert wire == record["wire"]
            assert wire_hash(wire) == record["canonical_wire_sha256"]
        else:
            # The JS WGS84 wire retains explicit null arguments. The helper
            # pins its distinct raw hash before this unmodified compilation.
            wire = javascript_wires(data)[name]
        original_wire = deepcopy(wire)
        result = compile_expression(wire, [], {})
        assert result["kind"] == "value"
        assert_full_value(data, record, result["value"])
        assert wire == original_wire
        assert data == before
        evidence = guard.evidence()
        receipt(f"full-value-{client}-{name}", {
            "client": client, "wire_sha256": wire_hash(wire),
            "source_wire_unchanged": True, "accepted": True,
            "all_original_columns_validated": True,
            "baseline_error": record["error"], "value": result["value"],
            "offline_guard": evidence,
            "javascript_network_attempts": 0 if client == "javascript" else None,
        })
    assert evidence["attempt_count"] == 0
