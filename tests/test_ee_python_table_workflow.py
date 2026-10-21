"""Versioned SDK -> metadata filter -> OLS -> prediction workflow control."""
import importlib.util
import json
from pathlib import Path

import numpy as np

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


def test_versioned_synthetic_workflow_matches_independent_trend_reference():
    fixture = json.loads((ROOT / "tests/fixtures/ee-table-workflow-v1.json").read_text())
    spec = importlib.util.spec_from_file_location(
        "synthetic_table_example", ROOT / "examples/08_GEE_python_synthetic_regression.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SYNTHETIC_VERSION == fixture["schema"]
    assert module.ROWS == fixture["rows"]
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        outputs = {}
        for name, value in module.build_analysis(ee, fixture["rows"]).items():
            encoded = ee.serializer.encode(value, for_cloud_api=False)
            outputs[name] = compile_expression(encoded, [], {})["value"]
    expected = fixture["independent_reference"]
    assert outputs["sample_count"] == expected["sample_count"]
    assert outputs["temperature_sum"] == expected["temperature_sum"]
    np.testing.assert_allclose(outputs["fit"]["coefficients"], expected["coefficients"], atol=1e-14)
    np.testing.assert_allclose(outputs["fit"]["residuals"], expected["residual_rms"], atol=1e-14)
    np.testing.assert_allclose(outputs["prediction_day_3"], expected["prediction_day_3"], atol=1e-14)
    assert outputs["prediction_formatted"] == expected["prediction_formatted"]
    assert guard.evidence()["attempt_count"] == 0
