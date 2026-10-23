# Static list and dictionary selection

The pinned Earth Engine Python API serializes `List.filter(filter)` with the
required `list` and `filter` arguments. For ordinary list items the filter
property is named `item`; a Feature list uses its feature properties. The
adapter evaluates the serialized `Filter` IR against a finite static List and
returns an owned List copy. It reuses the existing inline Feature filter rules
for predicates such as equality, ordered scalar comparisons, `inList`,
`listContains`, `notNull`, and boolean combinations. Direct equality on an
ordinary `item` also uses the bounded static equality contract, including
nested Lists, Dictionaries, and same-shape/same-dtype `ee.Array` values.

`Dictionary.select(selectors, ignoreMissing=false)` and
`Dictionary.remove(selectors, ignoreMissing=false)` accept a finite list of
string selectors. Each selector is a bounded RE2 regular expression matched
against the whole key. A selector matching no key raises by default; with
`ignoreMissing=true`, it is skipped. Selectors are applied as a set: duplicates do not duplicate output
entries, and results follow source dictionary insertion order. Null values are
ordinary values and are retained whenever their key is retained. Both methods
return recursively owned copies.

A literal-looking key does not override regular-expression semantics: `B[12]`
selects B1/B2; escape brackets to select a key named B[12]. All patterns are
compiled even on empty dictionaries or with `ignoreMissing=true`. Unsupported
RE2 syntax fails explicitly. Patterns, program memory and matching work share
the [bounded String regex contract](string-regex.md).

Inputs and output scans use the existing finite static value and compiler-work
limits: up to 10,000 container values, depth 96, 1 MB serialized static output,
and a shared 50,000-step work budget. Dynamic lists, dynamic filter values,
unsupported Filter operations, malformed keys, oversized inputs, and exhausted
budgets fail explicitly. These are local static computations, not claims of
Google server execution or parity for the documented local insertion-order,
structural-equality, or regex boundaries.

## Pinned references

- [Earth Engine `ee.List.filter`](https://developers.google.com/earth-engine/apidocs/ee-list-filter)
- [Earth Engine `ee.Dictionary.remove`](https://developers.google.com/earth-engine/apidocs/ee-dictionary-remove)
- [Earth Engine API reference, including `ee.Dictionary.select`](https://developers.google.com/earth-engine/api_docs)
- Pinned client/API metadata: `vendor/earthengine-js/algorithms.json`, SDK version 1.7.49.

Focused contract tests live in `tests/test_ee_static_container_selection.py`.
They cover pinned signatures, offline official-client serialization, local
finite results, ordering, nulls, owned copies, regex selection/rejection, and bounded
failure paths. They do not use credentials or user data and do not call Google.
