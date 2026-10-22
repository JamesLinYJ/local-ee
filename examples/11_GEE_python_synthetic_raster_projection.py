"""Fit a static two-band PCA basis and apply it to an actual local Image.

The training table is versioned synthetic data. The caller supplies the raster;
no cloud collection, automatic download or Google computation is used.
"""

SYNTHETIC_VERSION = "local-ee-synthetic-raster-projection/v1"
BANDS = ["red", "nir"]
TRAINING = [[3, 2], [1, 0], [3, 1], [1, 1]]
PROPERTIES = ["system:index", "system:time_start"]


def build_projection(ee, image, training_rows=TRAINING):
    if len(training_rows) < 2:
        raise ValueError("Sample covariance requires at least two training rows")
    samples = ee.Array(training_rows)
    count = len(training_rows)
    mean_row = samples.reduce(ee.Reducer.mean(), [0])
    centered = samples.subtract(mean_row.repeat(0, count))
    denominator = ee.Array([[count - 1, count - 1], [count - 1, count - 1]])
    covariance = centered.matrixTranspose().matrixMultiply(centered).divide(denominator)
    basis = covariance.eigen().slice(1, 1)
    mean = mean_row.project([1])

    vector = image.select(BANDS).toArray().subtract(ee.Image(mean)).toArray(1)
    scores = ee.Image(basis).matrixMultiply(vector)
    components = scores.arrayProject([0]).arrayFlatten([["PC1", "PC2"]])
    reconstructed = ee.Image(basis.matrixTranspose()).matrixMultiply(scores)
    reconstructed = reconstructed.arrayProject([0]).add(ee.Image(mean)).arrayFlatten([BANDS])
    return {
        "components": ee.Image(components.copyProperties(image, PROPERTIES)),
        "reconstructed": ee.Image(reconstructed.copyProperties(image, PROPERTIES)),
    }


if __name__ == "__main__":
    import ee

    ee.Initialize()
    source = ee.ImageCollection("sentinel-2-l2a").first()
    outputs = build_projection(ee, source)
    print("Synthetic training fixture:", SYNTHETIC_VERSION)
    for name, value in outputs.items():
        print(name, value.bandNames().getInfo())
