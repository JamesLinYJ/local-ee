"""Fit two raster response columns through the bounded array-image API."""

from __future__ import annotations

SYNTHETIC_VERSION = "local-ee-synthetic-multi-response-arrays/v1"
INPUT_BANDS = ["signal", "temperature"]
FRAME_LABELS = ["x0", "x1", "x2", "x3"]
X_VALUES = [0, 1, 2, 3]
COEFFICIENT_ROWS = ["intercept", "slope"]


def build_multi_response_fit(ee, collection):
    """Return coefficients, fitted samples and residuals for two responses."""
    ordered = ee.ImageCollection(collection).sort("system:time_start")
    frames = ordered.map(
        lambda image: ee.Image(image).select(INPUT_BANDS).toFloat()
    )

    # Repeat a one-cell array along its first existing axis to create a 4x1
    # intercept column. Both design columns are explicitly narrowed to Float32.
    intercept_seed = ee.Image(ee.Array([[1]])).toFloat()
    intercept = intercept_seed.arrayRepeat(
        axis=0, copies=ee.Image.constant(len(X_VALUES))
    ).toFloat()
    predictor = ee.Image(ee.Array([[value] for value in X_VALUES])).toFloat()
    design = intercept.arrayCat(predictor, axis=1).toFloat()

    packed = frames.toArrayPerBand(axis=0, dropMasked=False)
    lengths = ee.Image(ee.Array([len(FRAME_LABELS), 1]))

    def response_column(name):
        return packed.select([name]).arrayReshape(
            lengths=lengths, dimensions=2
        ).toFloat()

    signal = response_column("signal")
    temperature = response_column("temperature")
    responses = signal.arrayCat(temperature, axis=1).toFloat()

    coefficients = design.matrixSolve(responses)
    fitted = design.matrixMultiply(coefficients).toFloat()
    residuals = responses.subtract(fitted).toFloat()
    labels = [COEFFICIENT_ROWS, INPUT_BANDS]
    sample_labels = [FRAME_LABELS, INPUT_BANDS]
    return {
        "source_ids": ordered.aggregate_array("system:index"),
        "design_matrix": ee.Array([[1, value] for value in X_VALUES]),
        "coefficients": coefficients.arrayFlatten(labels),
        "fitted": fitted.arrayFlatten(sample_labels),
        "residuals": residuals.arrayFlatten(sample_labels),
    }


def main():
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    fixture = json.loads(
        (root / "tests/fixtures/ee-multi-response-arrays-v1.json").read_text()
    )
    if fixture["schema"] != SYNTHETIC_VERSION:
        raise ValueError("Unexpected multi-response synthetic fixture version")
    catalog = [{
        "id": fixture["collection_id"],
        "cube:dimensions": {"bands": {"values": fixture["bands"]}},
    }]
    items = [{
        "id": frame,
        "bbox": fixture["bbox"],
        "geometry": fixture["scene_geometry"],
        "properties": {
            "system:index": frame,
            "system:time_start": 1_680_000_000_000
                + fixture["frame_x"][frame] * 86_400_000,
        },
    } for frame in fixture["frame_order"]]
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    outputs = build_multi_response_fit(ee, ee.ImageCollection(fixture["collection_id"]))
    for name, value in outputs.items():
        result = compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), catalog,
            {fixture["collection_id"]: items},
        )
        print(json.dumps({
            "fixture": SYNTHETIC_VERSION,
            "output": name,
            "kind": result["kind"],
            "bands": result.get("bands"),
            "source_item_ids": result.get("source_item_ids"),
            "graph_nodes": len(result.get("process_graph", {})),
        }))


if __name__ == "__main__":
    main()
