# Finite collecting reducers

The local compiler supports `ee.Reducer.toList()` and
`ee.Reducer.toCollection()` when a finite `List.reduce()` or inline
`FeatureCollection.reduceColumns()` evaluates the reducer. The documented
`toList()` guide example uses the output name `list`. This local implementation
uses `collection` as `toCollection()`'s inferred output name; the official
constructor reference does not state that name, so this is not a Google output
parity claim. `reduceColumns()` returns a dictionary keyed by the selected
reducer output name, while a one-output `List.reduce()` returns the value
directly.

Google documents `toList(tupleSize, numOptional)` as collecting reducer inputs
into a list. A null or omitted `tupleSize` means one input and an ungrouped list
of scalar values. An explicit `tupleSize` from 1 through 32 sets the input
arity and produces a list of tuples, including one-element tuples when the
size is 1. The last `numOptional` inputs may be null; a row with a null in any
earlier, required input is dropped. Optional nulls remain in the returned
scalar or tuple. `numOptional` defaults to 0 and must be an integer between 0
and the input arity; an explicit null uses the same default. The
official Python SDK annotates this optional argument as nullable, and its
algorithm signature declares a default of zero.

Google documents `toCollection(propertyNames, numOptional)` as returning a
FeatureCollection whose feature properties use `propertyNames`; the number of
names determines reducer input arity. Locally, one through 32 unique,
non-empty property names are required. `.geo`, `.id`, and `system:index` are
reserved and rejected. Each retained row becomes a feature with null geometry
and an owned `properties` dictionary. The compiler adds no feature IDs. A null
in a required input drops the whole feature; optional trailing null values are
kept as null properties. Empty rows produce an empty FeatureCollection, while
an empty property-name list is rejected because it defines no data fields.
Here too, `numOptional` may be omitted or null to use zero.

Only constructor arguments documented for that reducer are accepted. Unknown
arguments fail instead of being discarded. Every input field is recursively
checked before null filtering, including fields in rows that will be dropped.
Values may be finite JSON
scalars/lists/dictionaries or bounded static `ee.Array` values that the local
public JSON boundary can materialize. Cycles, non-string dictionary keys,
unsupported internal objects, non-finite numbers, excessive nesting, and
oversized containers fail. Typed arrays must use numeric NumPy dtypes no wider
than Float64, and typed integer arrays must remain in the exact ±2^53 range.
Returned nested values and arrays are detached from their inputs; repeated
references are copied independently.

The shared limits are 50,000 translator work units, 1,000 rows, 32 reducer
inputs, 1 MB of selected input and public output JSON, depth 96, and at most
10,000 entries in a nested container. The 50,000 work limit also charges
repeated property names, recursive value scans, and each owned output copy.
These are bounded local static-table semantics; they do not imply support for
raster reducers or arbitrary server-side values.

Official references:

- [Reducer.toList](https://developers.google.com/earth-engine/apidocs/ee-reducer-tolist)
- [Reducer.toCollection](https://developers.google.com/earth-engine/apidocs/ee-reducer-tocollection)
- [Reducer.getOutputs](https://developers.google.com/earth-engine/apidocs/ee-reducer-getoutputs)
- [FeatureCollection.reduceColumns](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-reducecolumns)
- [Reducing a FeatureCollection](https://developers.google.com/earth-engine/guides/feature_collection_reducing)

The reference documents the constructors' arity, null handling, return type,
and `reduceColumns()`'s output-name mapping. Its public pages do not list the
specific `getOutputs()` values for these two constructors; the local names
above follow their collection result types and the established `toList()`
example, and should be compared with a live official SDK result before making
a Google-output-parity claim.
