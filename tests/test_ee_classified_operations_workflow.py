"""Python/JS SDK parity and actual compiled post-classification workflow."""
import json
import shutil
import subprocess

import pytest

from ee_classified_operations_workflow import ROOT, compiled_program
from ee_random_split_parity import JAVASCRIPT, semantic_wire
from gee.ee_translate import compile_expression
from gee.graph import validate
from gee.smile_rf_spec import prepare_rf_parameters


def fixture_and_parameters():
    fixture = json.loads((ROOT / "tests/fixtures/ee-random-split-native-v1.json").read_text())
    return fixture, prepare_rf_parameters(13, 1, 1, 1.0, 4, 41)


def test_example_compiles_classify_first_held_out_filter_annotation_limit_matrix():
    fixture, parameters = fixture_and_parameters()
    results, classify_spec, rf_spec, operations = compiled_program(fixture, parameters)
    assert results["limited"]["kind"] == "runtime_table"
    assert results["matrix_array"]["kind"] == results["accuracy"]["kind"] == "runtime_value"
    assert [json.loads(text)["operation"] for text in operations] == ["filter", "random_column", "limit"]
    assert json.loads(rf_spec)["schema"] == ["reflectance"]
    assert json.loads(classify_spec)["columns"] == [
        "system:index", "landcover", "reflectance", "split", "prediction", ".geo",
    ]
    assert results["limited"]["bands"] == [
        "system:index", "landcover", "reflectance", "split", "prediction", "audit_draw", ".geo",
    ]
    assert all(value["source_item_ids"] == ["wave31-classified-scene"] for value in results.values())


def test_official_javascript_and_python_post_classification_graphs_match():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node required for official JavaScript serialization")
    fixture, parameters = fixture_and_parameters()
    python_results, _, _, _ = compiled_program(fixture, parameters)
    # Reuse the networking-denial bootstrap and pinned signatures only; all
    # workflow expressions below are independently written JavaScript.
    script = JAVASCRIPT.split("const config =", 1)[0] + r"""
const fixture = JSON.parse(fs.readFileSync('tests/fixtures/ee-random-split-native-v1.json'));
const image = ee.Image('wave31-classified-scene').select(fixture.band_order);
const samples = image.sample({
  region: ee.Geometry(fixture.region, 'EPSG:4326', false),
  seed: fixture.options.seed, dropNulls: true, geometries: true
});
const randomized = samples.randomColumn('split', 29);
const training = randomized.filter(ee.Filter.lt('split', 0.5));
const model = ee.Classifier.smileRandomForest(13, 1, 1, 1, 4, 41)
  .train(training, 'landcover', ['reflectance']);
const predictions = randomized.classify(model, 'prediction');
const validation = predictions.filter(ee.Filter.gte('split', 0.5));
const annotated = validation.randomColumn('audit_draw', 31);
const limited = annotated.limit(8);
const matrix = limited.errorMatrix('landcover', 'prediction', [0,1]);
const values = {training, predictions, validation, annotated, limited,
  matrix_array:matrix.array(), accuracy:matrix.accuracy()};
const outputs = Object.fromEntries(Object.entries(values).map(([key,value]) =>
  [key,ee.Serializer.encode(value)]));
if(attempts !== 0) throw Error('unexpected networking');
console.log(JSON.stringify({outputs, attempts}));
"""
    completed = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True,
                               text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["attempts"] == 0
    from ee_classified_operations_workflow import example_module

    metadata = example_module().local_metadata(fixture)
    for key, expression in result["outputs"].items():
        compiled = compile_expression(expression, *metadata)
        validate(compiled["process_graph"])
        assert semantic_wire(compiled) == semantic_wire(python_results[key])
