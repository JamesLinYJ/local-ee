"""Static EE control flow may select a direct, still typed explanation output."""
import json

import pytest

from ee_rf_explanation_workflow import ROOT, FIXTURE, example_module
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from gee.graph import validate
from scripts.ee_python_api.offline import OfflineGuard


@pytest.mark.parametrize("control_flow", ["if", "collection_iterate"])
def test_static_control_flow_keeps_exact_direct_explanation_graph(control_flow):
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=ROOT / "vendor/earthengine-js/algorithms.json")
        explanation = example_module().build_workflow(
            ee, json.loads(FIXTURE.read_text()),
        )["explanation"]
        if control_flow == "if":
            selected = ee.Algorithms.If(True, explanation, None)
        else:
            # One compile-time iteration returns the same opaque final value;
            # it does not feed that value into a backend runtime callback.
            selected = ee.FeatureCollection([ee.Feature(None, {"index": 1})]).iterate(
                lambda _feature, _state: explanation, 0,
            )
        compiled = [compile_expression(ee.serializer.encode(value, for_cloud_api=False), [], {})
                    for value in (explanation, selected)]
    assert guard.evidence()["attempt_count"] == 0
    assert compiled[0] == compiled[1]
    assert compiled[1]["kind"] == "runtime_explanation"
    validate(compiled[1]["process_graph"])
