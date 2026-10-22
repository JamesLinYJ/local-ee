"""Estimate two-band sample covariance from a bounded synthetic scene series."""

SYNTHETIC_VERSION = "local-ee-synthetic-covariance-descriptors/v1"
BANDS = ["red", "nir"]
FRAME_LABELS = ["d000", "d090", "d180", "d270"]
COVARIANCE_LABELS = [["red", "nir"], ["red", "nir"]]


def build_covariance(ee, collection):
    """Return sample covariance, scalar descriptors, and centering evidence."""
    ordered = ee.ImageCollection(collection).sort("system:time_start")
    frames = ordered.map(lambda image: ee.Image(image).select(BANDS).toFloat())
    packed = frames.toArrayPerBand(axis=0, dropMasked=False)
    shape = ee.Image(ee.Array([len(FRAME_LABELS), 1]))

    def column(name):
        return packed.select([name]).arrayReshape(
            lengths=shape, dimensions=2,
        ).toFloat()

    samples = column("red").arrayCat(column("nir"), axis=1).toFloat()
    count = len(FRAME_LABELS)
    centering = [[(1.0 if row == col else 0.0) - 1.0 / count
                  for col in range(count)] for row in range(count)]
    centered = ee.Image(ee.Array(centering)).toFloat().matrixMultiply(samples).toFloat()
    cross_product = centered.arrayTranspose().matrixMultiply(centered).toFloat()
    divisor = ee.Image(ee.Array([[1 / (count - 1)] * len(BANDS)] * len(BANDS))).toFloat()
    covariance = cross_product.multiply(divisor).toFloat()

    diagonal = covariance.matrixDiagonal()
    diagonal_matrix = diagonal.matrixToDiag()
    return {
        "source_ids": ordered.aggregate_array("system:index"),
        "centered": centered.arrayFlatten([FRAME_LABELS, BANDS]),
        "covariance": covariance.arrayFlatten(COVARIANCE_LABELS),
        "trace": covariance.matrixTrace().rename("trace"),
        "determinant": covariance.matrixDeterminant().rename("determinant"),
        "diagonal": diagonal.arrayFlatten([["red", "nir"], ["variance"]]),
        "diagonal_matrix": diagonal_matrix.arrayFlatten(COVARIANCE_LABELS),
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
        (root / "tests/fixtures/ee-covariance-descriptors-v1.json").read_text()
    )
    if fixture["schema"] != SYNTHETIC_VERSION:
        raise ValueError("Unexpected covariance synthetic fixture version")
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
                + fixture["frame_day"][frame] * 86_400_000,
        },
    } for frame in fixture["frame_order"]]
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    outputs = build_covariance(ee, ee.ImageCollection(fixture["collection_id"]))
    for name, value in outputs.items():
        compiled = compile_expression(
            ee.serializer.encode(value, for_cloud_api=False),
            catalog, {fixture["collection_id"]: items},
        )
        print(json.dumps({
            "fixture": SYNTHETIC_VERSION,
            "output": name,
            "kind": compiled["kind"],
            "bands": compiled.get("bands"),
            "source_item_ids": compiled.get("source_item_ids"),
            "graph_nodes": len(compiled.get("process_graph", {})),
        }))


if __name__ == "__main__":
    main()
