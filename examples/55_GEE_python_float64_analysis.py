"""Offline Double-precision raster workflow over a synthetic metadata fixture.

The fixture keeps the admitted local optical sample's source ID, geometry, and
grid while explicitly declaring one additional synthetic temperature band in
test metadata. No raster values are embedded here and no ERA5 or Google
collection is requested.
"""


COLLECTION_ID = "sentinel-2-l2a"
TEMPERATURE_BAND = "synthetic_temperature_millikelvin"
TEMPERATURE_SCALE = 0.001
TEMPERATURE_OFFSET_K = 0.0
PIXEL_SIZE_METRES = 10
ROI = [100.2, 30.2, 100.8, 30.8]
EXPORT_REGION = [
    [[100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
     [100.2, 30.8], [100.2, 30.2]],
]
CLOUD_BITS = (1 << 0) | (1 << 1) | (1 << 2)


def build_workflow(ee, collection):
    scene = collection.first()
    scl = scene.select("SCL")

    # QA flags and follow-on arithmetic retain the integer cast's Double
    # marker; no Float32 conversion is needed for this QA processing.
    qa_packed = (
        scl.eq(8).toUint8().leftShift(0)
        .bitwiseOr(scl.eq(9).toUint8().leftShift(1))
        .bitwiseOr(scl.eq(10).toUint8().leftShift(2))
        .rename("synthetic_cloud_qa")
    )
    qa_numeric = qa_packed.toUint8().multiply(2).add(1).rename("qa_numeric")
    qa_clear = qa_packed.bitwiseAnd(CLOUD_BITS).eq(0).rename("qa_clear")

    # Double inputs retain the existing normalizedDifference negative-value
    # mask. The expression and explicit core formula also expose the signed
    # normalized difference without that extra negative-input mask.
    optical = scene.select(["nir", "red"]).toDouble()
    nir = optical.select("nir")
    red = optical.select("red")
    normalized_ndvi = optical.normalizedDifference(["nir", "red"]).rename(
        "normalized_ndvi"
    )
    signed_ndvi = scene.expression(
        expression="(nir - red) / (nir + red)",
        map_={"nir": nir, "red": red},
    ).rename("signed_ndvi")
    signed_ndvi_core = nir.subtract(red).divide(nir.add(red)).rename(
        "signed_ndvi_core"
    )

    # This fixture-only band is declared in the synthetic collection metadata
    # as millikelvin. Its conversion is not a claim about ERA5 or Sentinel-2.
    synthetic_temperature_celsius = (
        scene.select(TEMPERATURE_BAND).toDouble()
        .multiply(TEMPERATURE_SCALE)
        .add(TEMPERATURE_OFFSET_K)
        .subtract(273.15)
        .rename("synthetic_temperature_celsius")
    )

    # fastDistanceTransform yields squared-pixel values. Convert its result to
    # Double before sqrt and apply this fixture's declared 10 m pixel size.
    water_distance_pixels = (
        scl.eq(6).fastDistanceTransform(neighborhood=8)
        .toDouble().sqrt().rename("water_distance_pixels")
    )
    water_distance_metres = water_distance_pixels.multiply(
        PIXEL_SIZE_METRES
    ).rename("water_distance_metres")

    # Control path: explicit Float32 operands keep the prior Float32 graph.
    float32_difference = (
        scene.select("nir").toFloat()
        .subtract(scene.select("red").toFloat())
        .rename("float32_difference")
    )

    analysis = (
        signed_ndvi.addBands(normalized_ndvi)
        .addBands(qa_numeric)
        .addBands(qa_clear)
        .addBands(synthetic_temperature_celsius)
        .addBands(water_distance_metres)
    )
    return {
        "qa_packed": qa_packed,
        "qa_numeric": qa_numeric,
        "qa_clear": qa_clear,
        "normalized_ndvi": normalized_ndvi,
        "signed_ndvi": signed_ndvi,
        "signed_ndvi_core": signed_ndvi_core,
        "synthetic_temperature_celsius": synthetic_temperature_celsius,
        "water_distance_pixels": water_distance_pixels,
        "water_distance_metres": water_distance_metres,
        "float32_difference": float32_difference,
        "analysis": analysis,
    }


def build_export_task(ee, image):
    return ee.batch.Export.image.toDrive(
        image,
        description="synthetic_float64_analysis",
        folder="float64-analysis",
        fileNamePrefix="synthetic_float64_analysis",
        region=EXPORT_REGION,
        scale=PIXEL_SIZE_METRES,
        crs="EPSG:32649",
        maxPixels=100_000,
    )


if __name__ == "__main__":
    outputs = build_workflow(  # noqa: F821
        ee, ee.ImageCollection(COLLECTION_ID),
    )
    Map.addLayer(  # noqa: F821
        outputs["signed_ndvi"], {"min": -1, "max": 1},
        "Signed Double NDVI (synthetic fixture)",
    )
    Export.image.toDrive(  # noqa: F821
        image=outputs["analysis"],
        description="synthetic_float64_analysis",
        folder="float64-analysis",
        fileNamePrefix="synthetic_float64_analysis",
        region=EXPORT_REGION,
        scale=PIXEL_SIZE_METRES,
        crs="EPSG:32649",
        maxPixels=100_000,
    )
