# Finite correlation and trend reducers

The pinned Python SDK exposes four finite reducer signatures in this family:
`Reducer.pearsonsCorrelation()` and `Reducer.spearmansCorrelation()` take two
columns; `Reducer.kendallsCorrelation(numInputs=1)` takes one by default or two
when `numInputs=2`; and `Reducer.sensSlope()` takes x followed by y. Earth Engine
documents Pearson's two-sided test of zero correlation, Kendall tau-b and its
one-input sequence x behavior, and Sen's slope plus offset in the method
references for [Pearson](https://developers.google.com/earth-engine/apidocs/ee-reducer-pearsonscorrelation),
[Spearman](https://developers.google.com/earth-engine/apidocs/ee-reducer-spearmanscorrelation),
[Kendall](https://developers.google.com/earth-engine/apidocs/ee-reducer-kendallscorrelation),
and [Sen slope](https://developers.google.com/earth-engine/apidocs/ee-reducer-sensslope).
Those method signatures do not enumerate result dictionary keys. This local
family uses `correlation` and `p-value` for Pearson, `correlation` for
Spearman, `tau` for Kendall, and `slope` and `offset` for Sen's slope; these
output names are inferred from the reducer terminology and method conventions,
not claimed as verified Google output parity.

This local implementation is limited to static `List.reduce` and literal inline
`FeatureCollection.reduceColumns` consumers. It accepts at most 1000 rows, shares
the 50000-step work budget, preserves the 1 MB JSON limit, and has a 32-input
composed-reducer ceiling. The four leaves themselves use one or two columns.
There are no new runtime dependencies or raster semantics in this family.

Rows are complete-case: if any input is null, that row is omitted. Every other
field is still checked, including fields in an omitted row; booleans, non-finite
floats, non-numbers, and integers outside the exact ±2^53 range fail. Empty or
undefined statistics return null output fields. Pearson's coefficient is
defined with two or more nonconstant complete pairs; its p-value is null below
three pairs because the Student-t test has no positive degrees of freedom.
Constant input has null coefficient and p-value. A perfect coefficient with at
least three pairs has p-value zero. Spearman uses 1-based average ranks for
ties. Kendall uses tau-b; with one input, the x values are the increasing order
of retained complete rows. Tied x/y pairs do not count as concordant or
discordant, and a zero tau-b denominator returns null.

Sen's slope is the median of all pairwise `(y[j]-y[i])/(x[j]-x[i])` values for
unequal x. Equal-x pairs are omitted. The returned offset is the median of
`y[i] - slope*x[i]` over complete observations for this local reducer policy.
Even-sized medians average the two middle values. If there are no defined pair
slopes, both fields are null.
Scaled power-of-two arithmetic keeps pair differences, slopes and intercepts
finite through large common offsets and subnormal inputs; a final result outside
the finite Float64 range fails. Pair loops and sorting are charged before the
kernel runs, so the shared work cap can reject a quadratic workload well below
1000 rows.

The formulas follow the method definitions referenced by the pinned SDK:
Pearson r is centered covariance divided by the product of centered norms; its
two-sided p-value is the Student-t tail with `n-2` degrees of freedom;
Spearman is Pearson correlation of average-rank vectors; and Kendall tau-b is
`(concordant-discordant) / sqrt((pairs-xy_ties)*(pairs-yx_ties))`. Sen's slope
uses the pairwise median estimator introduced by Sen. See the primary [Sen 1968
paper](https://doi.org/10.1080/01621459.1968.10480934), [Kendall 1945 on ties](https://doi.org/10.1093/biomet/33.3.239),
and the [Apache Commons Math 3.6.1 correlation documentation](https://commons.apache.org/proper/commons-math/javadocs/api-3.6.1/org/apache/commons/math3/stat/correlation/package-summary.html)
that the Earth Engine method references point to.

The focused tests compare these kernels with independent closed-form references
and explicit tie/edge-case calculations. They do not establish same-data
agreement with Google's service or production runtime acceptance.
