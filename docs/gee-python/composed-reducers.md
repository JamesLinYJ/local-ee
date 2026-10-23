# Bounded composed and grouped reducers

This local slice evaluates a closed set of `ee.Reducer` compositions in
`List.reduce` and literal `FeatureCollection.reduceColumns`. The Python SDK
syntax is covered by the repository's pinned `earthengine-api` 1.7.49 lock;
that proves SDK serialization only. Local static evaluation and independent
synthetic values are tested separately, and no Google backend comparison is
claimed.

## Supported composition

`combine()` runs its two child reducers in order. With `sharedInputs=True`, both
children consume the same selected input columns and must have equal input
arity. With `sharedInputs=False`, the first child's input columns precede the
second child's columns. Outputs from the second child receive `outputPrefix`.
`setOutputs()` requires one entry per child output; `null` and empty names are
dropped, matching the documented API behavior. `getOutputs()` returns a fresh
static list. Duplicate names can be renamed by a later `setOutputs`; unresolved
duplicates reject where the result must become a dictionary.

Supported leaves are unweighted scalar `sum`, `mean`, `min`, `max`, `count`,
`first`, `last`, `median`, and sample standard deviation, plus the existing
`linearFit` and `linearRegression` leaves. Additional [numeric](numeric-reducer-leaves.md)
and [discrete](discrete-reducer-leaves.md) leaves now cover variance, extrema,
product, distinct/run counts, histograms and logical/bitwise statistics.
[repeat and forEach](reducer-expansion.md) apply independent input blocks.
`countEvery` consumes zero selected columns and counts source rows, including
empty records; it combines with a one-input reducer using separate inputs.
`group()` uses the selected-input
index in `groupField`, removes that field before applying its child reducer,
and returns a `groups` list of dictionaries. `groupName` names the key in each
group record. Nested grouping follows the same rule at each level.

`List.reduce` returns its sole output directly and returns a dictionary for
multiple outputs. `FeatureCollection.reduceColumns` always returns a dictionary
keyed by output names. These shapes match the documented return contracts for
[List.reduce](https://developers.google.com/earth-engine/apidocs/ee-list-reduce)
and [FeatureCollection.reduceColumns](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-reducecolumns).
The composition signatures and naming rules follow the official
[Reducer.combine](https://developers.google.com/earth-engine/apidocs/ee-reducer-combine),
[Reducer.group](https://developers.google.com/earth-engine/apidocs/ee-reducer-group),
[Reducer.setOutputs](https://developers.google.com/earth-engine/apidocs/ee-reducer-setoutputs),
and [Reducer.getOutputs](https://developers.google.com/earth-engine/apidocs/ee-reducer-getoutputs)
references.

The extra [numeric](numeric-reducer-leaves.md), [discrete](discrete-reducer-leaves.md)
and [expansion](reducer-expansion.md) pages specify additional leaf policies.
The examples and tests exercise actual local calculations, without a Google oracle.

## Bounded local behavior

- The only table source is a literal inline `FeatureCollection` with at most
  1,000 features. `List.reduce` accepts at most 1,000 list rows.
- The descriptor is closed and immutable after construction. It allows at most
  64 node occurrences, depth 16, 0–32 input columns, 256 output names, and
  10,000 characters per reducer or selector name. It rejects cycles, malformed
  mutated descriptors, and unsupported consumers.
- The whole operation uses the existing 50,000-step compiler work budget.
  Selected table properties must be finite JSON and are bounded by depth 96 and
  1 MB encoded size. List `first`/`last` return detached copies of bounded
  finite JSON values or static arrays; cycles and unsupported typed values
  reject. Public results retain the compiler's 1 MB output limit.
- Selectors must match the reducer's full input arity and are flat property
  names. Missing properties become null. Non-empty `weightSelectors` are
  explicitly unsupported; null or an empty list is accepted. The implementation
  never discards weights or changes a weighted request into an unweighted one.
- Scalar numeric reducers skip null values. `count` counts any non-null value;
  numeric statistics reject booleans, text, non-finite values, and integers
  outside the exact Float64 input range. In this local subset, empty sum/count
  return zero, other empty scalar outputs return null, and one-value sample
  standard deviation returns null. Existing regression kernels skip null or
  incomplete rows and preserve their null-result policy for insufficient or
  rank-deficient systems.
- Group keys are finite exact numbers, strings, or booleans. Null group keys
  are skipped, `1` and `1.0` share a numeric group, and booleans remain distinct
  from numbers. Group records retain first-seen order. These are explicit local
  static policies, not claims about every server-side input type or Google
  ordering.

Grouped reductions use the documented selector-index convention and return a
`groups` list; see Google's [grouped reductions guide](https://developers.google.com/earth-engine/guides/reducers_grouping).
Weighted calculations, arbitrary reducers, non-inline or dynamic
collections, nested selectors, and raster reducer consumers remain outside this
slice. Reducer specifications are separate from raster reducer kernels so a
table descriptor cannot be interpreted as an image algorithm.

The later [numeric raster adapter](raster-statistics.md) also accepts shared-input numeric combine/setOutputs, including array field axes. Group, repeat, forEach, independent inputs and nonnumeric leaves remain excluded from that adapter.
