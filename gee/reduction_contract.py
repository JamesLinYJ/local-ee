"""Closed scalar reducer names shared by graph validation and engine bridge."""

EE_BAND_REDUCERS = frozenset({
    "mean", "median", "min", "max", "sum", "count", "first", "last", "sd",
    "product", "stdDev", "variance", "sampleVariance",
})

# Unlike identity reducers, these must execute even for one observation.
SINGLE_OBSERVATION_KERNELS = frozenset({
    "count", "sd", "product", "stdDev", "variance", "sampleVariance",
})
