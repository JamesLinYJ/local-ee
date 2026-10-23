"""Read actual model importance and diagnostics; fixed synthetic fixture.

The three-field local explanation uses Smile1.5.3 raw diagnostics. It does not
establish Google tree/RNG/OOB equivalence or predictive skill on research data.
"""
from __future__ import annotations

import json
from pathlib import Path


def build_workflow(ee, fixture):
    features = ee.FeatureCollection([ee.Feature(None, row) for row in fixture["rows"]])
    parameters = fixture["parameters"]
    model = ee.Classifier.smileRandomForest(*[
        parameters[key] for key in (
            "number_of_trees", "variables_per_split", "min_leaf_population",
            "bag_fraction", "max_nodes", "seed",
        )
    ]).train(features, fixture["class_property"], fixture["schema"])
    explanation = model.explain()
    importance = ee.Dictionary(explanation.get("importance"))
    return {
        "explanation": explanation,
        "importance": importance,
        "signal": importance.get("signal"),
        "values": importance.values(),
        "ordered_values": importance.values(["signal", "constant", "signal"]),
        "tree_count": explanation.get("numberOfTrees"),
        "oob": explanation.get("outOfBagErrorEstimate"),
        "keys": importance.keys(),
        "contains_signal": importance.contains("signal"),
    }


def main():
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from gee.graph import validate
    from scripts.ee_python_api.offline import OfflineGuard

    fixture = json.loads((root / "tests/fixtures/ee-rf-explanation-v1.json").read_text())
    with OfflineGuard() as guard:
        ee = configure_local_ee("http://127.0.0.1:8787/openeo/1.2", "a" * 48,
                                signatures_path=root / "vendor/earthengine-js/algorithms.json")
        results = {name: compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), [], {},
        ) for name, value in build_workflow(ee, fixture).items()}
    for value in results.values():
        if "process_graph" in value:
            validate(value["process_graph"])
    assert guard.evidence()["attempt_count"] == 0
    print(json.dumps({"kinds": {key: value["kind"] for key, value in results.items()},
                      "network_attempts": 0, "fitted_or_deployed": False}, indent=2))


if __name__ == "__main__":
    main()
