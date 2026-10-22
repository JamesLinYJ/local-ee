"""Train a bounded nearest-class-mean classifier and validate held-out labels."""

SYNTHETIC_VERSION = "local-ee-synthetic-minimum-distance/v1"
INPUT_PROPERTIES = ["nir", "red"]
TRAINING_ROWS = [
    {"nir": 0, "red": 0, "landcover": 1},
    {"nir": 0, "red": 2, "landcover": 1},
    {"nir": 6, "red": 0, "landcover": 1},
    {"nir": 5, "red": 0, "landcover": 3},
    {"nir": 5, "red": 2, "landcover": 3},
    {"nir": 11, "red": 0, "landcover": 3},
]
VALIDATION_ROWS = [
    {"red": 0, "nir": 1, "landcover": 1},
    {"red": 1, "nir": 6, "landcover": 1},
    {"red": 2, "nir": 8, "landcover": 3},
    {"red": 1, "nir": 0, "landcover": 3},
    {"red": 0, "nir": 7, "landcover": 3},
]


def build_validation(ee, training, validation):
    model = ee.Classifier.minimumDistance(metric="euclidean", kNearest=1).train(
        features=training, classProperty="landcover", inputProperties=INPUT_PROPERTIES)
    predictions = validation.classify(model, "predicted")
    errors = predictions.errorMatrix("landcover", "predicted", [3, 1])
    resubstitution = model.confusionMatrix()
    return ee.Dictionary({
        "schema": model.schema(),
        "training_confusion": resubstitution.array(),
        "training_accuracy": resubstitution.accuracy(),
        "predictions": predictions.aggregate_array("predicted"),
        "validation_confusion": errors.array(),
        "validation_accuracy": errors.accuracy(),
        "validation_kappa": errors.kappa(),
    })


if __name__ == "__main__":
    import ee

    ee.Initialize()
    training = ee.FeatureCollection([ee.Feature(None, row) for row in TRAINING_ROWS])
    validation = ee.FeatureCollection([ee.Feature(None, row) for row in VALIDATION_ROWS])
    print("Synthetic sample:", SYNTHETIC_VERSION)
    print(build_validation(ee, training, validation).getInfo())
