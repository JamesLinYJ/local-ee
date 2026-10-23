# Finite FeatureCollection selection

This module implements three bounded operations for finite inline
`FeatureCollection` values: `distinct`, `remap`, and `fromColumns`. The pinned
Earth Engine Python SDK 1.7.49 serializes them as `Collection.distinct`,
`Collection.remap`, and `Collection.fromColumns`. SDK serialization establishes
the call shape only; it does not establish Google server behavior or local
backend execution. The pinned JavaScript SDK has no `FeatureCollection.fromColumns`
static helper; use `ee.FeatureCollection(ee.call("Collection.fromColumns", columns, names))`
to serialize the same official algorithm.

`FeatureCollection.distinct(properties)` follows Google's documented rule that
duplicates are selected using a strong hash of the serialized selected
properties. The local finite implementation hashes canonical compact UTF-8
JSON with SHA-256 and verifies equal serialized bytes inside a digest bucket.
Dictionary keys are sorted for the local canonical form. This is a documented
local inference; it is not Google's hash implementation or a Google parity
claim. The local result keeps the first matching row in input order, which is a
deterministic finite policy. Under this local JSON policy, integer `1` and
floating-point `1.0` serialize differently and remain distinct. The `.geo`
selector hashes the decoded GeoJSON representation exactly; it does not
normalize topologically equivalent geometries, and a null geometry is
rejected. Missing or null selected properties, typed arrays, internal Image
values, and other non-JSON values fail explicitly because their serialized
equality is not established here. An empty selector hashes the same empty
object for every row and therefore keeps the first row.

`FeatureCollection.remap(lookupIn, lookupOut, columnName)` accepts at most 1000
unique input keys and output values. Input keys are strings or exact integers
within the local Float64-safe integer domain; output values are integers in
that domain. The lists must have equal length. Rows with absent, null, or
unmatched column values are dropped, as the public method documents for
unmatched values. Other column value types, duplicate input keys, and unknown
arguments fail. Matching rows retain their order, ID, geometry, other fields,
and collection metadata; only the selected property is replaced.

`Collection.fromColumns(columns, propertyNames, propertyTypes)` uses one list
per property: `columns[j][i]` becomes the value of `propertyNames[j]` in output
row `i`. The lists of columns and property names must have equal lengths, all
columns must have the same row count, and duplicate property names fail. The
implementation creates one Feature per row with null geometry, preserves
explicit null cells, and does not pad short columns, discard fields, or assign
synthetic IDs. Output size and repeated property-name work are preflighted
before row dictionaries and cell copies are materialized. Up to 1000 rows and
10000 properties are accepted.

The pinned hidden algorithm signature says `propertyTypes` is an optional list
of objects with one entry per property, but does not define the accepted values.
The pinned Python SDK exposes the generated call and serializes the argument;
it does not provide a type vocabulary or local coercion rules. Therefore this
implementation accepts an omitted or null `propertyTypes` and rejects a
non-null value rather than guessing its cast semantics.

All three operations use the existing 50000-step compiler work budget and
1 MB public JSON output limit. Inputs must be finite inline tables with at
most 1000 rows. Sampled tables, RF-classified tables, ImageCollections,
unknown parameters, dynamic values, and incompatible column shapes fail
explicitly. Row copies and collection metadata are independently owned.

`Collection.flatten` remains unsupported. The current `Collection` constructor
rejects nested FeatureCollections before flatten can receive a finite nested
representation; supporting it requires a separate constructor representation
change.

## References

- [Google Earth Engine `FeatureCollection.distinct`](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-distinct)
- [Google Earth Engine `FeatureCollection.remap`](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-remap)
- The hidden `Collection.fromColumns` signature and its argument descriptions
  are in the [pinned official algorithm catalog](https://github.com/google/earthengine-api/blob/e189e4b89e785019ea5642ea8e80cb644749cd4a/python/ee/tests/algorithms.json); the SDK source revision is recorded in
  [the SDK source lock](../../vendor/earthengine-python/upstream-lock.json).

Focused SDK serialization and local finite-operation checks are in
[`tests/test_ee_feature_table_selection.py](../../tests/test_ee_feature_table_selection.py).
