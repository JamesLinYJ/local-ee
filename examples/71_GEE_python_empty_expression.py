"""Map-only Image.expression and empty receiver workflows using official EE SDK calls.

The expression receiver is the official transparent one-band Image(), not a
zero-band identity. Values from the finite synthetic fixture are checked by
the independent Wave67 reference and native sample probe.
"""
from __future__ import annotations


SYNTHETIC_VERSION = "local-ee-empty-expression-wave67/v1"
FIXTURE_PATH = "tests/fixtures/ee-empty-expression-wave67-v1.json"


def build_expression_images(ee, image):
    source = ee.Image(image)
    receiver = ee.Image()
    red = source.select("red")
    nir = source.select("nir")
    spectrum = source.select(["red", "nir"])

    return {
        "named_sum": receiver.expression(
            "nir + red", {"nir": nir, "red": red},
        ).rename("named_sum"),
        "dot_red": receiver.expression(
            "spectrum.red", {"spectrum": spectrum},
        ).rename("dot_red"),
        "index_red": receiver.expression(
            "spectrum[0]", {"spectrum": spectrum},
        ).rename("index_red"),
        "index_nir": receiver.expression(
            "spectrum[1]", {"spectrum": spectrum},
        ).rename("index_nir"),
        "assigned": receiver.expression(
            "assigned = red + 2", {"red": red},
        ),
        "default_call": receiver.expression("b()"),
        "default_index": receiver.expression("b(0)"),
        "default_name": receiver.expression("b('constant')"),
        "default_index_plus_red": receiver.expression(
            "b(0) + red", {"red": red},
        ).rename("default_index_plus_red"),
        "unweighted_nd": receiver.expression(
            "(nir - red) / (nir + red)", {"nir": nir, "red": red},
        ).rename("unweighted_nd"),
        "normalized_difference": source.normalizedDifference(
            ["nir", "red"],
        ).rename("normalized_difference"),
    }


def build_workflow(ee, image, fixture):
    source = ee.Image(image)
    expressions = build_expression_images(ee, source)
    map_names = (
        "named_sum", "dot_red", "index_red", "index_nir", "assigned",
        "unweighted_nd", "normalized_difference",
    )
    default_names = ("default_call", "default_index", "default_name",
                     "default_index_plus_red")
    region = ee.Geometry(fixture["region"])
    map_values = ee.Image.cat(*[expressions[name] for name in map_names])
    default_values = ee.Image.cat(*[expressions[name] for name in default_names])

    science = source.select("mask_science").toDouble()
    old_weight = source.select("old_weight")
    new_weight = source.select("new_weight")
    previously_masked = science.updateMask(old_weight)
    replaced = previously_masked.mask(new_weight)
    updated = previously_masked.updateMask(new_weight)
    hidden_recovery = (
        source.select("red").toDouble().updateMask(0.25).updateMask(0).mask(1)
        .rename("fractional_hidden_recovery")
    )

    return {
        "map_values": map_values,
        "default_values": default_values,
        "default_weights": default_values.mask(),
        "setter_values": replaced,
        "setter_weights": replaced.mask(),
        "update_mask_values": updated,
        "update_mask_weights": updated.mask(),
        "fractional_hidden_recovery": hidden_recovery,
        "map_sample": map_values.sample(region=region, dropNulls=False, geometries=True),
        "default_value_sample": default_values.sample(
            region=region, dropNulls=False, geometries=True,
        ),
        "default_weight_sample": default_values.mask().sample(
            region=region, dropNulls=False, geometries=True,
        ),
        "setter_value_sample": replaced.sample(
            region=region, dropNulls=False, geometries=True,
        ),
        "setter_weight_sample": replaced.mask().sample(
            region=region, dropNulls=False, geometries=True,
        ),
        "update_mask_value_sample": updated.sample(
            region=region, dropNulls=False, geometries=True,
        ),
        "update_mask_weight_sample": updated.mask().sample(
            region=region, dropNulls=False, geometries=True,
        ),
        "fractional_hidden_recovery_value_sample": hidden_recovery.sample(
            region=region, dropNulls=False, geometries=True,
        ),
        "fractional_hidden_recovery_weight_sample": hidden_recovery.mask().sample(
            region=region, dropNulls=False, geometries=True,
        ),
    }


def synthetic_metadata(fixture):
    bands = fixture["source_bands"]
    grid = fixture["grid"]
    collection = {"id": fixture["source_id"], "cube:dimensions": {
        "bands": {"values": bands},
    }}
    bbox = [grid["xmin"], grid["ymin"], grid["xmax"], grid["ymax"]]
    item = {
        "id": "wave67-empty-expression-source",
        "bbox": bbox,
        "geometry": {"type": "Polygon", "coordinates": [[
            [bbox[0], bbox[1]], [bbox[2], bbox[1]], [bbox[2], bbox[3]],
            [bbox[0], bbox[3]], [bbox[0], bbox[1]],
        ]]},
        "properties": {
            "system:index": "wave67-empty-expression-source",
            "system:time_start": 1,
            "proj:code": "EPSG:4326",
            "proj:transform": [1, 0, 0, 0, -1, grid["ymax"]],
        },
        "assets": {
            band: {"proj:shape": [grid["tile_rows"], grid["tile_cols"]],
                   "proj:epsg": 4326,
                   "proj:transform": [1, 0, 0, 0, -1, grid["ymax"]]}
            for band in bands
        },
    }
    return [{"id": collection["id"], **collection}], {collection["id"]: [item]}
