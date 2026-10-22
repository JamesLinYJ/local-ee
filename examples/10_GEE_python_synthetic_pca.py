"""Static synthetic PCA through the pinned Local EE Python Array API.

Run in the Local EE Python editor. This is a versioned table/matrix example;
it does not load imagery, call Google, or demonstrate raster Image.array*.
"""

SYNTHETIC_VERSION = "local-ee-synthetic-pca/v1"
ROWS = [[3, 2], [1, 0], [3, 1], [1, 1]]


def build_pca(ee, rows=ROWS):
    if len(rows) < 2:
        raise ValueError("Sample covariance requires at least two rows")
    samples = ee.Array(rows)
    shape = samples.length()
    count, columns = ee.Number(shape.get([0])), ee.Number(shape.get([1]))
    means = samples.reduce(ee.Reducer.mean(), [0])
    mean_rows = means.repeat(axis=0, copies=count)
    centered = samples.subtract(mean_rows)
    denominator = ee.Array([[count.subtract(1)]]).repeat(0, columns).repeat(1, columns)
    covariance = centered.matrixTranspose().matrixMultiply(centered).divide(denominator)
    eigen = covariance.eigen()
    eigenvalues = eigen.slice(axis=1, start=0, end=1).project([0])
    eigenvectors = eigen.slice(axis=1, start=1)
    scores = centered.matrixMultiply(eigenvectors.matrixTranspose())
    score_covariance = scores.matrixTranspose().matrixMultiply(scores).divide(denominator)
    return {
        "means": means.project([1]),
        "covariance": covariance,
        "eigenvalues": eigenvalues,
        "eigenvectors": eigenvectors,
        "scores": scores,
        "score_covariance": score_covariance,
        "reconstructed_samples": scores.matrixMultiply(eigenvectors).add(mean_rows),
    }


if __name__ == "__main__":
    import ee

    ee.Initialize()
    print("Synthetic fixture:", SYNTHETIC_VERSION)
    for name, value in build_pca(ee).items():
        print(name, value.getInfo())
