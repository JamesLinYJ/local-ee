"""Workflow-graph contracts and independent row-result comparisons."""
import json

from ee_image_sample_workflow_helpers import (
    ACCESSORS, CONFUSION_VALUE, ERROR_MATRIX, RF_CLASSIFY_IMAGE,
    RF_CLASSIFY_ROWS, RF_CONFUSION, RF_SAMPLES, SAMPLE, SAMPLE_OP,
    grid_centers, nodes, reference_sample_rows, reference_training_rows,
)


def assert_sample_workflow_graph(data, mode, descriptors):
    from gee.graph import validate

    for key in ("candidates", "training", "validation_predictions", "classified"):
        validate(descriptors[key]["process_graph"])
    for descriptor in descriptors["validation_values"].values():
        validate(descriptor["process_graph"])

    sample_nodes = nodes(descriptors["training"]["process_graph"], SAMPLE)
    operation_nodes = nodes(descriptors["training"]["process_graph"], SAMPLE_OP)
    assert len(sample_nodes) == 1
    assert [json.loads(node["arguments"]["spec"])["operation"]
            for _, node in operation_nodes] == ["filter", "filter", "limit"]
    spec = json.loads(sample_nodes[0][1]["arguments"]["spec"])
    assert spec["version"] == 2
    assert spec["bands"] == data["sample_bands"]
    assert spec["properties"] == []
    assert spec["image_sample"]["seed"] == data["sample_seed"]
    assert spec["image_sample"]["algorithm"] == "splitmix64-grid-v1"
    assert spec["geometries"] is True
    if mode in {"all", "nullable"}:
        assert spec["image_sample"]["factor"] is None
        assert spec["image_sample"]["num_pixels"] is None
        assert len(spec["regions"]["features"]) == 1
        assert spec["regions"]["features"][0]["geometry"] == data["items"][0]["geometry"]
    else:
        assert spec["regions"]["features"][0]["geometry"] == data["explicit_region"]
    assert spec["image_sample"]["drop_nulls"] is (mode == "all")
    if mode == "factor":
        assert spec["image_sample"]["factor"] == 0.5
        assert spec["image_sample"]["num_pixels"] is None
    elif mode == "num_pixels":
        assert spec["image_sample"]["factor"] is None
        assert spec["image_sample"]["num_pixels"] == 8
    else:
        assert spec["image_sample"]["factor"] is None
        assert spec["image_sample"]["num_pixels"] is None
    if mode == "all":
        assert spec["grid"] == {"scale": None, "crs": None}
    assert operation_nodes[0][1]["arguments"]["data"] == {
        "from_node": sample_nodes[0][0],
    }

    prediction_graph = descriptors["validation_predictions"]["process_graph"]
    trainer_nodes = nodes(prediction_graph, RF_SAMPLES)
    assert len(trainer_nodes) == 1
    trainer_id, trainer = trainer_nodes[0]
    trainer_spec = json.loads(trainer["arguments"]["spec"])
    assert trainer_spec["schema"] == data["input_properties"]
    assert trainer_spec["class_property"] == data["class_property"]
    assert trainer["arguments"]["data"]["from_node"]
    validation_predictors = nodes(prediction_graph, RF_CLASSIFY_ROWS)
    assert len(validation_predictors) == 1

    image_classifiers = nodes(descriptors["classified"]["process_graph"], RF_CLASSIFY_IMAGE)
    assert len(image_classifiers) == 1
    assert image_classifiers[0][1]["arguments"]["model"] == {"from_node": trainer_id}
    assert descriptors["validation_predictions"]["kind"] == "runtime_table"
    for name, descriptor in descriptors["validation_values"].items():
        matrix_nodes = nodes(descriptor["process_graph"], ERROR_MATRIX)
        accessor_nodes = nodes(descriptor["process_graph"], CONFUSION_VALUE)
        assert len(matrix_nodes) == len(accessor_nodes) == 1
        assert matrix_nodes[0][1]["arguments"]["data"] == {
            "from_node": validation_predictors[0][0],
        }
        accessor_spec = json.loads(accessor_nodes[0][1]["arguments"]["spec"])
        assert accessor_spec["operation"] == ACCESSORS[name]
    assert nodes(descriptors["training_array"]["process_graph"], RF_CONFUSION)
    return sample_nodes[0][1]["arguments"]["spec"]


def assert_sample_rows_match_reference(
    data, mode, descriptors, arrays, geometries, handlers,
):
    from test_ee_translate import evaluate_graph

    candidates = evaluate_graph(
        descriptors["candidates"], arrays, grid=grid_centers(data),
        source_geometries=geometries, process_handlers=handlers,
    )
    expected_candidates = {"type": "FeatureCollection", "features": reference_sample_rows(data, mode)}
    assert candidates == expected_candidates
    training = evaluate_graph(
        descriptors["training"], arrays, grid=grid_centers(data),
        source_geometries=geometries, process_handlers=handlers,
    )
    expected_training = {"type": "FeatureCollection", "features": reference_training_rows(data, mode)}
    assert training == expected_training
