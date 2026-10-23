# Static Array selection operators

This module evaluates a finite static subset of `Array.bitsToArray`,
`Array.cut`, and `Array.mask`. The Python `earthengine-api` client is pinned at
1.7.49. Its serialized algorithm names and arguments are covered separately
from the local numerical results in `tests/test_ee_array_selection.py`.

`Array.bitsToArray(input)` takes a scalar Number, not an Array. Positive values
are emitted most-significant bit first, with no leading zeroes; zero produces
`[0]`. The official example shows `5` as `[1, 0, 1]` and `-1` as 64 one-bits.
For other negative inputs this local implementation uses signed 64-bit
two's-complement bits, an explicit policy inferred from the documented `-1`
case. That policy has not been compared with a live Earth Engine result. Inputs
must be finite integer values in the exact Float64 integer range, including
`-2**53` and `2**53`; fractional, boolean, dynamic, and larger integer inputs
fail.

`Array.cut(array, position)` requires one integer per input axis. `-1` keeps
that entire axis, while an in-range non-negative index retains one element and
leaves that axis at length one. Other negative values, wrong-length positions,
and out-of-range indices fail. The result keeps the input dtype and rank. A
rank-zero static array accepts an empty position list as its zero-axis case.

`Array.mask(input, mask)` keeps input positions corresponding to non-zero mask
values. The documented examples use matching input and mask shapes, including
rank-one vectors and `1×N` or `N×1` arrays. This finite subset requires exact
shape equality; a non-empty higher-rank array must have exactly one axis longer
than one, so the compressed output axis is unambiguous. A rank-one mask is not
broadcast across a higher-rank input. Differing shapes, multiple varying
axes, and non-empty higher-rank singleton-only arrays fail explicitly. The
separate `Image.arrayMask` API documents rank-preserving row/column masks for
array-valued pixels; its shape behavior is not assumed here.

All three operators require static `StaticArray` values where the signature
expects an Array. Values must be finite real numbers, booleans are rejected,
and integer array cells stay within `[-2**53, 2**53]`. Inputs are limited to
rank 8 and 10,000 cells. The shared 50,000-step compilation budget is charged
before value scans or output allocation; `Array.mask` reserves work for its
worst-case output because the retained count is not known until the mask is
scanned. Results are detached, read-only arrays and retain the input dtype for
`cut` and `mask`.

The pinned SDK serialization and independent local expected-value checks do
not establish execution or same-data parity with Google's service.

Official references: [Array.bitsToArray](https://developers.google.com/earth-engine/apidocs/ee-array-bitstoarray),
[Array.cut](https://developers.google.com/earth-engine/apidocs/ee-array-cut),
[Array.mask](https://developers.google.com/earth-engine/apidocs/ee-array-mask),
and the distinct [Image.arrayMask](https://developers.google.com/earth-engine/apidocs/ee-image-arraymask).
