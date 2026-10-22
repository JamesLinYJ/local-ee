"""Official SDK PCA workflow compared with closed-form two-variable results."""
import importlib.util
import json
from pathlib import Path

import numpy as np

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]


def test_versioned_static_pca_matches_closed_form_covariance_and_components():
    fixture = json.loads((ROOT / "tests/fixtures/ee-pca-table-v1.json").read_text())
    spec = importlib.util.spec_from_file_location(
        "pca_example", ROOT / "examples/10_GEE_python_synthetic_pca.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SYNTHETIC_VERSION == fixture["schema"]
    assert module.ROWS == fixture["observations"]
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        outputs = {name: compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})["value"]
                   for name, value in module.build_pca(ee, fixture["observations"]).items()}
    reference = fixture["independent_reference"]
    for name in ("means", "covariance", "eigenvalues", "eigenvectors", "scores", "score_covariance"):
        np.testing.assert_allclose(outputs[name], reference[name], rtol=1e-14, atol=1e-14)
    np.testing.assert_allclose(outputs["reconstructed_samples"], fixture["observations"], atol=1e-14)
    # Eigenbasis signs follow the documented local rule. Covariance off-diagonal
    # zero and reconstruction additionally check the sign-independent result.
    assert abs(outputs["score_covariance"][0][1]) < 1e-14
    assert abs(outputs["score_covariance"][1][0]) < 1e-14
    assert guard.evidence()["attempt_count"] == 0
