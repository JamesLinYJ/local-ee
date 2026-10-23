"""Build a local, explicitly synthetic QA bit field from SCL categories.

The example compiles against a versioned metadata-only fixture using the
locally accepted ``sentinel-2-l2a`` collection ID and band labels. It does not
read raster files, request a Google collection, or claim that these bits match
QA60, Landsat QA_PIXEL, or any upstream product. The flag layout below is an
example contract defined here for testing integer image operations.
"""


ROI = [100.2, 30.2, 100.8, 30.8]
EXPORT_REGION = [
    [[100.2, 30.2], [100.8, 30.2], [100.8, 30.8],
     [100.2, 30.8], [100.2, 30.2]],
]

CLOUD_BITS = (1 << 0) | (1 << 1) | (1 << 2)
INVALID_BITS = (1 << 7) - 1
FLOAT32_INTEGER_LIMIT = 2**24
EXACT_FLOAT64_INTEGER_LIMIT = 2**53


def _flag(scl, category, bit):
    """Set one synthetic QA bit when a local SCL category matches."""
    return scl.eq(category).toUint8().leftShift(bit)


def build_workflow(ee, collection):
    scene = collection.first()
    # SCL is categorical. Cast it before packing flags so the example exercises
    # an explicit unsigned category conversion without doing Float64 arithmetic.
    scl = scene.select("SCL").toUint8()

    synthetic_cloud_qa = (
        _flag(scl, 8, 0)
        .bitwiseOr(_flag(scl, 9, 1))
        .bitwiseOr(_flag(scl, 10, 2))
    )
    synthetic_shadow_qa = _flag(scl, 3, 3)
    synthetic_snow_qa = _flag(scl, 11, 4)
    synthetic_invalid_qa = _flag(scl, 0, 5).bitwiseOr(_flag(scl, 1, 6))
    packed_qa = (
        synthetic_cloud_qa
        .bitwiseOr(synthetic_shadow_qa)
        .bitwiseOr(synthetic_snow_qa)
        .bitwiseOr(synthetic_invalid_qa)
        .toUint8()
        .rename("synthetic_qa")
    )

    cloud_clear = packed_qa.bitwiseAnd(CLOUD_BITS).eq(0).rename("cloud_clear")
    surface_clear = packed_qa.bitwiseAnd(INVALID_BITS).eq(0).rename("surface_clear")
    masked_ndvi = (
        scene.select(["nir", "red"]).toFloat()
        .updateMask(surface_clear)
        .normalizedDifference(["nir", "red"])
        .rename("masked_ndvi")
    )

    # Exercise an actual raster-backed high bit without general arithmetic:
    # the admitted SCL categories fit exactly after a 40-bit integer shift.
    shifted_category_bit = scl.leftShift(40).bitwiseAnd(1 << 40)
    dynamic_high_bit = shifted_category_bit.eq(1 << 40).rename("category_bit_40")

    # Integer shifts/OR produce high-magnitude values from actual SCL pixels;
    # no Float32 cast or generic arithmetic is used before the comparisons.
    comparison_mask = scl.gte(0)
    wider_than_float32 = (
        scl.toInt32().leftShift(24).bitwiseOr(1)
        .updateMask(comparison_mask)
    )
    wide_comparisons = {
        "wide_eq": wider_than_float32.eq(FLOAT32_INTEGER_LIMIT + 1),
        "wide_neq": wider_than_float32.neq(FLOAT32_INTEGER_LIMIT),
        "wide_lt": wider_than_float32.lt(FLOAT32_INTEGER_LIMIT + 2),
        "wide_lte": wider_than_float32.lte(FLOAT32_INTEGER_LIMIT + 1),
        "wide_gt": wider_than_float32.gt(FLOAT32_INTEGER_LIMIT),
        "wide_gte": wider_than_float32.gte(FLOAT32_INTEGER_LIMIT + 1),
    }

    # The predicate is dynamic, but its 0/1 SCL source makes the 53-bit shift
    # land only on exactly representable values 0 and 2**53.
    int64_upper = (
        scl.eq(1).toInt64().leftShift(53)
        .updateMask(comparison_mask)
    )
    exact_boundary = {
        "int64_at_upper_bound": int64_upper.eq(EXACT_FLOAT64_INTEGER_LIMIT),
        "int64_above_previous": int64_upper.gt(EXACT_FLOAT64_INTEGER_LIMIT - 1),
        "int64_not_above_bound": int64_upper.lte(EXACT_FLOAT64_INTEGER_LIMIT),
    }
    return {
        "packed_qa": packed_qa,
        "cloud_clear": cloud_clear,
        "surface_clear": surface_clear,
        "masked_ndvi": masked_ndvi,
        "dynamic_high_bit": dynamic_high_bit,
        **wide_comparisons,
        **exact_boundary,
        "negative_bit_count": ee.Image.constant(-1).updateMask(comparison_mask).bitCount(),
        "signed_shift_63": ee.Image.constant(-1).updateMask(comparison_mask).rightShift(63),
    }


def build_export_task(ee, image):
    return ee.batch.Export.image.toDrive(
        image,
        description="synthetic_integer_qa_masked_ndvi",
        folder="integer-images",
        fileNamePrefix="synthetic_integer_qa_masked_ndvi",
        region=EXPORT_REGION,
        scale=10,
        crs="EPSG:32649",
        maxPixels=100_000,
    )


if __name__ == "__main__":
    outputs = build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))  # noqa: F821
    Map.addLayer(  # noqa: F821
        outputs["cloud_clear"],
        {"min": 0, "max": 1, "palette": ["000000", "00aaff"]},
        "Synthetic cloud-clear mask",
    )
    Export.image.toDrive(  # noqa: F821
        image=outputs["masked_ndvi"],
        description="synthetic_integer_qa_masked_ndvi",
        folder="integer-images",
        fileNamePrefix="synthetic_integer_qa_masked_ndvi",
        region=EXPORT_REGION,
        scale=10,
        crs="EPSG:32649",
        maxPixels=100_000,
    )
