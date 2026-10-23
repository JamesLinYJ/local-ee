"""Official SDK parity, independent stump expectation and closed DAG edges."""
from copy import deepcopy
from fractions import Fraction
import json
import shutil
import subprocess

import pytest

from ee_random_split_parity import JAVASCRIPT, semantic_wire
from ee_rf_explanation_workflow import ROOT, compiled_program
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.rf_explanation_processes import RF_EXPLAIN
from gee.rf_explanation_spec import prepare_explanation_spec
from test_ee_rf_validation_processes import program


def explanation_graph():
    nodes = program()
    nodes["value"].pop("result")
    nodes["explain"] = {"process_id": RF_EXPLAIN, "arguments": {
        "model": {"from_node": "model"},
        "spec": prepare_explanation_spec(["x"], 3),
    }, "result": True}
    return nodes


def test_independent_perfect_stump_gini_and_compiled_three_field_workflow():
    fixture, results, training = compiled_program()
    left = [row for row in fixture["rows"] if row["label"] == 0]
    right = [row for row in fixture["rows"] if row["label"] == 1]
    assert len(left) == len(right) == 4
    assert max(row["signal"] for row in left) < min(row["signal"] for row in right)
    assert {row["constant"] for row in fixture["rows"]} == {7}
    assert 1 - 2 * Fraction(1, 2) ** 2 == Fraction(1, 2)
    assert fixture["independent_reference"]["importance"]["signal"] == 3 * Fraction(1, 2)
    assert json.loads(training["spec"])["schema"] == fixture["schema"]
    assert {key: value["kind"] for key, value in results.items()} == {
        key: "value" if key in {"keys", "contains_signal"} else "runtime_explanation"
        for key in results
    }


@pytest.mark.parametrize("source", ["matrix", "table", "training", "value"])
def test_explanation_requires_exact_direct_trainer(source):
    nodes = explanation_graph()
    nodes["explain"]["arguments"]["model"] = {"from_node": source}
    with pytest.raises(ValueError, match="trainer|model parameter"):
        validate(nodes)


@pytest.mark.parametrize("schema,trees", [(["other"], 3), (["x"], 4)])
def test_explanation_cannot_forge_model_schema_or_tree_count(schema, trees):
    nodes = explanation_graph()
    nodes["explain"]["arguments"]["spec"] = prepare_explanation_spec(schema, trees)
    with pytest.raises(ValueError, match="schema/tree count"):
        validate(nodes)


@pytest.mark.parametrize("format", ["CSV", "GTiff", "NetCDF"])
def test_explanation_is_json_only(format):
    nodes = explanation_graph()
    nodes["explain"].pop("result")
    nodes["sink"] = {"process_id": "save_result", "arguments": {
        "data": {"from_node": "explain"}, "format": format}, "result": True}
    with pytest.raises(ValueError, match="JSON only|JSON output"):
        validate(nodes)


@pytest.mark.parametrize("nested", [False, True])
def test_explanation_cannot_escape_to_generic_scalar_math_or_container(nested):
    nodes = explanation_graph()
    nodes["explain"].pop("result")
    ref = {"from_node": "explain"}
    nodes["sum"] = {"process_id": "add", "arguments": {
        "x": [ref] if nested else ref, "y": 1}, "result": True}
    with pytest.raises(ValueError, match="direct JSON output"):
        validate(nodes)
    allowed = explanation_graph()
    allowed["explain"].pop("result")
    allowed["sink"] = {"process_id": "save_result", "arguments": {
        "data": {"from_node": "explain"}, "format": "JSON"}, "result": True}
    validate(allowed)


def test_explanation_process_in_callback_or_with_extra_fields_rejects():
    nodes = explanation_graph()
    nodes["explain"]["arguments"]["url"] = "https://invalid.invalid"
    with pytest.raises(ValueError, match="exact top-level"):
        validate(nodes)
    callback = explanation_graph()
    nodes = {"load": {"process_id": "load_collection", "arguments": {"id": "local"}},
             "apply": {"process_id": "apply", "arguments": {
                 "data": {"from_node": "load"}, "process": {"process_graph": callback}}, "result": True}}
    with pytest.raises(ValueError, match="top-level"):
        validate(nodes)


def test_python_and_javascript_explanation_queries_compile_to_same_graphs():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for pinned JavaScript serialization")
    _, python_results, _ = compiled_program()
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const f = JSON.parse(fs.readFileSync('tests/fixtures/ee-rf-explanation-v1.json'));
const rows = ee.FeatureCollection(f.rows.map(row => ee.Feature(null,row)));
const p = f.parameters;
const model = ee.Classifier.smileRandomForest(p.number_of_trees,p.variables_per_split,
 p.min_leaf_population,p.bag_fraction,p.max_nodes,p.seed).train(rows,f.class_property,f.schema);
const explanation = model.explain();
const importance = ee.Dictionary(explanation.get('importance'));
const values = {explanation,importance,signal:importance.get('signal'),
 values:importance.values(),ordered_values:importance.values(['signal','constant','signal']),
 tree_count:explanation.get('numberOfTrees'),oob:explanation.get('outOfBagErrorEstimate'),
 keys:importance.keys(),contains_signal:importance.contains('signal')};
const outputs = Object.fromEntries(Object.entries(values).map(([key,value]) =>
 [key,ee.Serializer.encode(value)]));
if(attempts !== 0) throw Error('unexpected networking');
console.log(JSON.stringify({outputs,attempts}));
"""
    result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True,
                            text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["attempts"] == 0
    for key, expression in data["outputs"].items():
        compiled = compile_expression(expression, [], {})
        if "process_graph" in compiled:
            validate(compiled["process_graph"])
        assert semantic_wire(compiled) == semantic_wire(python_results[key])
