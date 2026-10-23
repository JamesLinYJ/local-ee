# Fixed-shape raster-array reductions

`Image.arrayReduce` reduces selected axes of a fixed-shape raster array and
keeps the result as an array-valued image. This implementation accepts numeric
single-input reducer leaves, shared-input `combine` trees, and `setOutputs`
selection. The result is compiled into local per-pixel reductions; it does not
materialize the raster array as public image bands.

The supported numeric leaves include the existing scalar reducers (`sum`,
`mean`, `min`, `max`, `count`, `first`, `last`, `median`, and sample standard
deviation) plus `product`, population `stdDev`, population `variance`,
`sampleVariance`, and `minMax`. `minMax` emits separate minimum and maximum
fields. `combine` must use `sharedInputs=true`; multi-input, non-numeric,
grouped, repeated, and per-input expansion reducers are rejected. `setOutputs`
can rename or remove output fields, and the remaining outputs retain their
declared order.

All reduced axes become singleton dimensions. With one output, `fieldAxis`
may be omitted. A multi-output reducer requires `fieldAxis`; the input
`fieldAxis` must be a singleton dimension that is not also reduced, and the
output dimension grows to the number of selected reducer fields. The output
array is stored in row-major order. The array's whole-array mask is retained on
the result, including when an individual reducer could otherwise return a
value from a partially masked group.

Raster arrays are limited to rank 8, axis lengths of 64, and 64 total cells.
The existing shared 50,000-step compilation budget and 500-node graph limit
also apply. New finite numeric descriptors use native Float64 scalar
reductions. Legacy `ee.Reducer` callback reductions retain their existing
precision and behavior. Raster-array operands from distinct source items may
be reduced together only when their explicit STAC projection metadata proves
that their pixel grids align; this check does not resample inputs.

The population/sample denominator choices and unsupported cases above are
local compatibility policies based on the declared reducer names. This page
records compiler and independent synthetic numerical coverage; it does not
claim a Google Earth Engine same-data comparison or complete API parity.
