"""Independent area controls across the local integration chart switch."""
from pathlib import Path
import hashlib
import json

import pytest

from ee_measures_workflow import ROOT, require_exact_measure_artifact
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


FIXTURE = Path(__file__).with_name("fixtures") / "ee-geometry-measures-chart-boundaries-v1.json"
RAW = FIXTURE.read_bytes()
assert hashlib.sha256(RAW).hexdigest() == (
    "acc95efa167023eee686bc7d48872f8e11b5693effe610ee3d3304f95d39fc1b"
)
CONTROLS = json.loads(RAW)["records"]


@pytest.mark.parametrize("record", CONTROLS, ids=lambda item: item["id"])
def test_area_chart_switch_matches_independent_decimal_reference(monkeypatch, record):
    require_exact_measure_artifact(monkeypatch)
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        expression = ee.Geometry(record["geometry"]).area()
        wire = ee.serializer.encode(expression, for_cloud_api=False)
        actual = compile_expression(wire, [], {})
    assert guard.evidence()["attempt_count"] == 0
    assert actual["kind"] == "value"
    assert actual["value"] == pytest.approx(
        record["expected"], rel=record["relative_tolerance"],
        abs=record["absolute_tolerance"],
    )
