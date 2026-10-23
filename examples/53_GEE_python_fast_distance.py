"""Local Sentinel-2-style water proximity and morphology expressions.

The examples use the pinned official client and locally catalogued synthetic
SCL/NIR/red bands. They build lazy graphs; they do not fetch Google imagery or
start a raster job.
"""


ROI = [100.2, 30.2, 100.8, 30.8]
EXPORT_REGION = [
    [[100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
     [100.2, 30.8], [100.2, 30.2]],
]


def build_workflow(ee, collection):
    scene = collection.first()
    scl = scene.select("SCL")
    water = scl.eq(6).rename("water_target")

    default_distance = water.fastDistanceTransform()
    water_dilation = default_distance.sqrt().lt(3).rename("water_dilation_3px")
    land = scl.neq(6)
    land_distance = land.fastDistanceTransform(neighborhood=32)
    water_erosion = water.multiply(
        land_distance.sqrt().gt(1)
    ).rename("water_erosion_1px")

    return {
        "default_distance": default_distance,
        "explicit_default_distance": water.fastDistanceTransform(
            neighborhood=256, units="pixels", metric="squared_euclidean",
        ),
        "null_default_distance": water.fastDistanceTransform(
            neighborhood=None, units=None, metric=None,
        ),
        "squared_euclidean": water.fastDistanceTransform(
            neighborhood=32, units="pixels", metric="squared_euclidean",
        ),
        "manhattan": water.fastDistanceTransform(
            neighborhood=32, units="pixels", metric="manhattan",
        ),
        "chebyshev": water.fastDistanceTransform(
            neighborhood=32, units="pixels", metric="chebyshev",
        ),
        "water_dilation": water_dilation,
        "water_erosion": water_erosion,
        "masked_double_distance": water.toDouble().updateMask(
            scl.gte(0)
        ).fastDistanceTransform(neighborhood=24),
        "multiband_distance": scene.select(["nir", "red"]).fastDistanceTransform(
            neighborhood=32,
        ),
        "observation_distance": collection.select("SCL").map(
            lambda image: image.eq(6).fastDistanceTransform(
                neighborhood=32,
            ).rename("water_distance")
        ),
        # Restrict the displayed/exported result after the transform so the
        # search sees the source image's full finite extent.
        "export_image": water_dilation.clip(ee.Geometry.Rectangle(
            ROI, "EPSG:4326", False,
        )),
    }


def build_export_task(ee, image):
    return ee.batch.Export.image.toDrive(
        image,
        description="synthetic_water_fast_distance",
        folder="distance",
        fileNamePrefix="synthetic_water_fast_distance",
        region=EXPORT_REGION,
        scale=10,
        crs="EPSG:32649",
        maxPixels=100_000,
    )


if __name__ == "__main__":
    outputs = build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))  # noqa: F821
    Map.addLayer(  # noqa: F821
        outputs["water_dilation"],
        {"min": 0, "max": 1, "palette": ["000000", "00aaff"]},
        "Water dilation (three pixels)",
    )
    Export.image.toDrive(  # noqa: F821
        image=outputs["export_image"],
        description="synthetic_water_fast_distance",
        region=EXPORT_REGION,
        scale=10,
        crs="EPSG:32649",
        maxPixels=100_000,
    )
