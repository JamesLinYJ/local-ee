# Bounded repeated reducer copies

This page extends the closed reducer trees described in
[composed reducers](composed-reducers.md). It covers `Reducer.repeat(count)`
and `Reducer.forEach(outputNames)` when consumed by static `List.reduce` or
inline `FeatureCollection.reduceColumns`. The pinned official Python client
serialization and local computation are checked independently. No Google
backend comparison is claimed.

## `repeat(count)`

`repeat` creates independent copies of a reducer over consecutive input
blocks. Each block has the child's full input arity. The output names stay the
same, and each output value is a list containing that output from each copy.
For example, `ee.Reducer.mean().repeat(2)` consumes two columns and a
`reduceColumns` result has the form `{"mean": [mean_of_column_1,
mean_of_column_2]}`. `List.reduce` returns that list directly when the child has
one output; multiple child outputs remain a dictionary whose values are lists.

## `forEach(outputNames)`

`forEach` creates one reducer copy for each name, with each copy consuming its
own consecutive input block. For a single-output child, the supplied names
are the output names. For a multi-output child, local output names use the
supplied name, an underscore, and the child's output name (for example,
`first_scale`). The official API catalog says these names are prefixed but
does not specify the separator; underscore follows Earth Engine's documented
band/statistic naming convention and is an explicit local policy.

Outputs are ordered by `outputNames`, then by the child's output order. The
number of outputs is the product of those two lengths. Duplicate names remain
in the reducer descriptor so an enclosing `setOutputs` can rename them; they
fail if a result must become a dictionary. Group-name collisions also fail,
including for empty input tables. A child whose outputs were all removed by
`setOutputs` still expands with its real input arity and produces an empty
dictionary result; the child is not assigned a phantom input or output.

## Limits and local policies

- `repeat` counts and `forEach` name lists must each request at least one copy;
  `repeat(0)` and `forEach([])` reject. A genuine zero-input child such as
  `countEvery` retains zero inputs after expansion and still counts each source
  row for every copy. Copy counts are bounded at 32 independently of arity.
- Reducer trees retain the depth-16 limit. The 64-node limit counts logical
  expanded copies, even though immutable descriptors store a child once.
  Inputs, outputs, and rows remain bounded at 32, 256, and 1,000.
- Validation, expanded row slices, repeated output names, and evaluation work
  are charged before the corresponding allocations or child evaluation. The
  existing shared 50,000-step compiler work limit and 1 MB JSON boundary still
  apply.
- `combine`, `group`, and `setOutputs` can wrap or be wrapped by either
  expansion. Grouping keeps first-seen key order and applies the child reducer
  to the remaining input columns.
- Weighted, dynamic, raster, and runtime-table reducer consumers remain
  unsupported. These descriptors are not raster reducer kernels.

Focused evidence is in `tests/test_ee_reducer_expansion.py`: official-client
serialization is compiled through the local expression path for both list
and inline-table reductions, including independent expected values,
multi-output naming, nesting, collision rejection, ownership, and expansion
budget failures.
