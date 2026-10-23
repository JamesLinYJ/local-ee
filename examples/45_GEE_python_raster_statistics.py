"""Numeric reducers over bands, observations and an explicit array field axis.

Pass a locally ingested collection. Multiple observations require declared
aligned STAC projection grids; export scale is not source alignment evidence.
"""


def build_workflow(ee, collection):
    reducer = (ee.Reducer.variance()
               .combine(ee.Reducer.stdDev(), sharedInputs=True)
               .combine(ee.Reducer.sampleVariance().setOutputs(["sample_var"]), sharedInputs=True)
               .combine(ee.Reducer.minMax(), sharedInputs=True)
               .combine(ee.Reducer.product(), sharedInputs=True))
    first = collection.first()
    selected = collection.toList(2)
    repeated = ee.ImageCollection.fromImages([
        ee.Image(selected.get(0)), ee.Image(selected.get(1)), ee.Image(selected.get(0)),
    ])
    return {
        "band_stats": first.reduce(reducer),
        "time_stats": collection.reduce(reducer),
        "repeated_stats": repeated.reduce(reducer),
        "array_stats": first.toArray().toArray(1).arrayReduce(reducer, [0], 1)
            .arrayFlatten([["bands"], ["variance", "stdDev", "sample_var", "min", "max", "product"]]),
        "static_stats": ee.Array([[1], [3], [5]]).reduce(reducer, [0], 1),
    }
