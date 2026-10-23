# Finite nested FeatureCollections

This module implements bounded nested `FeatureCollection` construction and
`Collection.flatten` for local finite values. The pinned Python SDK 1.7.49
serializes `flatten()` as `Collection.flatten`; its generated client call shape
does not establish computation semantics. Google documents flattening a
collection of collections, including the `ImageCollection.map()` to
`FeatureCollection.flatten()` pattern. The Python method at the pinned source
revision is a direct generated algorithm call, and the public constructor
accepts computed collections and lists of Features. See the [Google flatten
reference](https://developers.google.com/earth-engine/apidocs/ee-featurecollection-flatten),
[Google FeatureCollection constructor reference](https://developers.google.com/earth-engine/apidocs/ee-featurecollection),
and the pinned [`ee.Collection.flatten` implementation](https://github.com/google/earthengine-api/blob/e189e4b89e785019ea5642ea8e80cb644749cd4a/python/ee/collection.py#L547-L550).

The local compiler represents a nested table with an internal typed IR, not a
plain dictionary that existing flat-table handlers might mistake for rows.
`ee.FeatureCollection([child_a, child_b])` accepts only finite
FeatureCollections as immediate children. `map()` can return a child
FeatureCollection; homogeneous child-collection results remain typed until
`flatten()` converts them to an ordinary FeatureCollection. Flat map results,
sampled tables, and `Region` reduction wrappers retain their existing paths.
Mixed rows, child collections, Images, sampled values, opaque objects, and
dynamic values are rejected explicitly. A Feature row may contain finite JSON
values and bounded finite `ee.Array` values, but not internal Images or other
opaque values.

Flatten walks children depth first and preserves row order, geometry,
properties, and explicit Feature IDs. It never fabricates IDs. The output rows,
their nested property values, and collection metadata are independently owned.
As a local metadata policy, the outer collection's properties are retained;
child collection properties are validated but discarded. Google documents the
flatten operation but does not define collection-property inheritance in the
referenced API contract, so this policy is not a Google parity claim. An empty
ordinary FeatureCollection is accepted by `flatten()` as the empty result so
that `empty.map(...).flatten()` remains composable; its collection metadata is
preserved. A nonempty ordinary flat collection is not treated as a nested one.

Bounds apply before traversal, cloning, or output materialization: each
collection has at most 1000 immediate elements; total nested nodes are at most
10000; depth is at most 96; and the flattened result has at most 1000 rows.
Finite property containers have at most 10000 entries. Work uses the shared
50000-step compiler budget, and the public JSON representation is limited to
1 MB. None of these limits raises or bypasses another compiler budget.

The focused tests exercise SDK serialization plus local compilation (S and C),
including nested construction, mapped child tables, flatten order and row
values, downstream filter/aggregate operations, empty children and empty map
results, ownership, and explicit rejection boundaries. They do not invoke the
Earth Engine service or establish engine/runtime (E) or Google numerical (G)
parity.

See [`tests/test_ee_nested_collections.py`](../../tests/test_ee_nested_collections.py)
for the finite local checks.
