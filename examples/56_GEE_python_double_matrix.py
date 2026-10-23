"""Fit a fixed per-pixel linear model from three synthetic scalar bands."""

SYNTHETIC_VERSION = "local-ee-synthetic-double-matrix-workflow/v1"
BANDS = ["red", "nir", "blue"]
DESIGN_MATRIX = [[1, 0], [1, 1], [1, 2]]
COEFFICIENT_BANDS = ["intercept", "slope"]
PREDICTION_BANDS = ["x0", "x1", "x2"]


def build_workflow(ee, image):
    """Return least-squares coefficients, predictions and precision controls."""
    source = ee.Image(image).select(BANDS).set("workflow", SYNTHETIC_VERSION)
    observations = source.toDouble().toArray().arrayReshape(
        ee.Image.constant(ee.Array([3, 1])), 2,
    )
    design = ee.Image(ee.Array(DESIGN_MATRIX)).toDouble()

    copied = [
        "workflow", "system:index", "system:time_start",
        "proj:code", "proj:transform",
    ]
    coefficients = ee.Image(
        design.matrixSolve(observations).copyProperties(source, copied)
    )
    predictions = ee.Image(
        design.matrixMultiply(coefficients).copyProperties(source, copied)
    ).toDouble()

    # The middle observation is one scalar selected from a 3-by-1 array image.
    selected_prediction = predictions.arrayGet(
        ee.Image.constant([1, 0]),
    ).rename("prediction_at_x1")

    blue = source.select(["blue"])
    precision_controls = (
        blue.toDouble().rename("blue_float64")
        .addBands(blue.toFloat().rename("blue_float32"))
        .addBands(blue.toFloat().toDouble().rename("blue_float32_then_float64"))
    )

    return {
        "coefficients": coefficients.arrayProject([0]).arrayFlatten(
            [COEFFICIENT_BANDS],
        ),
        "predictions": predictions.arrayProject([0]).arrayFlatten(
            [PREDICTION_BANDS],
        ),
        "prediction_frobenius_norm": predictions.matrixFnorm().rename(
            "prediction_frobenius_norm",
        ),
        "selected_prediction": selected_prediction,
        "observation_trace": observations.matrixToDiag().matrixTrace().rename(
            "observation_trace",
        ),
        "precision_controls": precision_controls,
    }


def main():
    import json
    from pathlib import Path
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression
    from scripts.ee_python_api.probe_cases import COLLECTION_ID, synthetic_inputs

    metadata, items, _ = synthetic_inputs()
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    outputs = build_workflow(ee, ee.ImageCollection(COLLECTION_ID).first())
    for name, image in outputs.items():
        graph = compile_expression(
            ee.serializer.encode(image, for_cloud_api=False), [metadata], items,
        )
        print(json.dumps({
            "fixture": SYNTHETIC_VERSION,
            "output": name,
            "bands": graph["bands"],
            "graph_nodes": len(graph["process_graph"]),
        }))


if __name__ == "__main__":
    main()
