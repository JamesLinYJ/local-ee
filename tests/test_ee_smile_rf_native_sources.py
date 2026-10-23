"""Portable source and provenance checks for the separate Smile RF adapter."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_smile_dependency_lock_pins_four_primary_maven_artifacts_and_shared_slf4j():
    lock = json.loads((ROOT / "deploy/smile-rf-lock.json").read_text())
    assert lock["format"] == "local-ee-smile-rf-dependency-lock-v1"
    assert lock["implementation"] == "smile-1.5.3"
    assert lock["source"]["repository"] == "https://github.com/haifengl/smile"
    assert lock["source"]["tag"] == "v1.5.3"
    assert lock["source"]["license"] == "Apache-2.0"
    assert lock["source"]["notice_status"] == 404
    assert len(lock["smile_jars"]) == 4
    for filename, artifact in lock["smile_jars"].items():
        assert artifact["url"] == (
            f"https://repo.maven.apache.org/maven2/com/github/haifengl/"
            f"{artifact['coordinate'].split(':')[1]}/1.5.3/{filename}"
        )
        assert len(artifact["sha256"]) == 64
    assert lock["reused_slf4j_api"] == {
        "coordinate": "org.slf4j:slf4j-api:2.0.17",
        "spark_version": "4.2.0",
        "filename": "slf4j-api-2.0.17.jar",
        "sha256": "7b751d952061954d5abfed7181c1f645d336091b679891591d63329c622eb832",
    }


def test_vendored_upstream_license_and_readme_match_fixed_tag_digests():
    lock = json.loads((ROOT / "deploy/smile-rf-lock.json").read_text())
    vendor = ROOT / "vendor/smile-1.5.3"
    assert _sha256(vendor / "LICENSE") == lock["source"]["license_sha256"]
    assert _sha256(vendor / "README.md") == lock["source"]["readme_sha256"]
    notice = (vendor / "NOTICE.md").read_text()
    assert "HTTP 404" in notice
    assert "source JAR" in notice


def test_native_factory_revalidates_bounded_canonical_wire_and_trains_real_smile():
    wire = (ROOT / "engine/ee_smile_rf_wire.scala").read_text()
    factory = (ROOT / "engine/ee_smile_rf_factory.scala").read_text()
    assert 'private val SpecFields = Set(' in wire
    assert '"version", "implementation", "schema", "class_property",' in wire
    for field in ("number_of_trees", "variables_per_split", "min_leaf_population",
                  "bag_fraction", "max_nodes", "seed"):
        assert f'"{field}"' in wire
    assert "STRICT_DUPLICATE_DETECTION" in wire
    assert "MaxSpecBytes = 16384" in wire and "MaxRowsBytes = 1000000" in wire
    assert "MaxNameChars = 256" in wire
    assert "value.codePointCount(0, value.length) <= MaxNameChars" in wire
    assert "parser.getText.length <= MaxNameChars" not in wire
    assert "MaxTrainMagnitude = Double.MaxValue / 2.0" in wire
    assert "MaxTrainingWork = 1000000000L" in wire
    assert "smile.threads" in factory and "getThreadPoolSize() == 1" in factory
    assert "Math.setSeed(checkedSpec.seed.toLong)" in factory
    assert "new RandomForest.Trainer" in factory
    assert ".setNodeSize(checkedSpec.minLeaf)" in factory
    assert ".setSamplingRates(checkedSpec.bagFraction)" in factory
    assert ".setMaxNodes(effectiveLeaves)" in factory
    assert "getTrees" in factory and "maxDepth()" in factory
    assert "ObjectInputStream" not in factory and "readObject" not in factory


def test_feature_validation_factory_keeps_training_rows_and_uses_real_smile_predictions():
    wire = (ROOT / "engine/ee_smile_rf_wire.scala").read_text()
    factory = (ROOT / "engine/ee_smile_rf_factory.scala").read_text()
    probe = (ROOT / "tests/fixtures/ee-smile-rf-validation-kernel-probe.scala").read_text()
    assert "def parseQueryRows(text: String, schemaSize: Int)" in wire
    assert "private def queryNumber(node: JsonNode, row: Int, column: Int)" in wire
    assert "integer.abs <= MaxIntFeature" in wire
    assert "value.isFinite" in wire
    assert "val trainingRows: Vector[Vector[Double]]" in factory
    assert "val trainingLabels: Vector[Int]" in factory
    assert "row.clone().toVector" in factory and "checkedRows.y.toVector" in factory
    assert "def predictRows(model: LocalEeSmileRfModel, rowsText: String): String" in factory
    assert "LocalEeSmileRfNumeric.predictValue(values, model)" in factory
    assert "def confusionMatrix(model: LocalEeSmileRfModel): String" in factory
    assert "LocalEeSmileRfNumeric.predictValue(model.trainingRows(index).toArray, model)" in factory
    assert "resubstitution counts" in factory
    assert "Float64=preserved" in probe
    assert "independent frequency reference" in probe
    assert "invalid_queries" in probe


def test_prediction_uses_actual_smile_forest_preserves_tile_precision_and_masks():
    numeric = (ROOT / "engine/ee_smile_rf_numeric.scala").read_text()
    assert "model.forest.predict(values)" in numeric
    assert "convert(DoubleConstantNoDataCellType)" in numeric
    assert "value.isNaN || value.isFinite" in numeric
    assert "if (!hasNoData)" in numeric
    assert "IntArrayTile(output, cols, rows, IntConstantNoDataCellType)" in numeric
    assert "Float" not in numeric and "toFloat" not in numeric


def test_native_process_reuses_shared_cube_checks_and_applies_actual_depth_budget():
    source = (ROOT / "engine/ee_smile_rf_adapter.scala").read_text()
    assert 'id = "local_ee_smile_rf"' in source
    assert "arguments.size() == 1 && arguments.containsKey(\"model\")" in source
    assert "case value: LocalEeSmileRfModel" in source
    assert "LocalEeClassifyReduceBridge.validate(data, \"local_ee_smile_rf\")" in source
    assert "input.names.toVector == model.schema" in source
    assert "MaxPredictionNodeVisits = 1000000000L" in source
    assert "input.cols.toLong, input.rows.toLong), keyCount)" in source
    assert "pixels, model.maxDepthSum" in source
    assert "keyInGrid" in source
    assert "IntConstantNoDataCellType" in source
    assert "cubeMetadata(input, Seq(\"v\"))" in source
    assert "SparkContext" not in source


def test_independent_builder_is_explicit_sha_checked_offline_and_outside_native_lock():
    source = (ROOT / "scripts/build_smile_rf_adapter.py").read_text()
    assert "--dependencies" in source and "--base-adapter" in source and "--base-manifest" in source
    assert "local-ee-smile-rf-adapter.jar" in source
    assert 'base_adapter' in source and 'manifest_sha256' in source
    assert 'slf4j_api' in source and 'services' in source
    assert 'os.replace(staged_jar, output)' in source
    assert 'urlopen' not in source and 'requests.get' not in source
    assert 'engine-lock.json' in source
    assert 'engine-lock.json"' in source
    assert "WORK_ROOT" in source and ".native" not in source.split("def build(", 1)[1].split("def main", 1)[0]
