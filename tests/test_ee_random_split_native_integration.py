"""Opt-in trusted Python/JVM random-split integration; no SparkContext or service."""
from __future__ import annotations

import hashlib
import json
import shutil
import os

import pytest

from ee_random_split_native_helpers import (
    AUDIT,
    FIXTURE,
    SCRATCH,
    SCALA_PROBE,
    build_adapters,
    close_gateway,
    compiled_training_spec,
    compile_probe,
    loopback_gateway,
    matrix_array,
    matrix_counts,
    native_artifacts,
    random_column_reference,
    raw_sample_reference,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("LOCAL_EE_RUN_RANDOM_SPLIT_NATIVE_TEST") != "1",
    reason="opt-in authenticated loopback Python/JVM component proof; no SparkContext or service",
)


def test_actual_image_sample_random_filter_and_smile_rf_python_jvm_bridge(monkeypatch, tmp_path):
    java, scala_tools, runtime_jars, py4j_site, py4j_jar = native_artifacts()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    AUDIT.mkdir(parents=True, exist_ok=True)
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    from gee.smile_rf_spec import prepare_rf_parameters

    parameters = prepare_rf_parameters(
        number_of_trees=13, variables_per_split=1, min_leaf_population=1,
        bag_fraction=1.0, max_nodes=4, seed=41,
    )
    rf_spec = compiled_training_spec(fixture, parameters)
    from ee_classified_operations_workflow import compiled_program

    _, post_classify_spec, post_rf_spec, post_operations = compiled_program(fixture, parameters)
    base_jar, base_manifest_path, base_manifest, rf_jar, rf_manifest = build_adapters()
    classes, classpath_paths, compile_stderr = compile_probe(
        java, scala_tools, runtime_jars, base_jar, rf_jar,
    )

    gateway = process = None
    try:
        gateway, process = loopback_gateway(
            monkeypatch, java, py4j_site, py4j_jar, [classes, *classpath_paths],
        )
        raw_rows = json.loads(
            gateway.jvm.ee_random_split_native.SampleProbe().sample(str(FIXTURE))
        )
        assert raw_rows == raw_sample_reference(fixture)

        from engine.ee_process_adapters import local_ee_sample_table_op
        from engine.ee_rf_validation import (
            local_ee_confusion_value,
            local_ee_error_matrix,
            local_ee_smile_rf_classify_samples,
            local_ee_smile_rf_confusion,
        )
        from engine.ee_sampling_result import SampledFeatureTable
        from engine.ee_smile_rf_training import local_ee_train_smile_rf_samples
        from gee.compat.earthengine.ir import Filter
        from gee.image_sampling_spec import prepare_image_sample_spec
        from gee.random_column_spec import prepare_random_column_spec
        from gee.rf_validation_spec import (
            prepare_classify_spec,
            prepare_matrix_spec,
            prepare_metric_spec,
        )
        from gee.sample_table_spec import prepare_sample_filter
        from gee.sampling_spec import decode_sampling_spec, sampling_columns
        from gee.sampling_values import assemble_sample_features
        from gee.smile_rf_spec import prepare_rf_spec

        sample_spec = prepare_image_sample_spec(
            fixture["region"], fixture["band_order"], factor=1.0,
            seed=fixture["options"]["seed"], drop_nulls=True, geometries=True,
        )
        origin = decode_sampling_spec(sample_spec)
        table = SampledFeatureTable(
            assemble_sample_features(origin, raw_rows), sampling_columns(origin),
        )
        table.sample_spec = sample_spec
        table.sample_spec_verified = True
        table.sample_operations = ()
        table.sample_operation_work = 0
        original = table.data
        assert original["properties"] == {"band_order": fixture["band_order"]}
        assert table.columns == ["system:index", "landcover", "reflectance", ".geo"]
        assert [feature["geometry"] for feature in original["features"]] == [
            {"type": "Point", "coordinates": [row["x"], row["y"]]}
            for row in raw_sample_reference(fixture)
        ]

        seed = 29
        random_spec = prepare_random_column_spec(
            column_name="split", seed=seed, distribution="uniform",
            row_keys=["system:index"],
        )
        randomized = local_ee_sample_table_op({"data": table, "spec": random_spec}, env=None)
        assert randomized.columns == ["system:index", "landcover", "reflectance", "split", ".geo"]
        features = randomized.data["features"]
        expected_random = {
            feature["id"]: random_column_reference(feature["id"], seed)
            for feature in original["features"]
        }
        actual_random = {
            feature["id"]: feature["properties"]["split"] for feature in features
        }
        assert actual_random == expected_random
        assert all(0.0 <= value < 1.0 for value in actual_random.values())
        assert table.data == original

        less = Filter("lessThan", {"leftField": "split", "rightValue": 0.5})
        training = local_ee_sample_table_op({
            "data": randomized,
            "spec": prepare_sample_filter(less),
        }, env=None)
        validation = local_ee_sample_table_op({
            "data": randomized,
            "spec": prepare_sample_filter(Filter("not", {"filter": less})),
        }, env=None)
        train_features = training.data["features"]
        validation_features = validation.data["features"]
        all_ids = {feature["id"] for feature in original["features"]}
        train_ids = {feature["id"] for feature in train_features}
        validation_ids = {feature["id"] for feature in validation_features}
        assert train_ids.isdisjoint(validation_ids)
        assert train_ids | validation_ids == all_ids
        assert len(train_features) == len(validation_features) == 16
        assert {int(feature["properties"]["landcover"]) for feature in train_features} == {0, 1}
        assert {int(feature["properties"]["landcover"]) for feature in validation_features} == {0, 1}

        assert rf_spec == prepare_rf_spec(parameters, fixture["band_order"], "landcover")
        model = local_ee_train_smile_rf_samples({"data": training, "spec": rf_spec}, env=None)
        assert model.class_count == 2 and model.training_row_count == len(train_features)
        from py4j.java_gateway import JavaObject

        assert isinstance(model._java_model, JavaObject)
        assert model._java_model.getClass().getName() == "local.ee.smile.LocalEeSmileRfModel"

        def classify(samples):
            columns = [*samples.columns[:-1], "prediction", ".geo"]
            return local_ee_smile_rf_classify_samples({
                "data": samples,
                "spec": prepare_classify_spec("prediction", columns),
                "model": model,
            }, env=None)

        classified_validation = classify(validation)
        validation_matrix = local_ee_error_matrix({
            "data": classified_validation,
            "spec": prepare_matrix_spec("landcover", "prediction", [0, 1]),
        }, env=None)
        actual_validation_matrix = matrix_array(
            validation_matrix, local_ee_confusion_value, prepare_metric_spec,
        )
        expected_validation_matrix = matrix_counts(
            classified_validation.data["features"], "landcover", "prediction",
        )
        assert actual_validation_matrix == expected_validation_matrix
        assert sum(map(sum, actual_validation_matrix)) == len(validation_features)

        classified_training = classify(training)
        training_matrix = local_ee_smile_rf_confusion({"model": model}, env=None)
        actual_training_matrix = matrix_array(
            training_matrix, local_ee_confusion_value, prepare_metric_spec,
        )
        expected_training_matrix = matrix_counts(
            classified_training.data["features"], "landcover", "prediction",
        )
        assert actual_training_matrix == expected_training_matrix
        assert sum(map(sum, actual_training_matrix)) == len(train_features)

        # The new chain consumes the exact specs compiled from the official
        # SDK example and actual rows predicted by a genuine second model.
        # Its explicit predictor list excludes the label, unlike the metadata
        # default exercised above. Synthetic counts still do not prove skill.
        from engine.ee_process_adapters import local_ee_runtime_table_op

        post_model = local_ee_train_smile_rf_samples(
            {"data": training, "spec": post_rf_spec}, env=None,
        )
        assert tuple(post_model.schema) == ("reflectance",)
        classified_all = local_ee_smile_rf_classify_samples({
            "data": randomized, "spec": post_classify_spec, "model": post_model,
        }, env=None)
        before_operations = classified_all.data
        held_out = local_ee_runtime_table_op(
            {"data": classified_all, "spec": post_operations[0]}, env=None,
        )
        assert [row["id"] for row in held_out.data["features"]] == [
            row["id"] for row in validation_features
        ]
        annotated = local_ee_runtime_table_op(
            {"data": held_out, "spec": post_operations[1]}, env=None,
        )
        limited = local_ee_runtime_table_op(
            {"data": annotated, "spec": post_operations[2]}, env=None,
        )
        assert limited.columns == [
            "system:index", "landcover", "reflectance", "split", "prediction", "audit_draw", ".geo",
        ]
        expected_post_rows = before_operations["features"]
        expected_post_rows = [row for row in expected_post_rows
                              if random_column_reference(row["id"], 29) >= 0.5][:8]
        final_rows = limited.data["features"]
        assert len(final_rows) == len(expected_post_rows) == 8
        for actual, original in zip(final_rows, expected_post_rows):
            assert actual["id"] == original["id"]
            assert actual["geometry"] == original["geometry"]
            assert actual["properties"] == {
                **original["properties"],
                "audit_draw": random_column_reference(original["id"], 31),
            }
        assert limited.data["properties"] == {"band_order": fixture["band_order"]}
        assert classified_all.data == before_operations
        post_matrix = local_ee_error_matrix({
            "data": limited, "spec": prepare_matrix_spec("landcover", "prediction", [0, 1]),
        }, env=None)
        post_counts = matrix_array(post_matrix, local_ee_confusion_value, prepare_metric_spec)
        assert post_counts == matrix_counts(final_rows, "landcover", "prediction")
        assert sum(map(sum, post_counts)) == 8
        from uuid import uuid4
        import csv
        from gee.services.ee_runtime_results import read_result, result_context

        job_id = str(uuid4())
        output = tmp_path / "jobs" / job_id / "out"
        output.mkdir(parents=True)
        assets = limited.write_assets(output / "out")
        row = {"id": job_id, "assets": assets, "context": {
            "protocol": "earthengine", **result_context({
                "kind": "runtime_table", "bands": limited.columns,
            }),
        }}
        assert read_result(tmp_path, row) == limited.data
        limited.format = "CSV"
        csv_assets = limited.write_assets(output / "out")
        assert set(csv_assets) == {"openEO.csv"}
        with (output / "openEO.csv").open(newline="") as stream:
            csv_rows = list(csv.DictReader(stream))
        assert len(csv_rows) == 8
        assert list(csv_rows[0]) == limited.columns
        assert [value["system:index"] for value in csv_rows] == [value["id"] for value in final_rows]
        assert [float(value["audit_draw"]) for value in csv_rows] == [
            value["properties"]["audit_draw"] for value in final_rows
        ]

        evidence = {
            "scope": "actual GeoTrellis Image.sample tile kernel -> Python SampledFeatureTable and random/filter split -> real Smile JVM factory, predictions, and confusion counts; authenticated loopback Py4J only; no SparkContext, RDD adapter, service, sandbox, or Google comparison",
            "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
            "probe_sha256": hashlib.sha256(SCALA_PROBE.read_bytes()).hexdigest(),
            "base_adapter_sha256": base_manifest["jar_sha256"],
            "base_manifest_sha256": hashlib.sha256(base_manifest_path.read_bytes()).hexdigest(),
            "rf_adapter_sha256": rf_manifest["jar_sha256"],
            "sample_rows": len(raw_rows),
            "band_order": table.data["properties"]["band_order"],
            "training_schema": list(model.schema),
            "schema_source": "Official SDK omitted inputProperties compiled from declared band_order; exact explicit-input spec comparison passed before JVM startup",
            "random_column_seed": seed,
            "split_rows": {"training": len(train_features), "validation": len(validation_features)},
            "sample_operation_count": len(training.sample_operations),
            "validation_predictions": [
                feature["properties"]["prediction"]
                for feature in classified_validation.data["features"]
            ],
            "validation_matrix": actual_validation_matrix,
            "training_matrix": actual_training_matrix,
            "post_classification": {
                "training_schema": list(post_model.schema),
                "compiled_operations": [json.loads(text) for text in post_operations],
                "actual_rows": [classified_all.row_count, held_out.row_count, annotated.row_count, limited.row_count],
                "columns": limited.columns,
                "matrix": post_counts,
                "independent_ids_random_geometry_metadata": "passed",
                "source_unchanged": classified_all.data == before_operations,
                "physical_json_readback_csv_headers_ids_random": "passed",
            },
            "compile_stderr": compile_stderr,
        }
        (AUDIT / "random-split-native-integration.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        # Keep the exact tested pair before other component builds may reuse
        # the RF builder's fixed scratch directory with a different base JAR.
        for source, name in (
            (base_jar, "random-split-base.jar"),
            (base_manifest_path, "random-split-base.manifest.json"),
            (rf_jar, "random-split-rf.jar"),
            (rf_jar.with_suffix(rf_jar.suffix + ".manifest.json"), "random-split-rf.manifest.json"),
        ):
            shutil.copy2(source, AUDIT / name)
    finally:
        close_gateway(gateway, process)
        if process is not None:
            return_code = process.poll()
            assert return_code is not None, "Owned test gateway must exit before releasing its handle"
            (AUDIT / "random-split-gateway-lifecycle.json").write_text(
                json.dumps({"pid": process.pid, "return_code": return_code,
                            "authenticated_loopback": True, "terminated": True}, indent=2) + "\n",
                encoding="utf-8",
            )
