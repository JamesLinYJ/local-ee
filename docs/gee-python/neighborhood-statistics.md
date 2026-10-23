# Neighborhood image statistics

`Image.reduceNeighborhood` compiles for scalar-band images and fixed pixel
kernels. It runs once for each input band and appends each reducer output name,
for example `nir_sum` or `nir_high`. Supported statistics are `sum`, `mean`,
`count`, `min`, `max`, population `variance` and `stdDev`,
`sampleVariance` and `sampleStdDev`, `product`, `median`, and default `mode`.
Numeric single-input leaves can be combined with `sharedInputs=true`, and
`setOutputs` may rename or drop outputs. `minMax` expands to `min` and `max`.
The whole reducer tree is validated, including leaves later dropped by
`setOutputs`.

Weights come from the positive cells of a fixed `Kernel`; zero cells are
omitted, while negative weights and empty support reject. The effective weight
is the kernel value for `inputWeight='kernel'`, one for `'mask'`, and
`min(1, kernelValue)` for `'min'`. `sum` retains the coefficient scale. `mean`,
population variance, and population standard deviation use the effective
weights. `count`, `min`, and `max` use positive support and ignore its
magnitude. `sampleVariance`, `sampleStdDev`, `product`, `median`, and `mode`
consume unit support: a uniform positive kernel scale is converted to one for
that operation; a nonuniform effective kernel rejects. `inputWeight='mask'`
and the neighborhood-only `Reducer.unweighted()` wrapper provide unit support
for these operations. In a combined reducer, that unit conversion is per
operation, so a sum or weighted mean sibling keeps the original kernel
magnitudes.

Simple uniform-weight mean/min/max/median/default-mode reductions reuse the
existing `local_ee_focal` graph. Weighted and composed reductions use
`local_ee_neighborhood`, which carries a canonical Float64 coefficient
specification to the native process. `skipMasked` must be boolean and defaults
to true. Optimization strategies, nondefault mode histogram parameters,
non-fixed or meter-based kernels, reducers requiring multiple inputs, and unsupported reducer
leaves reject. `Reducer.unweighted()` is accepted only as a reducer for this
neighborhood operation; it is rejected by generic table, list, array, reducer
composition, and public-value consumers.

The compiler bounds kernels to 33 by 33 cells, offsets within 32 pixels, 1,089
positive coefficients, 10,000 output bands, 10,000 characters per output band
name, 50,000 shared compilation-work steps, and 500 graph nodes. It requires a
finite source and a proven common grid before merging sources. An explicit
`Image.clip()` remains inside the image expression. Neighborhood processing
uses the source grid and finite item bounds; export-region masking and
resampling happen afterward. See [native neighborhood statistics](neighborhood-native.md)
for the local process contract, numeric rules, and execution budget.

The focused compiler tests check real Earth Engine SDK serialization, argument
validation, reducer planning, coefficient specifications, graph ordering, and
unsupported-consumer boundaries. They do not establish native Spark execution,
production raster acceptance, or numerical parity with Google Earth Engine.

The API shape and weighting options follow Google's
[reduceNeighborhood reference](https://developers.google.com/earth-engine/apidocs/ee-image-reduceneighborhood)
and [neighborhood statistics guide](https://developers.google.com/earth-engine/guides/reducers_reduce_neighborhood).
The local binary-mask, empty-support, tie and resource policies remain explicit
subsets of the broader [weighted reduction contract](https://developers.google.com/earth-engine/guides/reducers_weighting).
