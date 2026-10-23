"""Local NDVI neighborhood statistics and convolution examples.

The caller supplies a catalogued three-scene red/NIR collection with a declared
native grid. All returned Images and collections are lazy local EE expressions;
no Google service or remote catalog is used here.
"""


ROI = [100.2, 30.2, 100.8, 30.8]


def build_workflow(ee, collection):
    source = collection.first().select(["red", "nir"])
    ndvi = source.normalizedDifference(["nir", "red"]).rename("NDVI").toFloat()
    gaussian = ee.Kernel.gaussian(radius=1, sigma=1)
    unit = ee.Kernel.square(radius=1, units="pixels", normalize=False)
    half = ee.Kernel.fixed(
        3, 3, [[0.5, 0.5, 0.5], [0.5, 0.5, 0.5], [0.5, 0.5, 0.5]], 1, 1
    )
    clipped = ndvi.clip(ee.Geometry.Rectangle(ROI, "EPSG:4326", False))

    weighted = (
        ee.Reducer.sum()
        .combine(reducer2=ee.Reducer.mean(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.variance(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.stdDev(), sharedInputs=True)
    )
    weighted_sum_median = ee.Reducer.sum().combine(
        reducer2=ee.Reducer.median(), sharedInputs=True
    )
    unit_statistics = (
        ee.Reducer.product()
        .combine(reducer2=ee.Reducer.sampleVariance(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.sampleStdDev(), sharedInputs=True)
    )
    # Weighted reducers precede unweighted reducers as required by the EE API.
    shared_statistics = (
        ee.Reducer.mean()
        .combine(reducer2=ee.Reducer.stdDev(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.minMax(), sharedInputs=True)
        .combine(reducer2=ee.Reducer.count(), sharedInputs=True)
        .setOutputs(["average", "spread", "low", "high", "observations"])
    )
    capped_gaussian = ee.Kernel.gaussian(
        radius=1, sigma=0.5, normalize=False, magnitude=4
    )
    inverse_gaussian = ee.Kernel.gaussian(
        radius=1, sigma=0.5, normalize=False
    ).inverse()

    convolved = ndvi.convolve(gaussian)
    return {
        "ndvi": ndvi,
        "weighted_gaussian": ndvi.reduceNeighborhood(weighted, gaussian),
        "weighted_sum_median": ndvi.reduceNeighborhood(
            weighted_sum_median, half
        ),
        "weighted_count": ndvi.reduceNeighborhood(ee.Reducer.count(), gaussian),
        "unit_product_sample_stats": ndvi.reduceNeighborhood(unit_statistics, unit),
        "min_clipped_mask": clipped.reduceNeighborhood(
            ee.Reducer.min(), capped_gaussian, inputWeight="min"
        ),
        "mask_weight_mean": clipped.reduceNeighborhood(
            ee.Reducer.mean(), gaussian, inputWeight="mask"
        ),
        "unweighted_mean": ndvi.reduceNeighborhood(
            ee.Reducer.mean().unweighted(), capped_gaussian
        ),
        "shared_statistics": ndvi.reduceNeighborhood(shared_statistics, unit),
        "collection_texture": collection.map(
            lambda image: image.normalizedDifference(["nir", "red"])
            .rename("NDVI").toFloat()
            .reduceNeighborhood(ee.Reducer.stdDev(), unit)
        ),
        "multiband_mean": source.reduceNeighborhood(ee.Reducer.mean(), unit),
        "convolve_texture": convolved.reduceNeighborhood(
            ee.Reducer.stdDev(), unit
        ),
        "convolve_euclidean": ndvi.convolve(ee.Kernel.euclidean(radius=1)),
        "convolve_manhattan": ndvi.convolve(ee.Kernel.manhattan(radius=1)),
        "convolve_chebyshev": ndvi.convolve(ee.Kernel.chebyshev(radius=1)),
        "convolve_compass": ndvi.convolve(ee.Kernel.compass()),
        "convolve_kirsch": ndvi.convolve(ee.Kernel.kirsch()),
        "convolve_inverse": ndvi.convolve(inverse_gaussian),
    }


if __name__ == "__main__":
    outputs = build_workflow(ee, ee.ImageCollection("sentinel-2-l2a"))  # noqa: F821
    Map.addLayer(outputs["ndvi"], {"min": -1, "max": 1}, "NDVI")  # noqa: F821
    Map.addLayer(outputs["convolve_texture"], {"min": 0, "max": 0.3},  # noqa: F821
                 "NDVI neighborhood standard deviation")
    Export.image.toDrive(image=outputs["convolve_texture"],  # noqa: F821
                         description="local_ndvi_texture", fileFormat="GeoTIFF")
