"""Bounded pixel distance kernels over locally catalogued synthetic scenes.

This example only builds lazy official-client expressions. It does not fetch
Google imagery or start raster execution. The distance image is Float64; cast
to Float32 before the ordinary comparison shown here.
"""


ROI = [100.2, 30.2, 100.8, 30.8]
EXPORT_REGION = [
    [[100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
     [100.2, 30.8], [100.2, 30.2]],
]


def build_workflow(ee, collection):
    scene = collection.first()
    roi = ee.Geometry.Rectangle(ROI, "EPSG:4326", False)
    euclidean = ee.Kernel.euclidean(
        radius=3, units="pixels", normalize=False, magnitude=1,
    )
    manhattan = ee.Kernel.manhattan(
        radius=3, units="pixels", normalize=False, magnitude=1,
    )
    chebyshev = ee.Kernel.chebyshev(
        radius=3, units="pixels", normalize=False, magnitude=1,
    )

    water_targets = scene.select("SCL").eq(6).rename("water_target")
    water_distance = water_targets.distance(euclidean, skipMasked=True)
    water_buffer = water_distance.toFloat().lte(2).rename("water_within_2_pixels")
    masked_clipped_distance = (
        scene.select("nir")
        .updateMask(scene.select("SCL").gte(0))
        .clip(roi)
        .distance(euclidean)
    )
    multi_band_distance = scene.select(["nir", "red"]).distance(euclidean)
    observation_distance = collection.select("SCL").map(
        lambda image: image.eq(6).distance(euclidean).rename("water_distance")
    )
    clipped = water_buffer.clip(roi)

    return {
        "euclidean": scene.select("nir").distance(euclidean),
        "manhattan": scene.select("nir").distance(manhattan),
        "chebyshev": scene.select("nir").distance(chebyshev),
        "water_distance": water_distance,
        "water_buffer": water_buffer,
        "masked_clipped_distance": masked_clipped_distance,
        "multi_band_distance": multi_band_distance,
        "observation_distance": observation_distance,
        "clipped_water_buffer": clipped,
    }


def build_export_task(ee, image):
    roi = ee.Geometry.Rectangle(ROI, "EPSG:4326", False)
    return ee.batch.Export.image.toDrive(
        image,
        description="synthetic_water_distance_buffer",
        folder="distance",
        fileNamePrefix="synthetic_water_distance_buffer",
        region=EXPORT_REGION,
        scale=10,
        crs="EPSG:32649",
        maxPixels=100_000,
    )


if __name__ == "__main__":
    outputs = build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))  # noqa: F821
    Map.addLayer(  # noqa: F821
        outputs["clipped_water_buffer"],
        {"min": 0, "max": 1, "palette": ["000000", "00aaff"]},
        "Water within two pixels",
    )
    Export.image.toDrive(  # noqa: F821
        image=outputs["clipped_water_buffer"],
        description="synthetic_water_distance_buffer",
        region=EXPORT_REGION,
        scale=10,
        crs="EPSG:32649",
        maxPixels=100_000,
    )
