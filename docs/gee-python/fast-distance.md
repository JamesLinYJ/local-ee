# `Image.fastDistanceTransform`

The pinned Earth Engine API describes this method as the distance to the
nearest nonzero input pixel. Its optional arguments are `neighborhood` (256 by
default), `units` (`"pixels"`) and `metric` (`"squared_euclidean"` by default,
or `"manhattan"` / `"chebyshev"`). The default metric returns squared
Euclidean distance. Google recommends it for neighborhood operations such as
erosion and dilation. See the [API reference](https://developers.google.com/earth-engine/apidocs/ee-image-fastdistancetransform)
and [coding best practices](https://developers.google.com/earth-engine/guides/best_practices#use_fastdistancetransform_for_neighborhood_operations).

```python
water = image.select("SCL").eq(6)
distance_squared = water.fastDistanceTransform()
within_three_pixels = distance_squared.sqrt().lt(3)
manhattan = water.fastDistanceTransform(
    neighborhood=64, units="pixels", metric="manhattan",
)
```

The local compiler accepts omitted or raw-null arguments as those defaults.
Its bounded local policy requires an integral numeric neighborhood from 1 to
4096 and pixel units. Boolean, fractional, zero, and out-of-range values,
unknown arguments, other units, and unknown metrics fail explicitly. The
workflow in [`53_GEE_python_fast_distance.py`](../../examples/53_GEE_python_fast_distance.py)
shows the default call, all three metrics, water-mask dilation and erosion,
masking a Double source, multiband input, mapped observations, and an export
ROI.

Local execution treats each finite, unmasked, nonzero input cell as a target.
Masked source cells do not become targets. Every observed center receives an
integer distance, including masked centers and searches with no target; values
are capped at `N²` for squared Euclidean distance or `N` for Manhattan and
Chebyshev distance. Each band is searched independently. Existing source and
time keys are preserved, and a missing tile is not created. The native result
is Int32 and remains exactly representable through `2²⁴`, so expressions such
as `image.fastDistanceTransform().sqrt().lt(3)` can continue through the usual
Float32 pixel callbacks. An existing Double source is kept Double through
masking before the search.

The search uses the full finite source extent; an output clip, export region,
or resampling request is applied after the transform. The neighborhood bound
does not promise that every size fits every input: the existing source,
buffer, scratch, graph, and work budgets still apply. Small tiles can use
multi-hop searches, including the default size when its budgets fit.

These are explicit local rules, not a claim of numerical parity with Google's
engine. No same-data Google comparison establishes neighborhood cutoff
boundaries, masked-target handling, multiband behavior, or output dtype. The
offline Python/JavaScript workflow test verifies SDK serialization, local graph
compilation, and Map/Export request capture; it does not run Spark, deploy the
service, or perform a physical export.

The wave48 trusted native run checked 13 pure-transform cases and 16 actual
GeoTrellis source-tile cases. The latter covered 85 observed keys and 1,772,714
output pixels; complete per-tile hashes, ranges and saturation counts matched
an independent Python nearest-target oracle. All three metrics ran with
N=256 over 3×3 actual 256×256 tiles, and crossed two tile hops on the smaller
temporal fixtures. Missing tiles account for 384 unused grid slots. A 65,537-cell
line also retained the exact squared distance 4,294,967,296 before public
saturation, which checks the internal Long arithmetic independently of Int32
output.

For N=256 and 256×256 tiles, the conservative work plan admits 24 observed
keys and rejects 25. Its 3×3 fixture uses 18,305,280 logical allocation cells
and 362,741,850 work units. These are admission estimates, not measured peak
memory or scene throughput. The native probe exercised wire, tile, fragment,
duplicate-center, and budget rejection controls; the distributed RDD path was
compiled but was not executed with a SparkContext.

The native adapter assumes stable unique source keys between its bounded
census and later RDD evaluation, as provided by an immutable input snapshot.
Its own work limits exclude upstream graph evaluation, IO and Spark retries.
Changing or nondeterministic RDDs require further validation before claiming
the same aggregate resource bound. See the [wave48 report](../../reports/gee-python-wave48.json)
for the retained evidence and unverified scope.
