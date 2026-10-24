"""Build a zero-band schema seed and accumulate two real local scenes."""


SYNTHETIC_VERSION = "local-ee-bandless-wave68/v1"
FIXTURE_PATH = "tests/fixtures/ee-bandless-wave68-v1.json"


def build_workflow(ee, fixture):
    collection = ee.ImageCollection(fixture["source_id"])
    scenes = ee.List(collection.toList(2))
    first = ee.Image(scenes.get(0))
    second = ee.Image(scenes.get(1))

    # Image() is a masked one-band image; select([]) makes the schema seed.
    empty = ee.Image().select([])
    seed = empty.set("seed", "wave68")
    accumulated = ee.Image(scenes.iterate(
        lambda scene, acc: ee.Image(acc).addBands(
            ee.Image(scene).select(["red", "nir"]),
        ),
        seed,
    ))
    red_total = accumulated.select("red").add(
        accumulated.select("red_1"),
    ).rename("red_total")
    nir_total = accumulated.select("nir").add(
        accumulated.select("nir_1"),
    ).rename("nir_total")
    science = accumulated.addBands(red_total).addBands(nir_total)
    region = ee.Geometry(fixture["region"])

    return {
        "empty": empty,
        "empty_metadata": empty.copyProperties(
            first, ["system:index", "system:time_start", "scene_label"],
        ).set("seed", "wave68"),
        "source_empty_metadata": first.select([]).rename([]).copyProperties(
            first, ["system:index", "system:time_start", "scene_label"],
        ).set("seed", "wave68"),
        "empty_add_source": empty.addBands(first.select(["red", "nir"])),
        "source_add_empty": first.addBands(empty),
        "empty_add_empty": empty.addBands(empty),
        "ordered_add": empty.addBands(first.select(["nir", "red"])),
        "collision_default": first.select(["nir", "red"]).addBands(
            second.select(["red", "nir"]),
        ),
        "collision_overwrite": first.select(["nir", "red"]).addBands(
            second.select(["red", "nir"]), overwrite=True,
        ),
        "accumulated": accumulated,
        "science": science,
        "samples": science.sample(
            region=region, dropNulls=False, geometries=True,
        ),
        # Captured as an official SDK wire; local execution uses the supported
        # List.iterate over the bounded result of Collection.toList above.
        "collection_iterate": ee.Image(ee.ImageCollection.fromImages(
            [first, second],
        ).iterate(
            lambda scene, acc: ee.Image(acc).addBands(
                ee.Image(scene).select(["red", "nir"]),
            ),
            empty,
        )),
    }
