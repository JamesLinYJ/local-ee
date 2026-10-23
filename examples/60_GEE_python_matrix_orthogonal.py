"""Compile compact per-pixel QR and SVD factors from a synthetic scene."""

SYNTHETIC_VERSION = "local-ee-synthetic-matrix-orthogonal/v1"
COLLECTION_ID = "sentinel-2-l2a"
TALL_BANDS = ["a00", "a01", "a10", "a11", "a20", "a21"]
WIDE_BANDS = ["a00", "a10", "a20", "a01", "a11", "a21"]
TRUNCATION_BANDS = ["a00", "a01", "b0", "a10", "a11", "b1", "a20", "a21", "b2"]
RHS_BANDS = ["b0", "b1", "b2"]
SOURCE_BANDS = sorted(set(TALL_BANDS + RHS_BANDS))
PROPERTIES = [
    "workflow", "system:index", "system:time_start", "proj:code", "proj:transform",
]


def _matrix(ee, image, bands, shape, precision="double"):
    values = image.select(bands)
    if precision == "double":
        values = values.toDouble()
    elif precision == "float32":
        values = values.toFloat()
    elif precision == "float32_then_double":
        values = values.toFloat().toDouble()
    else:
        raise ValueError(f"Unsupported matrix precision: {precision}")
    return values.toArray().arrayReshape(
        ee.Image.constant(ee.Array(shape)), 2,
    )


def _rhs(ee, image):
    return image.select(RHS_BANDS).toDouble().toArray().arrayReshape(
        ee.Image.constant(ee.Array([3, 1])), 2,
    )


def _flat(ee, source, array, rows, columns):
    return ee.Image(array.arrayFlatten([rows, columns]).copyProperties(source, PROPERTIES))


def build_workflow(ee, image):
    """Build QR/SVD factors and consume them through real array operations."""
    source = ee.Image(image).select(SOURCE_BANDS).set("workflow", SYNTHETIC_VERSION)
    tall = _matrix(ee, source, TALL_BANDS, [3, 2])
    wide = _matrix(ee, source, WIDE_BANDS, [2, 3])
    rhs = _rhs(ee, source)

    qr_tall = tall.matrixQRDecomposition()
    q_tall, r_tall = qr_tall.select("Q"), qr_tall.select("R")
    qtb = q_tall.matrixTranspose().matrixMultiply(rhs).toDouble()
    coefficients = r_tall.matrixSolve(qtb)
    fit = tall.matrixMultiply(coefficients)
    projection = q_tall.matrixMultiply(qtb)

    svd_tall = tall.matrixSingularValueDecomposition()
    u_tall, s_tall, v_tall = (
        svd_tall.select("U"), svd_tall.select("S"), svd_tall.select("V")
    )
    u_tall_1 = u_tall.arraySlice(1, 0, 1)
    s_tall_1 = s_tall.arraySlice(0, 0, 1).arraySlice(1, 0, 1)
    v_tall_1 = v_tall.arraySlice(1, 0, 1)
    u_tall_2 = u_tall.arraySlice(1, 0, 2)
    s_tall_2 = s_tall.arraySlice(0, 0, 2).arraySlice(1, 0, 2)
    v_tall_2 = v_tall.arraySlice(1, 0, 2)
    qr_wide = wide.matrixQRDecomposition()
    q_wide, r_wide = qr_wide.select("Q"), qr_wide.select("R")
    svd_wide = wide.matrixSingularValueDecomposition()
    u_wide, s_wide, v_wide = (
        svd_wide.select("U"), svd_wide.select("S"), svd_wide.select("V")
    )
    wide_rank1 = (
        u_wide.arraySlice(1, 0, 1)
        .matrixMultiply(s_wide.arraySlice(0, 0, 1).arraySlice(1, 0, 1))
        .matrixMultiply(v_wide.arraySlice(1, 0, 1).matrixTranspose())
    )
    wide_rank2 = (
        u_wide.arraySlice(1, 0, 2)
        .matrixMultiply(s_wide.arraySlice(0, 0, 2).arraySlice(1, 0, 2))
        .matrixMultiply(v_wide.arraySlice(1, 0, 2).matrixTranspose())
    )
    truncation_matrix = _matrix(ee, source, TRUNCATION_BANDS, [3, 3])
    svd_truncation = truncation_matrix.matrixSingularValueDecomposition()
    u_truncation, s_truncation, v_truncation = (
        svd_truncation.select("U"), svd_truncation.select("S"),
        svd_truncation.select("V"),
    )
    square = _matrix(ee, source, ["a00", "a01", "a10", "a11"], [2, 2])
    svd_square = square.matrixSingularValueDecomposition()
    u_square, s_square, v_square = (
        svd_square.select("U"), svd_square.select("S"), svd_square.select("V")
    )
    square_rank1 = (
        u_square.arraySlice(1, 0, 1)
        .matrixMultiply(s_square.arraySlice(0, 0, 1).arraySlice(1, 0, 1))
        .matrixMultiply(v_square.arraySlice(1, 0, 1).matrixTranspose())
    )
    square_rank2 = (
        u_square.arraySlice(1, 0, 2)
        .matrixMultiply(s_square.arraySlice(0, 0, 2).arraySlice(1, 0, 2))
        .matrixMultiply(v_square.arraySlice(1, 0, 2).matrixTranspose())
    )
    tall32 = _matrix(ee, source, TALL_BANDS, [3, 2], "float32_then_double")
    qr_tall32 = tall32.matrixQRDecomposition()
    svd_tall32 = tall32.matrixSingularValueDecomposition()

    return {
        "qr_tall_q": _flat(ee, source, q_tall, ["r0", "r1", "r2"], ["c0", "c1"]),
        "qr_tall_r": _flat(ee, source, r_tall, ["r0", "r1"], ["c0", "c1"]),
        "qr_tall_reconstruction": _flat(
            ee, source, q_tall.matrixMultiply(r_tall),
            ["r0", "r1", "r2"], ["c0", "c1"],
        ),
        "qr_tall_projection": _flat(
            ee, source, projection, ["r0", "r1", "r2"], ["value"],
        ),
        "qr_tall_least_squares": _flat(
            ee, source, coefficients, ["c0", "c1"], ["value"],
        ),
        "qr_tall_fit": _flat(ee, source, fit, ["r0", "r1", "r2"], ["value"]),
        "svd_tall_u": _flat(ee, source, u_tall, ["r0", "r1", "r2"], ["k0", "k1"]),
        "svd_tall_s": _flat(ee, source, s_tall, ["k0", "k1"], ["k0", "k1"]),
        "svd_tall_v": _flat(ee, source, v_tall, ["c0", "c1"], ["k0", "k1"]),
        "svd_tall_rank1": _flat(
            ee, source, u_tall_1.matrixMultiply(s_tall_1).matrixMultiply(
                v_tall_1.matrixTranspose()), ["r0", "r1", "r2"], ["c0", "c1"],
        ),
        "svd_tall_reconstruction": _flat(
            ee, source,
            u_tall.matrixMultiply(s_tall).matrixMultiply(v_tall.matrixTranspose()),
            ["r0", "r1", "r2"], ["c0", "c1"],
        ),
        "svd_tall_rank2": _flat(
            ee, source, u_tall_2.matrixMultiply(s_tall_2).matrixMultiply(
                v_tall_2.matrixTranspose()), ["r0", "r1", "r2"], ["c0", "c1"],
        ),
        "svd_square_u": _flat(ee, source, u_square, ["r0", "r1"], ["k0", "k1"]),
        "svd_square_s": _flat(ee, source, s_square, ["k0", "k1"], ["k0", "k1"]),
        "svd_square_v": _flat(ee, source, v_square, ["c0", "c1"], ["k0", "k1"]),
        "svd_square_reconstruction": _flat(
            ee, source, u_square.matrixMultiply(s_square).matrixMultiply(
                v_square.matrixTranspose()), ["r0", "r1"], ["c0", "c1"],
        ),
        "svd_square_rank1": _flat(
            ee, source, square_rank1, ["r0", "r1"], ["c0", "c1"],
        ),
        "svd_square_rank2": _flat(
            ee, source, square_rank2, ["r0", "r1"], ["c0", "c1"],
        ),
        "qr_wide_q": _flat(ee, source, q_wide, ["r0", "r1"], ["c0", "c1"]),
        "qr_wide_r": _flat(ee, source, r_wide, ["r0", "r1"], ["c0", "c1", "c2"]),
        "qr_wide_reconstruction": _flat(
            ee, source, q_wide.matrixMultiply(r_wide),
            ["r0", "r1"], ["c0", "c1", "c2"],
        ),
        "svd_wide_u": _flat(ee, source, u_wide, ["r0", "r1"], ["k0", "k1"]),
        "svd_wide_s": _flat(ee, source, s_wide, ["k0", "k1"], ["k0", "k1"]),
        "svd_wide_v": _flat(ee, source, v_wide, ["c0", "c1", "c2"], ["k0", "k1"]),
        "svd_wide_rank1": _flat(ee, source, wide_rank1, ["r0", "r1"], ["c0", "c1", "c2"]),
        "svd_wide_reconstruction": _flat(
            ee, source, u_wide.matrixMultiply(s_wide).matrixMultiply(
                v_wide.matrixTranspose()), ["r0", "r1"], ["c0", "c1", "c2"],
        ),
        "svd_wide_rank2": _flat(
            ee, source, wide_rank2, ["r0", "r1"], ["c0", "c1", "c2"],
        ),
        "svd_truncation_u": _flat(
            ee, source, u_truncation, ["r0", "r1", "r2"], ["k0", "k1", "k2"],
        ),
        "svd_truncation_s": _flat(
            ee, source, s_truncation, ["k0", "k1", "k2"], ["k0", "k1", "k2"],
        ),
        "svd_truncation_v": _flat(
            ee, source, v_truncation, ["c0", "c1", "c2"], ["k0", "k1", "k2"],
        ),
        "qr_float32_then_double_reconstruction": _flat(
            ee, source, qr_tall32.select("Q").matrixMultiply(qr_tall32.select("R")),
            ["r0", "r1", "r2"], ["c0", "c1"],
        ),
        "svd_float32_then_double_reconstruction": _flat(
            ee, source, svd_tall32.select("U").matrixMultiply(
                svd_tall32.select("S").matrixMultiply(
                    svd_tall32.select("V").matrixTranspose()
                )
            ), ["r0", "r1", "r2"], ["c0", "c1"],
        ),
    }


def build_budget_limited_compositions(ee, image):
    """Return real factor compositions currently covered by explicit budget tests."""
    source = ee.Image(image).select(SOURCE_BANDS)
    tall = _matrix(ee, source, TALL_BANDS, [3, 2])
    rhs = _rhs(ee, source)
    qr_tall = tall.matrixQRDecomposition()
    q_tall, r_tall = qr_tall.select("Q"), qr_tall.select("R")
    qtb = q_tall.matrixTranspose().matrixMultiply(rhs).toDouble()
    coefficients = r_tall.matrixSolve(qtb)
    fit = tall.matrixMultiply(coefficients)
    truncation_matrix = _matrix(ee, source, TRUNCATION_BANDS, [3, 3])
    svd_truncation = truncation_matrix.matrixSingularValueDecomposition()
    u_truncation, s_truncation, v_truncation = (
        svd_truncation.select("U"), svd_truncation.select("S"),
        svd_truncation.select("V"),
    )

    return {
        "qr_tall_normal_residual": _flat(
            ee, source, q_tall.matrixTranspose().matrixMultiply(rhs.subtract(fit)),
            ["c0", "c1"], ["value"],
        ),
        "svd_truncation_reconstruction": _flat(
            ee, source, u_truncation.matrixMultiply(s_truncation).matrixMultiply(
                v_truncation.matrixTranspose()),
            ["r0", "r1", "r2"], ["c0", "c1", "c2"],
        ),
        "svd_truncation_rank2": _flat(
            ee, source,
            u_truncation.arraySlice(1, 0, 2)
            .matrixMultiply(s_truncation.arraySlice(0, 0, 2).arraySlice(1, 0, 2))
            .matrixMultiply(v_truncation.arraySlice(1, 0, 2).matrixTranspose()),
            ["r0", "r1", "r2"], ["c0", "c1", "c2"],
        ),
    }


def declared_catalog():
    """Return synthetic metadata only; no remote catalog or source data."""
    geometry = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [12, 0], [12, 1], [0, 1], [0, 0]]],
    }
    catalog = [{
        "id": COLLECTION_ID,
        "cube:dimensions": {"bands": {"values": SOURCE_BANDS}},
    }]
    items = {COLLECTION_ID: [{
        "id": "matrix-orthogonal-scene-v1",
        "bbox": [0, 0, 12, 1],
        "geometry": geometry,
        "properties": {
            "system:index": "matrix-orthogonal-scene-v1",
            "system:time_start": 1_798_588_800_000,
            "proj:code": "EPSG:32649",
            "proj:transform": [1, 0, 0, 0, -1, 1],
        },
    }]}
    return catalog, items


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
        expression = ee.serializer.encode(image, for_cloud_api=False)
        graph = compile_expression(expression, catalog, items)
        print(json.dumps({
            "fixture": SYNTHETIC_VERSION,
            "output": name,
            "bands": graph["bands"],
            "graph_nodes": len(graph["process_graph"]),
        }))


if __name__ == "__main__":
    main()
