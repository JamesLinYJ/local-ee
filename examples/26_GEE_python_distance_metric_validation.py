"""Compare bounded minimum-distance metrics on held-out synthetic features."""

from pathlib import Path

SYNTHETIC_VERSION = "local-ee-distance-metric-validation/v1"
INPUT_PROPERTIES = ["nir", "red"]
CLASS_PROPERTY = "landcover"
CLASS_ORDER = [0, 1]
PREDICTION_PROPERTY = "predicted"
DISTANCE_METRICS = ("euclidean", "manhattan", "cosine")

TRAINING_ROWS = [
    {"nir": 2, "red": 0, "landcover": 0, "system:index": "train-0a"},
    {"nir": 4, "red": 0, "landcover": 0, "system:index": "train-0b"},
    {"nir": 1, "red": 1, "landcover": 1, "system:index": "train-1a"},
    {"nir": 3, "red": 3, "landcover": 1, "system:index": "train-1b"},
]

VALIDATION_ROWS = [
    {"nir": 0.25, "red": 0.25, "landcover": 0, "sample_id": "diag-small",
     "system:index": "held-01", "note": "positive diagonal, small magnitude"},
    {"red": 2, "nir": 2, "landcover": 1, "sample_id": "diag-unit",
     "system:index": "held-02", "note": "same direction at larger magnitude"},
    {"nir": 8, "red": 3.6, "landcover": 1, "sample_id": "shallow-large",
     "system:index": "held-03", "note": "positive direction near the Euclidean boundary"},
    {"nir": 6, "red": 0, "landcover": 1, "sample_id": "positive-axis",
     "system:index": "held-04", "note": "positive nir axis"},
    {"nir": -2, "red": -2, "landcover": 0, "sample_id": "negative-diagonal",
     "system:index": "held-05", "note": "negative direction"},
    {"nir": 0, "red": 4, "landcover": 1, "sample_id": "positive-red-axis",
     "system:index": "held-06", "note": "positive red axis"},
]


def build_metric_validation(ee, training, validation, metric):
    """Train one metric, predict held-out rows, and return local-policy scores."""
    model = ee.Classifier.minimumDistance(metric=metric, kNearest=1).train(
        features=training,
        classProperty=CLASS_PROPERTY,
        inputProperties=INPUT_PROPERTIES,
    )
    classified = validation.classify(model, PREDICTION_PROPERTY)
    validation_matrix = classified.errorMatrix(
        CLASS_PROPERTY, PREDICTION_PROPERTY, CLASS_ORDER,
    )
    training_matrix = model.confusionMatrix()
    return ee.Dictionary({
        "schema": model.schema(),
        "training_confusion": training_matrix.array(),
        "validation_sample_ids": classified.aggregate_array("sample_id"),
        "predictions": classified.aggregate_array(PREDICTION_PROPERTY),
        "classified_features": classified,
        "validation_confusion": validation_matrix.array(),
        "accuracy": validation_matrix.accuracy(),
        "consumers_accuracy": validation_matrix.consumersAccuracy(),
        "producers_accuracy": validation_matrix.producersAccuracy(),
        "fscore": validation_matrix.fscore(),
        "fscore_beta2": validation_matrix.fscore(beta=2),
    })


def build_all_validations(ee, training, validation):
    """Retrain on one unchanged table for each supported metric."""
    by_metric = {
        metric: build_metric_validation(ee, training, validation, metric)
        for metric in DISTANCE_METRICS
    }
    return ee.Dictionary({
        "training_before": training,
        "training_after": training,
        "validation_before": validation,
        "validation_after": validation,
        "by_metric": ee.Dictionary(by_metric),
    })


if __name__ == "__main__":
    import json

    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    root = Path(__file__).resolve().parents[1]
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    training = ee.FeatureCollection([ee.Feature(None, row) for row in TRAINING_ROWS])
    validation = ee.FeatureCollection([ee.Feature(None, row) for row in VALIDATION_ROWS])
    expression = ee.serializer.encode(
        build_all_validations(ee, training, validation), for_cloud_api=False,
    )
    print(json.dumps(compile_expression(expression, [], {})["value"], indent=2))
