# Finite circular reducers

The pinned Earth Engine Python API exposes the no-argument
`Reducer.circularMean()`, `Reducer.circularStddev()` and
`Reducer.circularVariance()` constructors. Their inputs are radians. The
documented result labels are `circularMean`, `circularStdDev` and
`circularVariance`; the mean is returned on the `[-π, π]` branch. See Google's
references for [circular mean](https://developers.google.com/earth-engine/apidocs/ee-reducer-circularmean),
[circular standard deviation](https://developers.google.com/earth-engine/apidocs/ee-reducer-circularstddev)
and [circular variance](https://developers.google.com/earth-engine/apidocs/ee-reducer-circularvariance).

This implementation is a closed static table reducer family. Each row has one
numeric angle; nulls are skipped, and booleans, non-finite values, malformed
rows and integers outside the exact `[-2^53, 2^53]` domain fail. It accepts at
most 1,000 rows and charges scans, trigonometric work and result construction
to the existing shared 50,000-step budget. The 1 MB output cap is retained.
Only unweighted scalar inputs are implemented here. This module does not add
weighted, raster, neighborhood, or runtime execution semantics.

For `n` retained angles, the circular mean is the argument of the resultant
vector

`(Σ cos θᵢ, Σ sin θᵢ)`,

the mean resultant length is `R = hypot(Σ cos θᵢ, Σ sin θᵢ) / n`, circular
variance is `1 - R`, and circular standard deviation is `sqrt(-2 ln R)`.
The official standard-deviation reference states that formula. The mean
resultant length and variance definitions, including an undefined direction
when the resultant is zero, are also set out in Kutil's [primary circular
statistics paper](https://www.cosy.sbg.ac.at/~rkutil/publication/Kutil12a.pdf).

Local undefined-result policy is explicit: empty or all-null input returns
null for all three statistics. When a non-empty sample's computed resultant
length is at most `32 × machine epsilon`, mean and standard deviation are
undefined and return null; variance returns `1`. This threshold treats exact
antipodal cancellation and its libm roundoff as zero, while resultants above
the threshold remain defined. The threshold also means a genuinely tiny
resultant inside that interval is treated as numerically indeterminate.

To preserve small spread, the kernel centers relative angular differences and
uses `2 sin²(δ/2)` for `1 - cos(δ)`, with `log1p` for the standard deviation.
If those squared differences underflow while their square root remains
representable, it uses the centered RMS small-angle limit. Large absolute
finite inputs go through the platform `sin`/`cos` argument reduction; the
kernel does not reduce those inputs with `% 2π`. These are stable Float64
policies, not exact arithmetic or evidence of same-data agreement with Google.

Focused tests compare normal, near-coincident, wrap-boundary, near-antipodal
and huge-angle samples to analytic or independent high-precision Decimal
references. They do not establish raster, weighted, production-runtime or
Google same-data acceptance.
