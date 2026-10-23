"""Solve and inspect dynamic per-pixel matrices from a declared local scene."""

SYNTHETIC_VERSION = "local-ee-synthetic-pixel-matrices/v1"
# The local compiler only opens collections that already have an accepted
# source-resolver ID. This versioned catalog is entirely synthetic and uses
# that existing local alias; it does not grant acceptance to a new dataset.
COLLECTION_ID = "sentinel-2-l2a"
MATRIX_BANDS = ["m00", "m01", "m10", "m11"]
RIGHT_HAND_SIDE_BANDS = ["b0", "b1"]
SOURCE_BANDS = MATRIX_BANDS + RIGHT_HAND_SIDE_BANDS
MATRIX_SHAPE = [2, 2]
RIGHT_HAND_SIDE_SHAPE = [2, 1]
MATRIX_ROWS = ["row0", "row1"]
MATRIX_COLUMNS = ["col0", "col1"]
SOLUTION_COLUMNS = ["x0", "x1"]
COPIED_PROPERTIES = [
    "workflow", "system:index", "system:time_start", "proj:code", "proj:transform",
]


def declared_catalog():
    """Return the versioned metadata used by this example's compile-only CLI."""
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [5, 0], [5, 1], [0, 1], [0, 0]]],
    }
    catalog = [{
        "id": COLLECTION_ID,
        "cube:dimensions": {"bands": {"values": SOURCE_BANDS}},
    }]
    items = {COLLECTION_ID: [{
        "id": "matrix-scene-v1",
        "bbox": [0, 0, 5, 1],
        "geometry": geometry,
        "properties": {
            "system:index": "matrix-scene-v1",
            "system:time_start": 1_798_588_800_000,
            "proj:code": "EPSG:32649",
            "proj:transform": [1, 0, 0, 0, -1, 1],
        },
    }]}
    return catalog, items


def _matrix_from_bands(ee, image, bands, shape, *, precision="double"):
    values = image.select(bands)
    if precision == "double":
        values = values.toDouble()
    elif precision == "float32":
        values = values.toFloat()
    elif precision == "float32_then_double":
        # Preserve the nested Float32 rounding, then carry the rounded values
        # through the matrix operation as Float64.
        values = values.toFloat().toDouble()
    else:
        raise ValueError(f"Unsupported example precision: {precision}")
    return values.toArray().arrayReshape(
        ee.Image.constant(ee.Array(shape)), 2,
    )


def _flatten(matrix, source, row_names, column_names):
    return matrix.arrayFlatten([row_names, column_names]).copyProperties(
        source, COPIED_PROPERTIES,
    )


def build_workflow(ee, image):
    """Build matrix operations from real source bands, never literal matrices."""
    source = ee.Image(image).select(SOURCE_BANDS).set("workflow", SYNTHETIC_VERSION)
    matrix = _matrix_from_bands(ee, source, MATRIX_BANDS, MATRIX_SHAPE)
    right_hand_side = _matrix_from_bands(
        ee, source, RIGHT_HAND_SIDE_BANDS, RIGHT_HAND_SIDE_SHAPE,
    )

    inverse = matrix.matrixInverse()
    pseudo_inverse = matrix.matrixPseudoInverse()
    solution = matrix.matrixSolve(right_hand_side)

    rounded_matrix = _matrix_from_bands(
        ee, source, MATRIX_BANDS, MATRIX_SHAPE,
        precision="float32_then_double",
    )
    rounded_inverse = rounded_matrix.matrixInverse()
    float32_matrix = _matrix_from_bands(
        ee, source, MATRIX_BANDS, MATRIX_SHAPE, precision="float32",
    )

    return {
        "matrix_inverse": _flatten(
            inverse, source, MATRIX_ROWS, MATRIX_COLUMNS,
        ),
        "matrix_pseudoinverse": _flatten(
            pseudo_inverse, source, MATRIX_ROWS, MATRIX_COLUMNS,
        ),
        "matrix_solve": _flatten(
            solution, source, SOLUTION_COLUMNS, ["rhs"],
        ),
        "inverse_reconstruction": _flatten(
            inverse.matrixMultiply(matrix), source, MATRIX_ROWS, MATRIX_COLUMNS,
        ),
        "pseudoinverse_projection": _flatten(
            pseudo_inverse.matrixMultiply(matrix), source,
            MATRIX_ROWS, MATRIX_COLUMNS,
        ),
        "pseudoinverse_prediction": _flatten(
            pseudo_inverse.matrixMultiply(right_hand_side), source,
            SOLUTION_COLUMNS, ["rhs"],
        ),
        "float64_matrix": _flatten(
            matrix, source, MATRIX_ROWS, MATRIX_COLUMNS,
        ),
        "float32_then_float64_matrix": _flatten(
            rounded_matrix, source, MATRIX_ROWS, MATRIX_COLUMNS,
        ),
        "float32_then_float64_inverse": _flatten(
            rounded_inverse, source, MATRIX_ROWS, MATRIX_COLUMNS,
        ),
        "float32_matrix": _flatten(
            float32_matrix, source, MATRIX_ROWS, MATRIX_COLUMNS,
        ),
        "float32_inverse": _flatten(
            float32_matrix.matrixInverse(), source, MATRIX_ROWS, MATRIX_COLUMNS,
        ),
    }


def main():
    import json
    from pathlib import Path
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    catalog, items = declared_catalog()
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    outputs = build_workflow(
        ee, ee.ImageCollection(COLLECTION_ID).first(),
    )
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
