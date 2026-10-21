"""Versioned synthetic table workflow; no imagery or Google computation.

Run in the Local EE Python editor. This example exercises metadata filtering,
table OLS, typed coefficients, a matrix prediction and local numeric formatting.
It does not demonstrate raster regression or a Google same-data comparison.
"""

SYNTHETIC_VERSION = "local-ee-synthetic-table/v1"
ROWS = [
    {"constant": 1, "day": 0, "temperature": 1, "valid": True},
    {"constant": 1, "day": 1, "temperature": 2, "valid": True},
    {"constant": 1, "day": 2, "temperature": 6, "valid": True},
    {"constant": 1, "day": 3, "temperature": None, "valid": True},
    {"constant": 1, "day": 4, "temperature": 1000, "valid": False},
]


def build_analysis(ee, rows=ROWS):
    samples = ee.FeatureCollection([ee.Feature(None, row) for row in rows])
    valid = samples.filter(ee.Filter.eq("valid", True)).filter(
        ee.Filter.notNull(["constant", "day", "temperature"]))
    fitted = valid.reduceColumns(
        reducer=ee.Reducer.linearRegression(numX=2, numY=1),
        selectors=["constant", "day", "temperature"],
    )
    coefficients = ee.Array(fitted.get("coefficients"))
    prediction = ee.Number(coefficients.transpose().matrixMultiply([[1], [3]]).get([0, 0]))
    total = valid.iterate(
        lambda row, accumulator: ee.Number(accumulator).add(
            ee.Number(ee.Feature(row).get("temperature"))), ee.Number(0))
    return {
        "sample_count": valid.size(),
        "temperature_sum": ee.Number(total),
        "fit": fitted,
        "prediction_day_3": prediction,
        "prediction_formatted": prediction.format("%.2f"),
    }


if __name__ == "__main__":
    import ee

    ee.Initialize()
    print("Synthetic fixture:", SYNTHETIC_VERSION)
    for name, value in build_analysis(ee).items():
        print(name, value.getInfo())
