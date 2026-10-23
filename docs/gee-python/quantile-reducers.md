# Finite percentile, interval-mean and mode reducers

This local family implements `Reducer.percentile`, `Reducer.intervalMean` and
`Reducer.mode` for finite scalar table rows. The pinned API signatures are in
[`algorithms.json`](../../vendor/earthengine-js/algorithms.json), and Google's
references describe the [percentile](https://developers.google.com/earth-engine/apidocs/ee-reducer-percentile),
[intervalMean](https://developers.google.com/earth-engine/apidocs/ee-reducer-intervalmean)
and [mode](https://developers.google.com/earth-engine/apidocs/ee-reducer-mode)
operations. The references say that percentiles accept values from 0 to 100,
that intervalMean averages inputs in a percentile range, and that mode selects
the most frequent input. For larger server inputs, those implementations use
histograms after `maxRaw`; the references do not specify exact interpolation or
tie-breaking rules for the direct calculation.

This implementation uses an explicit local exact policy. Percentiles sort
non-null values and linearly interpolate at `p * (n - 1) / 100`. Default output
names are `p` followed by the percentile (`p50`, for example); `outputNames`
can provide the same number of custom names. `intervalMean` computes the two
percentile bounds using that interpolation, then averages every observed value
inside the closed numeric interval, including all tied boundary values. It
returns null when there are no observations in the interval. `mode` counts
exact numeric values and returns the numerically smallest value when multiple
values tie. The local output names are `intervalMean` and `mode`. These
interpolation, interval inclusion, output-name and tie policies are documented
local behavior, not claims of Google result parity.

`maxBuckets` and `minBucketWidth` are accepted only when omitted or null.
Non-null values reject because this implementation does not approximate with
histograms. When supplied, `maxRaw` is a hard limit on the number of non-null
input values; exceeding it rejects. It is not used to choose an alternate
algorithm. All three reducers accept at most 1,000 one-scalar rows. Null values
are skipped; booleans, non-finite floats, non-numbers and integers outside the
exact ±2^53 range reject. Values and interpolation use exact rational
representations of integers and finite Float64 values, with only final outputs
rounded to Float64. Extreme and subnormal inputs therefore do not overflow
during interpolation. Each input or percentile rational is limited to 1,100
combined numerator and denominator bits; exact integers and finite Float64
inputs fit within that bound. Interpolation and mean intermediates can be
larger, but their sizes are bounded by those inputs, 256 percentiles and 1,000
rows. The row preflight reserves 18 64-bit limbs per value before conversion.

The family retains the shared 50,000-step work and 1 MB JSON-output limits.
Row scans, sorting, numeric work and output-name/result copies are charged
before their corresponding kernels run. Output-size checks allow up to six
escaped JSON bytes per output-name character. The supported table path does
not add raster or weighted-reduction semantics. Focused tests compare percentile and
interval calculations against independent `Fraction` references and cover
empty/null inputs, ties, maxRaw, unsupported approximation parameters, numeric
boundaries, and the 1,000-row sorting limit. They establish this finite local
subset only. Example46 additionally covers official Python/JS serialization,
grouped-table composition and physical CSV write/read through the synthetic
task harness; Google same-data and deployed-runtime acceptance remain separate.
