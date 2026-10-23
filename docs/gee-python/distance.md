# `Image.distance`

`Image.distance(kernel, skipMasked)` measures, per input band, the distance from
each pixel to the nearest nonzero pixel covered by the supplied distance
kernel. Google describes the kernel radius as the maximum distance to consider;
`skipMasked` controls whether a masked input center also masks its output. See
the [Image.distance reference](https://developers.google.com/earth-engine/apidocs/ee-image-distance)
and the [Euclidean](https://developers.google.com/earth-engine/apidocs/ee-kernel-euclidean),
[Manhattan](https://developers.google.com/earth-engine/apidocs/ee-kernel-manhattan),
and [Chebyshev](https://developers.google.com/earth-engine/apidocs/ee-kernel-chebyshev)
kernel references.

This local implementation accepts only the original, unnormalized,
unit-magnitude `Kernel.euclidean`, `Kernel.manhattan`, or `Kernel.chebyshev`
with `units="pixels"`. Radius is a finite binary64 value from 0 through 16.
Meter kernels, transformed or fixed kernels, and other kernel settings fail
explicitly. The constructor's coefficient matrix remains its documented square
shape; the distance search checks only offsets inside the selected metric
radius. Euclidean inclusion compares the exact squared integer offset with the
exact square of the binary64 radius. The Manhattan and Chebyshev checks compare
their integer distances with that same radius. `nextafter(sqrt(2), 0)` excludes
diagonal cells while the representable `sqrt(2)` value includes them.

Every finite nonzero unmasked source value is a target, including negative,
subnormal, and extreme Float64 values. A masked source value is never a target.
`skipMasked=True` leaves a masked output center as NoData. With `False`, the
center can receive a distance from an unmasked target nearby. A nonzero center
is a zero-distance target. When the metric radius contains no target, output is
NaN NoData; no finite sentinel is substituted. Existing spatial and temporal
keys remain the output domain, and temporal halo reads stay within the same
timestamp.

The compiler emits canonical compact JSON with exactly these fields:

```json
{"metric":"euclidean","radius":"4000000000000000","skip_masked":true,"v":1}
```

`radius` stores the original binary64 bits as 16 lowercase hexadecimal digits.
The native parser independently validates the complete versioned value. Its
budget checks cover source keys, decoded cells, the `ceil(radius)` halo,
neighbor-offset setup, per-tile work, and aggregate work before buffering. The
current limits are 100,000 source keys, 10,000,000 decoded cells per tile,
100,000,000 decoded cells across the source, 100,000,000 work units per tile,
and 1,000,000,000 work units total. The exact workload estimate also includes
the radius's precomputed integer-floor setup. This budget covers distance-kernel
setup and tile reads, copies, and output checks. Upstream graph evaluation, IO,
and Spark retries have separate costs, so these limits are not an end-to-end
job-work guarantee.

The output is Float64. Cast it with `toFloat()` before ordinary local pixel
arithmetic or comparisons that require Float32 inputs; the example uses that
explicit cast before a distance threshold. This is a local adapter boundary,
not a claim that arbitrary Float64 pixel callbacks are supported.

The compiler preserves source precision through raster first/last selection,
clipping, and masks before this search. It moves the required Double cast
through those value-preserving operations, so a tiny nonzero source value does
not become a false zero target. An explicit `toFloat()` or ordinary arithmetic
still has its existing rounding behavior. Mixed scalar/raster band reductions
and source-free conditional values retain the existing callback policy; this
change does not add a general typed callback engine.

The focused Python checks use an independent whole-grid `Fraction` oracle and
exercise real Float64 GeoTrellis tiles through a hand-built halo and
`BufferTilesRDD`. That probe is opt-in and starts no SparkContext or service.
It also checks same-timestamp isolation and the exact total-work boundary for
256 by 256 tiles at radius 16, plus rejected layouts, key counts, cell types,
target areas, and non-finite inputs. The official Python and JavaScript SDK
workflow checks use only a synthetic local catalogue and deny network calls. These
checks separate SDK serialization, local compilation, and native tile-kernel
evidence. They do not establish a full Spark/service run, deployment behavior,
or Google same-data numerical parity.

The wave47 native run compared 14 synthetic cases through both tile paths,
with 660 actual output pixels per path and four isolated time keys. Missing
tiles explain the difference from the 672 possible grid slots; they were not
fabricated. All checked values and masks matched; Euclidean values differed
from the independent Decimal square-root reference by zero ULP on these
fixtures (the test allows one ULP). Ten malformed wire cases and ten layout,
budget, or numeric rejection controls also passed.

At radius 16 on 256 by 256 tiles, the conservative one-billion-work-unit
budget admits at most 18 Euclidean, 27 Manhattan, or 13 Chebyshev tile keys.
These are measured admission boundaries, not throughput estimates or a claim
that arbitrary scene sizes are supported. See the [wave47 report](../../reports/gee-python-wave47.json)
for the exact validation scope and retained local evidence paths.
