"""Solve a fixed spectral mixture per pixel with bounded Image.matrixSolve."""

SYNTHETIC_VERSION = "local-ee-synthetic-raster-least-squares/v1"
BANDS = ["green", "red", "nir"]
DESIGN_MATRIX = [[2, 1], [1, 2], [1, 1]]
ENDMEMBER_BANDS = ["endmember_1", "endmember_2"]


def build_least_squares(ee, image):
    """Return unmixing, forward reconstruction and per-band residual images."""
    design = ee.Image(ee.Array(DESIGN_MATRIX)).toFloat()
    observations = (
        ee.Image(image).select(BANDS).toArray().toArray(1).toFloat()
    )
    abundance_array = design.matrixSolve(observations)
    reconstruction_array = design.matrixMultiply(abundance_array).toFloat()
    residual_array = observations.subtract(reconstruction_array).toFloat()

    abundances = abundance_array.arrayProject([0]).arrayFlatten([ENDMEMBER_BANDS])
    reconstruction = reconstruction_array.arrayProject([0]).arrayFlatten([BANDS])
    residuals = residual_array.arrayProject([0]).arrayFlatten([BANDS])
    return {
        "abundances": abundances,
        "reconstruction": reconstruction,
        "residuals": residuals,
    }


def main():
    import json
    from pathlib import Path
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from gee.ee_python_client import configure_local_ee
    from gee.ee_translate import compile_expression

    data = json.loads((root / "tests/fixtures/ee-raster-least-squares-v1.json").read_text())
    if data["schema"] != SYNTHETIC_VERSION:
        raise ValueError("Unexpected synthetic raster fixture version")
    catalog = [{"id": data["collection_id"],
        "cube:dimensions": {"bands": {"values": data["bands"]}}}]
    item = {"id": data["item_id"], "bbox": data["bbox"],
        "geometry": data["scene_geometry"], "properties": {"system:index": data["item_id"]}}
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    outputs = build_least_squares(
        ee, ee.ImageCollection(data["collection_id"]).first()
    )
    for name, image in outputs.items():
        encoded = ee.serializer.encode(image, for_cloud_api=False)
        result = compile_expression(encoded, catalog, {data["collection_id"]: [item]})
        print(json.dumps({"fixture": SYNTHETIC_VERSION, "output": name,
            "bands": result["bands"], "graph_nodes": len(result["process_graph"])}))


if __name__ == "__main__":
    main()
