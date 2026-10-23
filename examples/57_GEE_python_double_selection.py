"""Double-precision keyed array selection on the local reshape-scene fixture."""

SYNTHETIC_VERSION = "local-ee-synthetic-double-selection/v1"
COLLECTION_ID = "sentinel-2-l2a"
PAYLOAD_BANDS = ["blue", "green", "red", "nir"]
KEY_BANDS = ["b5", "b4"]  # Reverse source order to make the first sample swap columns.
SCORE_BANDS = ["b4", "b5", "b6", "b7"]
MATRIX_LABELS = [["row0", "row1"], ["col0", "col1"]]
SYNTHETIC_BANDS = PAYLOAD_BANDS + SCORE_BANDS
SYNTHETIC_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [4, 0], [4, 1], [0, 1], [0, 0]]],
}
SYNTHETIC_PROJECTION = {
    "proj:code": "EPSG:32649",
    "proj:transform": [10, 0, 220000, 0, -10, 3420000],
}


def synthetic_catalog():
    """Return only local sample metadata; it declares no provider catalogue."""
    metadata = {
        "id": COLLECTION_ID,
        "cube:dimensions": {"bands": {"values": SYNTHETIC_BANDS}},
    }
    items = {COLLECTION_ID: [{
        "id": "reshape-scene",
        "bbox": [0, 0, 4, 1],
        "geometry": SYNTHETIC_GEOMETRY,
        "properties": {
            "system:index": "reshape-scene",
            "system:time_start": 1000,
            **SYNTHETIC_PROJECTION,
        },
    }]}
    return [metadata], items


def build_workflow(ee, image):
    """Return coupled sorts, first-maximum coordinates, and a trimmed mean."""
    source = ee.Image(image).set("workflow", SYNTHETIC_VERSION)
    matrix_shape = ee.Image.constant(ee.Array([2, 2]))
    key_shape = ee.Image.constant(ee.Array([1, 2]))

    payload_double = (
        source.select(PAYLOAD_BANDS).toArray()
        .arrayReshape(matrix_shape, 2).toDouble()
    )
    payload_float = (
        source.select(PAYLOAD_BANDS).toArray()
        .arrayReshape(matrix_shape, 2).toFloat()
    )
    keys_double = (
        source.select(KEY_BANDS).toArray()
        .arrayReshape(key_shape, 2).toDouble()
    )
    keys_after_float32 = keys_double.toFloat().toDouble()

    score_grid = (
        source.select(SCORE_BANDS).toArray()
        .arrayReshape(matrix_shape, 2).toDouble()
    )
    score_grid_after_float32 = score_grid.toFloat().toDouble()
    score_vector = source.select(SCORE_BANDS).toArray().toDouble()
    ordered_scores = score_vector.arraySort()
    middle_scores = ordered_scores.arraySlice(0, 1, 3)
    trimmed_middle_mean = (
        middle_scores.arrayReduce(ee.Reducer.mean(), [0])
        .arrayGet([0]).rename("trimmed_middle_score_mean")
    )

    return {
        "sorted_double_payload": payload_double.arraySort(keys_double).arrayFlatten(
            MATRIX_LABELS,
        ),
        "sorted_mixed_precision_payload": payload_float.arraySort(
            keys_double,
        ).arrayFlatten(MATRIX_LABELS),
        "sorted_payload_after_float32_keys": payload_double.arraySort(
            keys_after_float32,
        ).arrayFlatten(MATRIX_LABELS),
        "first_max_double_coordinates": score_grid.arrayArgmax().arrayFlatten(
            [["max_row", "max_column"]],
        ),
        "first_max_after_float32_coordinates": (
            score_grid_after_float32.arrayArgmax().arrayFlatten(
                [["max_row", "max_column"]],
            )
        ),
        "trimmed_middle_score_mean": trimmed_middle_mean,
    }


def main():
    import json
    from pathlib import Path
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    catalog, items = synthetic_catalog()
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    outputs = build_workflow(ee, ee.ImageCollection(COLLECTION_ID).first())
    for name, image in outputs.items():
        graph = compile_expression(
            ee.serializer.encode(image, for_cloud_api=False), catalog, items,
        )
        print(json.dumps({
            "fixture": SYNTHETIC_VERSION,
            "output": name,
            "bands": graph["bands"],
            "graph_nodes": len(graph["process_graph"]),
        }))


if __name__ == "__main__":
    main()
