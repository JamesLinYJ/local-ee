"""Compile bounded Cholesky and LU factors from a declared synthetic scene."""

SYNTHETIC_VERSION = "local-ee-synthetic-matrix-factors/v1"
COLLECTION_ID = "sentinel-2-l2a"
MATRIX_BANDS = ["m00", "m01", "m10", "m11"]
RHS_BANDS = ["b0", "b1"]
SOURCE_BANDS = MATRIX_BANDS + RHS_BANDS
MATRIX_SHAPE = [2, 2]
RHS_SHAPE = [2, 1]
PROPERTIES = [
    "workflow", "system:index", "system:time_start", "proj:code", "proj:transform",
]


def declared_catalog():
    """Return synthetic catalog metadata for compile-only local evaluation."""
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [8, 0], [8, 1], [0, 1], [0, 0]]],
    }
    catalog = [{
        "id": COLLECTION_ID,
        "cube:dimensions": {"bands": {"values": SOURCE_BANDS}},
    }]
    items = {COLLECTION_ID: [{
        "id": "matrix-factor-scene-v1",
        "bbox": [0, 0, 8, 1],
        "geometry": geometry,
        "properties": {
            "system:index": "matrix-factor-scene-v1",
            "system:time_start": 1_798_588_800_000,
            "proj:code": "EPSG:32649",
            "proj:transform": [1, 0, 0, 0, -1, 1],
        },
    }]}
    return catalog, items


def _matrix(ee, image, *, precision="double"):
    values = image.select(MATRIX_BANDS)
    if precision == "double":
        values = values.toDouble()
    elif precision == "float32":
        values = values.toFloat()
    elif precision == "float32_then_double":
        values = values.toFloat().toDouble()
    else:
        raise ValueError(f"Unsupported matrix precision: {precision}")
    return values.toArray().arrayReshape(
        ee.Image.constant(ee.Array(MATRIX_SHAPE)), 2,
    )


def _rhs(ee, image):
    return image.select(RHS_BANDS).toDouble().toArray().arrayReshape(
        ee.Image.constant(ee.Array(RHS_SHAPE)), 2,
    )


def _flatten(ee, array, source, row_labels, column_labels):
    return ee.Image(
        array.arrayFlatten([row_labels, column_labels]).copyProperties(
            source, PROPERTIES,
        )
    )


def build_workflow(ee, image):
    """Build and consume factors from actual named source bands."""
    source = ee.Image(image).select(SOURCE_BANDS).set("workflow", SYNTHETIC_VERSION)
    matrix = _matrix(ee, source)
    rhs = _rhs(ee, source)

    cholesky = matrix.matrixCholeskyDecomposition()
    lower = cholesky.select("L")
    lower_t = lower.matrixTranspose()
    lu = matrix.matrixLUDecomposition()
    lu_lower = lu.select("L")
    upper = lu.select("U")
    permutation = lu.select("P")
    float32_upper = (
        _matrix(ee, source, precision="float32")
        .matrixLUDecomposition().select("U")
    )

    lu_factors = (
        _flatten(ee, lu_lower, source, ["L0", "L1"], ["C0", "C1"])
        .addBands(_flatten(ee, upper, source, ["U0", "U1"], ["C0", "C1"]))
        .addBands(_flatten(ee, permutation, source, ["P0", "P1"], ["C0", "C1"]))
    )
    return {
        "cholesky_L": _flatten(ee, lower, source, ["L0", "L1"], ["C0", "C1"]),
        "cholesky_reconstruction": _flatten(ee,
            lower.matrixMultiply(lower_t), source, ["R0", "R1"], ["C0", "C1"],
        ),
        "cholesky_float32_L": _flatten(ee,
            _matrix(ee, source, precision="float32").matrixCholeskyDecomposition()
            .select("L"), source, ["L0", "L1"], ["C0", "C1"],
        ),
        "cholesky_float32_then_double_L": _flatten(ee,
            _matrix(ee, source, precision="float32_then_double")
            .matrixCholeskyDecomposition().select("L"),
            source, ["L0", "L1"], ["C0", "C1"],
        ),
        "lu_float32_U": _flatten(ee, float32_upper, source,
            ["U0", "U1"], ["C0", "C1"],
        ).toFloat(),
        "lu_factors": lu_factors,
        "lu_left_product": _flatten(ee,
            permutation.matrixMultiply(matrix), source,
            ["R0", "R1"], ["C0", "C1"],
        ),
        "lu_right_product": _flatten(ee,
            lu_lower.matrixMultiply(upper), source,
            ["R0", "R1"], ["C0", "C1"],
        ),
        "lu_upper_inverse": _flatten(ee,
            upper.matrixInverse(), source, ["R0", "R1"], ["C0", "C1"],
        ),
        "cholesky_solve_from_factors": _flatten(ee,
            lower_t.matrixSolve(lower.matrixSolve(rhs)),
            source, ["X0", "X1"], ["rhs"],
        ),
    }


def full_lu_inverse_expression(ee, image):
    """Return the conventional U^-1 L^-1 P composition for budget testing."""
    source = ee.Image(image).select(SOURCE_BANDS)
    matrix = _matrix(ee, source)
    factors = matrix.matrixLUDecomposition()
    return (
        factors.select("U").matrixInverse()
        .matrixMultiply(factors.select("L").matrixInverse())
        .matrixMultiply(factors.select("P"))
    )


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
