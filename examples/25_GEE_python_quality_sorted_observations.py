"""Rank coupled NDVI/day observations by local quality values.

This is a versioned synthetic compatibility workflow. Lower cloud_score is
better. Equal Float32 keys keep the original collection order in the local
implementation. No provider QA interpretation or Google comparison is implied.
"""
import ee


SYNTHETIC_VERSION = "local-ee-quality-sorted-observations/v1"
COLLECTION_ID = "sentinel-2-l2a"
START = "2024-01-01"


def build_outputs():
    def add_observation(image):
        ndvi = image.expression(
            "(nir-red)/(nir+red)",
            {"nir": image.select("nir"), "red": image.select("red")},
        ).rename("ndvi")
        day = ee.Image.constant(image.date().difference(ee.Date(START), "day")).rename("day")
        return image.addBands(ndvi).addBands(day)

    series = ee.ImageCollection(COLLECTION_ID).sort("system:time_start").map(add_observation)
    arrays = series.select(["ndvi", "day", "cloud_score"]).toArrayPerBand()
    lengths = ee.Image.constant(ee.Array([4, 1]))
    ndvi = arrays.select("ndvi").arrayReshape(lengths, 2).toFloat()
    day = arrays.select("day").arrayReshape(lengths, 2).toFloat()
    quality = arrays.select("cloud_score").arrayReshape(lengths, 2).toFloat()
    observations = ndvi.arrayCat(day, 1)
    ordered = observations.arraySort(quality)
    best_two = ordered.arraySlice(0, 0, 2)
    best_ndvi = best_two.arraySlice(1, 0, 1).arrayProject([0])
    return {
        "ordered": ordered,
        "best_two": best_two,
        "best_mean": best_ndvi.arrayReduce(ee.Reducer.mean(), [0]).arrayGet([0]).rename("best_mean"),
    }


def main():
    outputs = build_outputs()
    print("Synthetic quality-ranked NDVI/day workflow:", SYNTHETIC_VERSION)
    print("Requires the explicitly registered four-scene synthetic catalogue.")
    Map.addLayer(outputs["best_mean"], {"min": -1, "max": 1}, "Best two observations")


if __name__ == "__main__":
    main()
