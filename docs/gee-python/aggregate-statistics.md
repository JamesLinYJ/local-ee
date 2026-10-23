# Bounded `AggregateFeatureCollection` statistics

The pinned Earth Engine Python SDK 1.7.49 serializes `aggregate_first`,
`aggregate_count`, `aggregate_count_distinct`, `aggregate_min`,
`aggregate_max`, `aggregate_mean`, `aggregate_product`, `aggregate_sum`,
`aggregate_sample_sd`, `aggregate_sample_var`, `aggregate_total_sd`,
`aggregate_total_var`, `aggregate_stats`, and `aggregate_histogram` as
`AggregateFeatureCollection.*` calls with exactly `collection` and `property`
arguments. The existing `aggregate_array` implementation remains separate.
Official reference pages describe the method signatures and broad operations;
the `aggregate_stats` example also shows the complete 13-field result. See the
[FeatureCollection aggregate reference](https://developers.google.com/earth-engine/api_docs#ee.FeatureCollection.aggregate_stats),
the [aggregate count reference](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-aggregate_count),
and the [aggregate histogram reference](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-aggregate_histogram).

The local implementation accepts finite inline `FeatureCollection` values
with at most 1000 features. It also reads actual declared properties from a
finite local `ImageCollection` (`Collection` IR) or a finite `ImageSequence`,
up to 1000 selected images. That image support reads existing image metadata
only; it does not inspect pixels or invent properties. Sampled, remote,
opaque, cyclic, and other dynamic collections fail explicitly.

Missing and explicit `null` properties are both treated as null by these
aggregates. `aggregate_first` preserves input order and returns the first
feature's scalar property, including null when that first value is missing or
null; it does not skip ahead. `aggregate_count` counts non-null scalar or
nested JSON values, including booleans, strings, arrays, and objects. The
selected value must be finite bounded JSON: compiler IR such as Images and
Arrays, cycles, non-string keys in selected nested objects, non-finite numbers,
and integers outside the exact `[-2^53, 2^53]` domain fail even for count.
Containers are limited to 10000 entries and depth 96; selected property strings
and nested object-key bytes are charged to the work budget. `count_distinct` and
`histogram` accept only scalar strings, booleans, and numbers. Distinct numeric
integers and floats compare as one numeric type (`1` and `1.0` are equal),
while booleans remain distinct from numbers. Nested values can be counted but
cannot be returned by `aggregate_first` or consumed by the other scalar
statistics.

`aggregate_min` and `aggregate_max` accept either homogeneous numeric values
or homogeneous strings after nulls are omitted. Strings use Python Unicode
code-point order as the local ordering rule. Booleans and mixed numeric/string
values fail. Mean, sum, product, variance, standard deviation, and
`aggregate_stats` require finite numeric values and reject strings, booleans,
and mixed types. Integer property inputs must be in the exact binary64 integer
domain `[-2^53, 2^53]`.

The local empty-input contract is: count and distinct count return `0`,
histogram returns `{}`, sum returns `0.0`, product returns `1.0`, and first,
min, max, mean, standard deviations, and variances return `null`. Sample
standard deviation and variance are also `null` for a singleton. Population
(`total_*`) variance and deviation are zero for a singleton.
`aggregate_stats` returns `max`, `mean`, `min`, `sample_sd`, `sample_var`,
`sum`, `sum_sq`, `total_count`, `total_sd`, `total_var`, `valid_count`,
`weight_sum`, and `weighted_sum`. Here `total_count` is the collection row
count, `valid_count` is the non-null numeric count, and the unweighted
`weight_sum` and `weighted_sum` are respectively `valid_count` and `sum`.
Undefined statistics are null; empty sum and sum of squares are zero.

Histogram dictionary keys are strings: text values keep their text, booleans
become `true`/`false`, integers use decimal notation, and finite floats use a
canonical local binary64 spelling. If two distinct typed values map to the
same string key (for example numeric `1` and text `"1"`), the operation fails
instead of merging or overwriting bins. This is an explicit local collision
policy, not a statement about Google's server implementation.

Means use a shifted calculation with scaled fallback when subtracting finite
extremes would overflow. Variance and standard-deviation requests use scaled
centered deviations, so they do not first form raw squares; each request
computes only its requested reducer. The full `aggregate_stats` result also
computes `sum_sq`, which fails when that requested field exceeds the finite
numeric range even if mean or variance alone would be finite. Numeric outputs
must remain finite. All scans, string comparisons, key generation, numeric
work, and output accounting are charged before the work to the existing shared
50000-step budget. Inline collections remain limited to 1000 rows and public
JSON output to 1 MB. These are bounded local policies; the finite tests provide
independent expected values and SDK serialization/compilation evidence, not a
Google numerical oracle or image-engine acceptance.

The public API reference documents aggregate descriptions and return types,
but does not settle all edge behavior covered by this subset, including empty
aggregates, mixed types, null/missing distinctions, histogram key collisions,
and floating-point last-bit behavior. Those cases follow the local contract
above until a same-input Google comparison is performed.
