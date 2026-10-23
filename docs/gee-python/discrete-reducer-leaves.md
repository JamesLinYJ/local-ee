# Finite discrete reducer leaves

This local slice evaluates 13 finite discrete `ee.Reducer` leaves in the existing
bounded `List.reduce` and literal `FeatureCollection.reduceColumns` path. The
official SDK's constructor and serialization behavior is covered separately;
this module's calculations use finite local inputs and do not claim Google
backend parity.

Output names follow the pinned algorithm descriptions and official references:
`countEvery`, `countDistinct`, `countDistinctNonNull`, and `countRuns` emit
`count`; `firstNonNull` emits `first`; `lastNonNull` emits `last`;
`frequencyHistogram` emits `histogram`; `allNonZero` and `and` emit `all`;
`anyNonZero` and `or` emit `any`; and the bitwise leaves emit `bitwiseAnd` or
`bitwiseOr`. The relevant references are [countEvery](https://developers.google.com/earth-engine/apidocs/ee-reducer-countevery),
[countDistinct](https://developers.google.com/earth-engine/apidocs/ee-reducer-countdistinct),
[countDistinctNonNull](https://developers.google.com/earth-engine/apidocs/ee-reducer-countdistinctnonnull),
[countRuns](https://developers.google.com/earth-engine/apidocs/ee-reducer-countruns),
[firstNonNull](https://developers.google.com/earth-engine/apidocs/ee-reducer-firstnonnull),
[lastNonNull](https://developers.google.com/earth-engine/apidocs/ee-reducer-lastnonnull),
[frequencyHistogram](https://developers.google.com/earth-engine/apidocs/ee-reducer-frequencyhistogram),
[allNonZero](https://developers.google.com/earth-engine/apidocs/ee-reducer-allnonzero),
[anyNonZero](https://developers.google.com/earth-engine/apidocs/ee-reducer-anynonzero),
[bitwiseAnd](https://developers.google.com/earth-engine/apidocs/ee-reducer-bitwiseand),
and [bitwiseOr](https://developers.google.com/earth-engine/apidocs/ee-reducer-bitwiseor).

## Local input and null rules

Every input list is capped at 1,000 values and fully preflighted before any
reducer can stop early or ignore a row. The scan rejects dynamic IR, cycles,
unsupported Python objects, non-finite floats and integers outside the exact
`[-2^53, 2^53]` domain, including values nested in dictionaries, lists and
static Arrays. Nested finite JSON and static Arrays are useful as
`countEvery` inputs and as `firstNonNull` / `lastNonNull` outputs. The
distinct, run, histogram, logical and bitwise reducers use scalar values only.
Their accepted scalar categories are numbers, strings, booleans and null;
operation-specific rules below narrow that set further.

- `countEvery` counts each list position, including null. The pinned API says it
  counts inputs; the official [Image.reduceToVectors](https://developers.google.com/earth-engine/apidocs/ee-image-reducetovectors) reference also specifies
  that its default `countEvery` reducer consumes bands after dropping the label
  band. We infer zero-input arity from that labels-only case; no Google arity probe
  has run. A labels-only input has zero selected reducer columns but
  still produces one count per source row. The table evaluator represents each
  such row as a null placeholder when calling this leaf; a direct List reduction
  instead counts its actual list positions.
- `countDistinct` treats null as one distinct value; `countDistinctNonNull`
  omits null. Numeric `1` and `1.0` are the same value, while boolean `true`
  remains distinct from numeric `1`.
- `countRuns` omits null values and counts transitions between adjacent
  remaining scalar identities. A null gap does not reset the previous value.
- `firstNonNull` and `lastNonNull` select the first or last non-null value and
  return an owned copy. No non-null value returns null.
- `frequencyHistogram` omits null and accepts scalar values. Keys use bounded
  string conversion: booleans become `true` / `false`, and equal numeric
  values share a key. If distinct input types convert to the same string key,
  evaluation fails instead of overwriting an earlier count.
- `allNonZero` / `and` and `anyNonZero` / `or` accept finite numbers, omit
  nulls, and reject booleans. Their outputs are integer `1` or `0`. Empty or
  all-null input returns the bounded logical identity: `1` for all/and and `0`
  for any/or.
- `bitwiseAnd` and `bitwiseOr` accept finite integer-valued numbers, including
  negative values, within the exact `±2^53` domain. Booleans and fractional
  values fail. Results outside that exact integer domain fail. Empty or
  all-null input returns `-1` for AND and `0` for OR.

The API reference describes reducer intent and names but does not specify every
null, empty-input, scalar-type, or `countRuns` gap behavior used above. Those
cases are explicit local policies, not claims about Google results. Signed
bitwise behavior follows the documented Array examples, while the reducer
reference itself does not state a signed boundary.

## Resource limits and validation

Input scans, scalar hashing, selected-value copies, and public output all use
the existing shared 50,000-step compiler budget and 1 MB JSON limit. Histogram
string-key collisions fail closed. First/last outputs are detached from their
source containers; cycles and unsupported values fail even when they occur
after the selected value or would otherwise be skipped by a reducer.

Focused tests cover every leaf's expected output, empty and null cases,
numeric/bool identity, ownership, collision failure, unsupported types,
exact integer boundaries, cycles, and work limits. They validate this finite
compiler slice only; SDK workflow integration, actual execution, and Google
comparison remain separate evidence.

Histogram output sizing now counts each unique key once and incrementally
reserves count-digit growth; repeated key lookups, comparisons and updates still
consume work. The official SDK path with 1,000 repeated integer values passes
at 33,153 steps for reduceColumns and 29,037 for aggregate_histogram. A full
1,000-distinct-integer FeatureCollection exceeds the unchanged 50,000-step
budget, although its direct kernel fits. The 1,000-row cap is an upper bound,
not a guarantee that every nested or high-cardinality table fits.
