"""Fit two synthetic responses from column lists and predict with typed arrays."""

SYNTHETIC_VERSION = "local-ee-synthetic-list-regression/v1"
TIMES = [-2, -1, 0, 1, 2, 3]
FIRST_RESPONSE = [-6, 1.5, -2, 3.5, 3, 2.5]
SECOND_RESPONSE = [1.5, 5.25, -8, 1.75, 4.5, 12.25]


def build_prediction(ee, times, first_response, second_response, target=4):
    x = ee.List(times)
    square = x.map(lambda value: ee.Number(value).pow(2))
    # Unlike zip/unzip's normal truncation contract, this scientific workflow
    # requires aligned observations; verify lengths before assembling rows.
    first, second = ee.List(first_response), ee.List(second_response)
    aligned = ee.Algorithms.If(x.length().eq(first.length()),
        x.length().eq(second.length()), False)
    rows = ee.List([ee.List.repeat(1, x.length()), x, square, first, second]).unzip()
    fitted = ee.Dictionary(rows.reduce(ee.Reducer.linearRegression(3, 2)))
    coefficients = ee.Array(fitted.get("coefficients"))
    prediction = ee.Array([[1, target, target**2]]).matrixMultiply(coefficients)
    return ee.Dictionary(ee.Algorithms.If(aligned, ee.Dictionary({
        "coefficients": coefficients,
        "residual_rms": fitted.get("residuals"),
        "prediction": prediction,
        "rows": rows.length(),
    }), ee.Dictionary({"error": "Input column lengths must match"})))


if __name__ == "__main__":
    import ee

    ee.Initialize()
    print("Synthetic sample:", SYNTHETIC_VERSION)
    print(build_prediction(ee, TIMES, FIRST_RESPONSE, SECOND_RESPONSE).getInfo())
