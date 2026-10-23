# Static Array reductions

`ee.Array.reduce(reducer, axes, fieldAxis)` now evaluates a finite numeric
subset over owned static arrays. The result keeps the input rank: each axis in
`axes` has length one, retained axes keep their lengths, and a supplied
`fieldAxis` has the reducer's output count. Reductions are independent for each
combination of retained indices.

The [official Array.reduce reference](https://developers.google.com/earth-engine/apidocs/ee-array-reduce)
specifies that `fieldAxis` supplies reducer inputs and receives reducer outputs.
It is required when the reducer has multiple inputs or outputs, and its input
length must match the reducer input count. This local numeric subset currently
uses single-input leaves. Multi-output reductions therefore require an
input-length-one field axis; the axis cannot also appear in `axes`, because
those roles would require conflicting result lengths. Supplying `fieldAxis`
for a single-output reducer is supported when its input length is one.

Supported leaves are the existing `sum`, `mean`, `min`, `max`, `count`,
`first`, `last`, `median`, and sample standard deviation (`sd`), plus
`product`, population `stdDev`, population `variance`, sample `sampleVariance`,
and `minMax`. `minMax` produces two fields named `min` and `max`. Shared-input
`Reducer.combine` and `Reducer.setOutputs` are accepted through the closed
numeric reducer plan; independent-input combinations and other composed
reducers remain unsupported here.

Float sums and means use bounded finite arithmetic that preserves representable
cancellation and large-offset differences. Standard deviation is computed
without forming a variance first, so a finite standard deviation can succeed
when its variance is outside Float64 range. Variance outputs that are not
finite are rejected. Product accumulates significands and binary exponents to
avoid order-dependent early overflow or underflow; a final non-finite result
is rejected. Integer sum and product use exact intermediates and reject results
outside the exact Float64 integer domain (±2^53). The existing integer min/max
and sum behavior is preserved.

Static arrays remain limited to rank 8, 10,000 cells, and the shared 50,000
work budget. Input scans, grouping/transposition, each requested output kernel,
and owned result construction are precharged before array buffers are made.
Empty inputs, invalid or repeated axes, field-axis overlap or wrong length,
unused arguments, unsupported reducer descriptors, non-finite values, and
sample statistics with fewer than two values fail explicitly. Static arrays
cannot represent null output fields, so undefined sample results are rejected
rather than fabricated.

These are local finite-computation semantics. Static and SDK serialization
checks do not establish Google numerical parity or multi-input reducer support.
