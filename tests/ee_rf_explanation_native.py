"""Actual trusted JVM diagnostics with an independent perfect-stump oracle."""
from fractions import Fraction
import hashlib
import json
from uuid import uuid4

from ee_rf_explanation_workflow import FIXTURE, compiled_program


def verify_native_explanation(tmp_path):
    from engine.ee_rf_explanation import local_ee_smile_rf_explain
    from engine.ee_smile_rf_training import local_ee_train_smile_rf_rows
    from gee.services.ee_runtime_results import read_result, result_context

    fixture, compiled, training = compiled_program()
    assert set(training) == {"rows", "spec"}
    model = local_ee_train_smile_rf_rows(training, env=None)
    assert tuple(model.schema) == tuple(fixture["schema"])
    # A class-stratified half sample always retains two rows per class here.
    # Every signal value of class0 is smaller than every class1 value, while
    # the constant feature never splits. All3 bounded2-leaf trees have pure
    # children and the same root Gini reduction regardless of sampled IDs.
    gini = 1 - 2 * Fraction(1, 2) ** 2
    expected = {"importance": {"constant": 0.0, "signal": float(3 * gini)},
                "numberOfTrees": 3, "outOfBagErrorEstimate": 0.0}
    assert expected == fixture["independent_reference"]
    expected_views = {
        "explanation": expected, "importance": expected["importance"],
        "signal": expected["importance"]["signal"], "values": [0.0, 1.5],
        "ordered_values": [1.5, 0.0, 1.5], "tree_count": 3, "oob": 0.0,
        "keys": ["constant", "signal"], "contains_signal": True,
    }
    observed = {}
    for name, descriptor in compiled.items():
        if descriptor["kind"] == "value":
            observed[name] = descriptor["value"]
            assert observed[name] == expected_views[name]
            continue
        result = local_ee_smile_rf_explain({
            "model": model, "spec": descriptor["explanation_spec"],
        }, env=None)
        job_id = str(uuid4())
        output = tmp_path / "jobs" / job_id / "out"
        output.mkdir(parents=True)
        assets = result.write_assets(output / "out")
        row = {"id": job_id, "assets": assets, "context": {
            "protocol": "earthengine", **result_context(descriptor),
        }}
        observed[name] = read_result(tmp_path, row)
        assert observed[name] == expected_views[name]
        assert result.create_flask_response().get_json() == expected_views[name]
    return {
        "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "source": "actual trusted model trained from official SDK compiled rows/spec",
        "schema": list(model.schema), "observed": observed,
        "independent_reference": "Exact Fraction balanced-root Gini1/2, constant cannot split, signal pure children in each of3 stumps; held-out rows always correctly separated",
        "native_and_owned_json_readback": "passed",
        "scope": "Independent fixed-stump numeric proof only; not arbitrary RF/Google tree parity or real-data skill",
    }
