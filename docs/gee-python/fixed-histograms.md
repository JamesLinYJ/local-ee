# Finite fixed-bin histogram reducers

The finite reducer kernel supports `ee.Reducer.fixedHistogram` and
`ee.Reducer.fixed2DHistogram` for static List and inline table reduction. It
computes local finite rows only. This does not add raster reduction support or
claim comparison against Earth Engine results.

The pinned [`algorithms.json`](../../vendor/earthengine-js/algorithms.json)
defines the constructors: `fixedHistogram(min, max, steps, cumulative=false)`
and `fixed2DHistogram(xMin, xMax, xSteps, yMin, yMax, ySteps)`. The official
[1D reference](https://developers.google.com/earth-engine/apidocs/ee-reducer-fixedhistogram)
specifies an N×2 array of bucket lower edges and counts, or cumulative counts,
with values in `[min, max)`; the
[2D reference](https://developers.google.com/earth-engine/apidocs/ee-reducer-fixed2dhistogram)
specifies a count matrix plus 1D lower-edge arrays for `xAxis` and `yAxis`,
also with `[min, max)` ranges. The 2D algorithm descriptor omits output names;
this implementation locally infers the output keys `histogram`, `xAxis`, and
`yAxis` from the official reference's terminology. Those keys are not verified
against a published `getOutputs()` result. The pinned and official references
establish output shapes and ranges only.

Inputs are lists of at most 1,000 rows. The 1D leaf accepts one scalar per row;
the 2D leaf accepts two. Null 1D values and incomplete 2D pairs are skipped,
but every non-null component is validated first. Values must be finite Python
integers in `[-2^53, 2^53]` or finite floats; booleans, strings, arrays,
non-finite numbers, and out-of-domain integers reject. Values exactly equal to
the lower bound enter the first bin, values equal to interior boundaries enter
the bin to their right, and the upper bound is excluded.

Steps accept positive exact integers carried as JSON integers or finite,
integer-valued floats, then canonicalize them to integers. Values outside the
exact ±2^53 integer domain reject. The pinned optional `cumulative` argument
defaults to false when omitted; explicit null is rejected as a non-Boolean.

Bin assignment uses exact rational representations of finite binary64 inputs,
so intermediate division or subtraction rounding cannot move a value across a
mathematical bin boundary. Lower edges are computed from exact rational values
of the binary64 bounds, then rounded to Float64 for output. A constructor
rejects a grid when its lower edges cannot be represented as distinct finite
Float64 values. In the 2D count matrix, axis 0 is the x-bin index (rows) and
axis 1 is the y-bin index (columns); each axis array contains its lower edges,
including the minimum and excluding the maximum. Output arrays are owned,
typed, and read-only. The 1D cumulative option emits running counts through
each bin.

The existing 1,000-row, 10,000-array-cell, 50,000-step, and 1 MB JSON limits
apply. Work for scanning and validating all rows, bins, count storage, and
output copies is charged before materialization. Shape limits follow those
shared budgets; the implementation adds no stricter family-specific cap.

Focused controls use an independent `Fraction` bin-assignment reference and
cover empty and out-of-range values, cumulative counts, exact boundaries,
incomplete pairs, scalar types, unrepresentable huge/subnormal grids, owned
read-only arrays, and shared work limits. These controls establish the local
finite kernel only; they are not a Google Earth Engine oracle.
