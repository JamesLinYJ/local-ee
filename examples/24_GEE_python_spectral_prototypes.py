"""Select fixed synthetic spectral prototypes by per-pixel squared distance."""

import math

SYNTHETIC_VERSION = "local-ee-synthetic-spectral-prototypes/v1"
BANDS = ["red", "nir"]


def _valid_reflectance(value):
    if type(value) not in (int, float):
        return False
    if type(value) is int and abs(value) > 2**53:
        return False
    return math.isfinite(value)


def build_prototype_selection(ee, collection, prototype_ids, prototype_vectors):
    """Return prototype distances, negative scores and the first maximum index."""
    if (not isinstance(prototype_ids, (list, tuple)) or len(prototype_ids) != 3
            or any(not isinstance(name, str) or not name for name in prototype_ids)
            or len(set(prototype_ids)) != 3):
        raise ValueError("Provide exactly three unique, nonempty prototype IDs")
    if (not isinstance(prototype_vectors, (list, tuple)) or len(prototype_vectors) != 3
            or any(not isinstance(vector, (list, tuple)) or len(vector) != len(BANDS)
                   or any(not _valid_reflectance(value) for value in vector)
                   for vector in prototype_vectors)):
        raise ValueError("Provide exactly three finite two-band prototype vectors")
    ordered = ee.ImageCollection(collection).sort("system:time_start")
    source = ee.Image(ordered.first()).select(BANDS).toFloat()
    spectrum = source.toArray(axis=0).toFloat()
    zero_distance = ee.Image(ee.Array([0])).toFloat()

    distances = []
    scores = []
    for prototype in prototype_vectors:
        reference = ee.Image(ee.Array(prototype)).toFloat()
        delta = spectrum.subtract(reference).toFloat()
        squared = delta.multiply(delta).toFloat()
        distance = squared.arrayReduce(ee.Reducer.sum(), axes=[0]).toFloat()
        distances.append(distance)
        scores.append(zero_distance.subtract(distance).toFloat())

    distance_vector = distances[0].arrayCat(distances[1], axis=0).arrayCat(
        distances[2], axis=0,
    )
    score_vector = scores[0].arrayCat(scores[1], axis=0).arrayCat(scores[2], axis=0)
    # The fixture midpoint is binary-exact, so explicit Float32 conversion keeps
    # its exact tie; arrayArgmax chooses the first equal maximum. Other decimal
    # ties can change under Float32 rounding and are not inferred from this case.
    selected_position = score_vector.arrayArgmax()

    return {
        "source_ids": ordered.aggregate_array("system:index"),
        "distances": distance_vector.arrayFlatten([prototype_ids]),
        "scores": score_vector.arrayFlatten([prototype_ids]),
        "selected_index": selected_position.arrayFlatten([["selected_prototype_index"]]),
        "calibration_tie_index": ee.Array([0.5, 0.5, -1]).argmax(),
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
        (root / "tests/fixtures/ee-spectral-prototypes-v1.json").read_text()
    )
    if fixture["schema"] != SYNTHETIC_VERSION:
        raise ValueError("Unexpected spectral prototype fixture version")
    catalog = [{
        "id": fixture["collection_id"],
        "cube:dimensions": {"bands": {"values": fixture["bands"]}},
    }]
    item = {
        "id": fixture["frame_id"],
        "bbox": fixture["bbox"],
        "geometry": fixture["scene_geometry"],
        "properties": {
            "system:index": fixture["frame_id"],
            "system:time_start": fixture["frame_time_millis"],
        },
    }
    ee = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=root / "vendor/earthengine-js/algorithms.json",
    )
    outputs = build_prototype_selection(
        ee, ee.ImageCollection(fixture["collection_id"]),
        fixture["prototype_ids"], fixture["prototype_vectors"],
    )
    for name, value in outputs.items():
        compiled = compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), catalog,
            {fixture["collection_id"]: [item]},
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
