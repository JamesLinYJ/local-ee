"""RF feature-workflow graph and independent validation reference tests."""
from __future__ import annotations

import json

import pytest

from ee_rf_validation_parity import (
    confusion_from_raw_rows, exact_metrics, expanded_matrix_rows,
)
from ee_rf_validation_workflow_helpers import (
    ACCESSOR_OPERATION, CONFUSION_VALUE, ERROR_MATRIX,
    RF_CLASSIFY_ROWS, RF_CLASSIFY_SAMPLES, RF_CONFUSION, RF_ROWS, RF_SAMPLES,
    ROOT, SAMPLE, SAMPLE_OP, compile_cross_sdk_workflows, compile_value, encode,
    example_module, javascript_workflows, load_fixture, local_metadata, make_ee,
    nodes, semantic_wire, trainer_nodes as _trainer_nodes,
    compile_workflow as _compile_workflow,
)
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from gee.smile_rf_spec import decode_rf_spec
from scripts.ee_python_api.offline import OfflineGuard


def test_example_compiles_training_and_validation_outputs_without_fitting():
    module = example_module()
    with OfflineGuard() as guard:
        compiled = module.compile_workflows(make_ee(), ROOT)
    assert guard.evidence()["attempt_count"] == 0
    assert compiled["fitted"] is False
    assert set(compiled["workflows"]) == {"inline", "sampled"}
    for mode, outputs in compiled["workflows"].items():
        assert {
            "training_predictions", "validation_predictions",
            *[f"training_{name}" for name in ACCESSOR_OPERATION],
            *[f"validation_{name}" for name in ACCESSOR_OPERATION],
        } == set(outputs)
        assert outputs["training_predictions"]["kind"] == "runtime_table"
        assert outputs["validation_predictions"]["kind"] == "runtime_table"
        assert all(outputs[f"training_{name}"]["kind"] == "runtime_value"
                   for name in ACCESSOR_OPERATION)
        assert all(outputs[f"validation_{name}"]["kind"] == "runtime_value"
                   for name in ACCESSOR_OPERATION)
        assert nodes(
            outputs["training_predictions"]["process_graph"],
            RF_CLASSIFY_ROWS if mode == "inline" else RF_CLASSIFY_SAMPLES,
        )
        assert nodes(
            outputs["validation_predictions"]["process_graph"],
            RF_CLASSIFY_ROWS,
        )


@pytest.mark.parametrize(
    "mode,training_process,training_classify,validation_classify,sample_operations",
    [
    ("inline", RF_ROWS, RF_CLASSIFY_ROWS, RF_CLASSIFY_ROWS, 0),
    ("sampled", RF_SAMPLES, RF_CLASSIFY_SAMPLES, RF_CLASSIFY_ROWS, 3),
    ],
)
def test_feature_prediction_and_validation_accessors_use_runtime_graph(
    mode, training_process, training_classify, validation_classify, sample_operations,
):
    data = load_fixture()
    module = example_module()
    metadata = local_metadata(data)
    with OfflineGuard() as guard:
        ee = make_ee()
        workflow, descriptors = _compile_workflow(ee, module, data, metadata, mode)
    assert guard.evidence()["attempt_count"] == 0

    training_table = descriptors["training_predictions"]
    validation_table = descriptors["validation_predictions"]
    assert training_table["kind"] == validation_table["kind"] == "runtime_table"
    for descriptor in (training_table, validation_table):
        validate(descriptor["process_graph"])

    runtime_table = nodes(validation_table["process_graph"], validation_classify)
    assert len(runtime_table) == 1
    training_runtime_table = nodes(training_table["process_graph"], training_classify)
    assert len(training_runtime_table) == 1
    training_ids, sample_ids = _trainer_nodes(validation_table["process_graph"])
    assert len(nodes(validation_table["process_graph"], training_process)) == 1
    assert len(training_ids) == (1 if training_process == RF_ROWS else 0)
    assert len(sample_ids) == (1 if training_process == RF_SAMPLES else 0)
    assert nodes(
        validation_table["process_graph"],
        RF_CLASSIFY_SAMPLES if validation_classify == RF_CLASSIFY_ROWS else RF_CLASSIFY_ROWS,
    ) == []
    prediction_args = runtime_table[0][1]["arguments"]
    trainer_id, _ = nodes(validation_table["process_graph"], training_process)[0]
    assert prediction_args["model"] == {"from_node": trainer_id}
    training_graph = training_table["process_graph"]
    training_args = training_runtime_table[0][1]["arguments"]
    training_model_id, _ = nodes(training_graph, training_process)[0]
    assert training_args["model"] == {"from_node": training_model_id}

    class_spec = json.loads(prediction_args["spec"])
    assert class_spec["output_name"] == data["output_name"]
    assert class_spec["columns"] == [
        "system:index", "nir", "red", "class_id", "site",
        data["output_name"], ".geo",
    ]
    assert "value" not in validation_table
    assert "value" not in training_table
    decoded_model = decode_rf_spec(nodes(training_graph, training_process)[0][1]["arguments"]["spec"])
    assert decoded_model["schema"] == data["input_properties"]
    assert decoded_model["class_property"] == data["class_property"]
    assert decoded_model["implementation"] == "smile-1.5.3"
    assert {
        key: decoded_model[key] for key in data["classifier_parameters"]
    } == data["classifier_parameters"]

    validation_value_graphs = descriptors["validation_values"]
    assert set(validation_value_graphs) == {
        "array", "order", "accuracy", "kappa", "consumers_accuracy",
        "producers_accuracy", "fscore_beta_2",
    }
    for name, descriptor in validation_value_graphs.items():
        graph = descriptor["process_graph"]
        validate(graph)
        assert descriptor["kind"] == "runtime_value"
        assert "value" not in descriptor
        error_nodes = nodes(graph, ERROR_MATRIX)
        accessor_nodes = nodes(graph, CONFUSION_VALUE)
        assert len(error_nodes) == len(accessor_nodes) == 1
        matrix_id, matrix_node = error_nodes[0]
        assert matrix_node["arguments"]["data"] == {"from_node": runtime_table[0][0]}
        assert accessor_nodes[0][1]["arguments"]["data"] == {"from_node": matrix_id}
        spec = json.loads(matrix_node["arguments"]["spec"])
        assert spec == {
            "version": 1, "actual": data["class_property"],
            "predicted": data["output_name"], "order": data["class_order"],
        }
        assert (json.loads(accessor_nodes[0][1]["arguments"]["spec"])["operation"]
                == ACCESSOR_OPERATION[name])

    training_value_graphs = descriptors["training_values"]
    assert set(training_value_graphs) == set(ACCESSOR_OPERATION)
    for name, descriptor in training_value_graphs.items():
        graph = descriptor["process_graph"]
        validate(graph)
        assert descriptor["kind"] == "runtime_value"
        assert "value" not in descriptor
        confusion_nodes = nodes(graph, RF_CONFUSION)
        accessor_nodes = nodes(graph, CONFUSION_VALUE)
        assert len(confusion_nodes) == len(accessor_nodes) == 1
        assert nodes(graph, ERROR_MATRIX) == []
        assert accessor_nodes[0][1]["arguments"]["data"] == {
            "from_node": confusion_nodes[0][0],
        }
        assert (json.loads(accessor_nodes[0][1]["arguments"]["spec"])["operation"]
                == ACCESSOR_OPERATION[name])
        assert len(nodes(graph, training_process)) == 1
        assert len(nodes(graph, SAMPLE)) == int(sample_operations > 0)
        assert len(nodes(graph, SAMPLE_OP)) == sample_operations

    if mode == "sampled":
        graph = validation_table["process_graph"]
        sample_nodes = nodes(graph, SAMPLE)
        operation_nodes = nodes(graph, SAMPLE_OP)
        assert len(sample_nodes) == 1
        assert len(operation_nodes) == sample_operations
        sample_node = sample_nodes[0][1]
        sample_wire = json.loads(sample_node["arguments"]["spec"])
        assert sample_wire["grid"] == {"scale": data["training_scale"], "crs": None}
        operations = [json.loads(node["arguments"]["spec"])["operation"]
                      for _, node in operation_nodes]
        assert operations == ["filter", "filter", "limit"]
        assert sample_node["arguments"]["data"]["from_node"]

    export = ee.batch.Export.table.toDrive(
        collection=workflow["validation_predictions"],
        description=f"rf_validation_{mode}",
        fileNamePrefix=f"rf_validation_{mode}",
        fileFormat="CSV",
        selectors=data["export_selectors"],
    )
    from gee.ee_python_exports import local_options

    export_request = local_options(
        ee, "export_table", export.config.copy(), lambda value: encode(ee, value),
    )
    assert export_request["options"]["selectors"] == data["export_selectors"]
    export_descriptor = compile_expression(
        encode(ee, export_request["expression"]), *metadata,
    )
    assert export_descriptor["kind"] == "runtime_table"
    assert nodes(export_descriptor["process_graph"], validation_classify)


def test_independent_raw_frequency_and_fraction_reference_covers_order_and_missing_rows():
    data = load_fixture()["matrix_reference"]
    rows = expanded_matrix_rows(data)
    expected = data["expected"]
    complete, evaluated, matrix = confusion_from_raw_rows(rows, data["order"])
    metrics = exact_metrics(matrix)

    assert complete == expected["complete_rows"] == 18
    assert evaluated == expected["evaluated_rows"] == 17
    assert matrix == expected["matrix"]
    assert str(metrics["accuracy"]) == expected["accuracy"]
    assert str(metrics["kappa"]) == expected["kappa"]
    assert [str(value) for value in metrics["consumers_accuracy"]] == expected["consumers_accuracy"]
    assert [str(value) for value in metrics["producers_accuracy"]] == expected["producers_accuracy"]
    assert [str(value) for value in metrics["fscore_beta_2"]] == expected["fscore_beta_2"]


def test_empty_and_zero_denominator_references_do_not_invent_metric_values():
    data = load_fixture()
    empty = data["empty_matrix_reference"]
    complete, evaluated, matrix = confusion_from_raw_rows(empty["rows"], empty["order"])
    assert (complete, evaluated, matrix) == (0, 0, [[0, 0], [0, 0]])
    metrics = exact_metrics(matrix)
    assert metrics == {
        "accuracy": None, "kappa": None,
        "consumers_accuracy": [None, None],
        "producers_accuracy": [None, None],
        "fscore_beta_2": [None, None],
    }

    zero = data["zero_denominator_reference"]
    zero_metrics = exact_metrics(zero["matrix"])
    assert zero_metrics["accuracy"] == 1
    assert zero_metrics["kappa"] is None
    assert zero_metrics["consumers_accuracy"] == [1, None]
    assert zero_metrics["producers_accuracy"] == [1, None]
    assert zero_metrics["fscore_beta_2"] == [1, None]


def test_static_validation_controls_match_raw_pair_reference_and_reject_bad_schema():
    data = load_fixture()["matrix_reference"]
    order = data["order"]
    valid_rows = [row for row in expanded_matrix_rows(data)
                  if row.get("actual") is not None and row.get("predicted") is not None]
    in_order_rows = [row for row in valid_rows
                     if row["actual"] in order and row["predicted"] in order]
    complete, evaluated, expected_matrix = confusion_from_raw_rows(
        expanded_matrix_rows(data), order,
    )

    with OfflineGuard() as guard:
        ee = make_ee()
        collection = ee.FeatureCollection([
            ee.Feature(None, row) for row in in_order_rows
        ])
        matrix = collection.errorMatrix("actual", "predicted", order)
        output = compile_value(ee, matrix.array(), ([], {}))["value"]
        inferred_negative = ee.FeatureCollection([
            ee.Feature(None, {"actual": -1, "predicted": -1}),
        ]).errorMatrix("actual", "predicted")
        with pytest.raises(UnsupportedEEError, match="nonnegative when order is omitted"):
            compile_value(ee, inferred_negative.array(), ([], {}))
        missing_schema = ee.FeatureCollection([
            ee.Feature(None, {"actual": 1}),
        ]).errorMatrix("actual", "predicted", [0, 1])
        with pytest.raises(UnsupportedEEError, match="property is missing: predicted"):
            compile_value(ee, missing_schema.array(), ([], {}))
    assert guard.evidence()["attempt_count"] == 0
    assert (complete, evaluated, output) == (18, 17, expected_matrix)


@pytest.mark.parametrize("bad_row", [
    {"actual": None, "predicted": 0},
    {"actual": 0, "predicted": None},
    {"actual": 0.5, "predicted": 1},
    {"actual": 0, "predicted": True},
])
def test_static_validation_controls_reject_null_fractional_and_boolean_labels(bad_row):
    with OfflineGuard() as guard:
        ee = make_ee()
        expression = ee.FeatureCollection([ee.Feature(None, bad_row)]).errorMatrix(
            "actual", "predicted", [0, 1],
        ).array()
        with pytest.raises(UnsupportedEEError):
            compile_value(ee, expression, ([], {}))
    assert guard.evidence()["attempt_count"] == 0


def test_dynamic_rf_classification_rejects_missing_schema_null_and_output_collision():
    data = load_fixture()
    with OfflineGuard() as guard:
        ee = make_ee()
        training = ee.FeatureCollection([
            ee.Feature(None, row) for row in data["static_training_rows"]
        ])
        classifier = ee.Classifier.smileRandomForest(
            numberOfTrees=data["classifier_parameters"]["number_of_trees"],
            variablesPerSplit=data["classifier_parameters"]["variables_per_split"],
            minLeafPopulation=data["classifier_parameters"]["min_leaf_population"],
            bagFraction=data["classifier_parameters"]["bag_fraction"],
            maxNodes=data["classifier_parameters"]["max_nodes"],
            seed=data["classifier_parameters"]["seed"],
        ).train(
            features=training, classProperty=data["class_property"],
            inputProperties=data["input_properties"],
        )
        missing_input = ee.FeatureCollection([
            ee.Feature(None, {"nir": 3.5, "class_id": 0}),
        ]).classify(classifier, data["output_name"])
        with pytest.raises(UnsupportedEEError, match="missing classifier property: red"):
            compile_value(ee, missing_input, ([], {}))
        null_input = ee.FeatureCollection([
            ee.Feature(None, {"red": None, "nir": 3.5, "class_id": 0}),
        ]).classify(classifier, data["output_name"])
        with pytest.raises(UnsupportedEEError, match="classifier property is null: red"):
            compile_value(ee, null_input, ([], {}))
        collision = ee.FeatureCollection([
            ee.Feature(None, {"red": 1.5, "nir": 3.5, "class_id": 0,
                              data["output_name"]: 99}),
        ]).classify(classifier, data["output_name"])
        with pytest.raises(UnsupportedEEError, match="output property already exists"):
            compile_value(ee, collision, ([], {}))
    assert guard.evidence()["attempt_count"] == 0


def test_official_python_and_javascript_feature_workflows_compile_to_equivalent_graphs(
    javascript_workflows,
):
    with OfflineGuard() as guard:
        python_descriptors, javascript_descriptors = compile_cross_sdk_workflows(
            make_ee(), javascript_workflows,
        )
    assert guard.evidence()["attempt_count"] == 0

    # Compare graph/process structure exactly and parse the embedded canonical
    # JSON payloads; 9.0 and 9 are the same exact EE Number in these row values.
    assert semantic_wire(python_descriptors) == semantic_wire(javascript_descriptors)
    for mode in python_descriptors.values():
        for key, descriptor in mode.items():
            if key.endswith("_values"):
                for value in descriptor.values():
                    validate(value.get("process_graph", {}))
            else:
                validate(descriptor.get("process_graph", {}))
