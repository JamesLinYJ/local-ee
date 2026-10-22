"""Evaluate local prediction labels with an explicit, stable class order."""

SYNTHETIC_VERSION = "local-ee-synthetic-classification-validation/v1"
CLASS_ORDER = [30, 10, 20]
SAMPLE_ROWS = (
    [{"actual": 10, "predicted": 10}] * 5
    + [{"actual": 10, "predicted": 20}]
    + [{"actual": 20, "predicted": 10}] * 2
    + [{"actual": 20, "predicted": 20}] * 3
    + [{"actual": 20, "predicted": 30}]
    + [{"actual": 30, "predicted": 20}]
    + [{"actual": 30, "predicted": 30}] * 4
    + [{"predicted": 20}, {"actual": None, "predicted": 10},
       {"actual": 30, "predicted": None}, {"actual": 99, "predicted": 20}]
)


def build_validation(ee, predictions, order=CLASS_ORDER):
    complete = predictions.filter(ee.Filter.notNull(["actual", "predicted"]))
    matrix = complete.errorMatrix("actual", "predicted", order)
    return ee.Dictionary({
        "class_order": matrix.order(),
        "matrix": matrix.array(),
        "accuracy": matrix.accuracy(),
        "kappa": matrix.kappa(),
        "complete_rows": complete.size(),
        "evaluated_rows": matrix.array().reduce(ee.Reducer.sum(), [0, 1]).get([0, 0]),
    })


if __name__ == "__main__":
    import ee

    ee.Initialize()
    predictions = ee.FeatureCollection([ee.Feature(None, row) for row in SAMPLE_ROWS])
    print("Synthetic sample:", SYNTHETIC_VERSION)
    print(build_validation(ee, predictions).getInfo())
