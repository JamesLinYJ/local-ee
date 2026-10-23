# Static pixel Kernels

This page describes the base shape constructors. See [weighted kernels](weighted-kernels.md)
for Gaussian, edge, rotation and addition, and [distance kernels](distance-kernels.md)
for Euclidean/Manhattan/Chebyshev, Compass/Kirsch and inverse. Each consumer
has its own weight rules: [focal](focal.md), [convolve](convolve.md), and
[neighborhood statistics](neighborhood-statistics.md).

The local compiler constructs immutable finite `KernelSpec` values for the
pinned `Kernel.fixed`, `circle`, `square`, `rectangle`, `plus`, `cross`,
`diamond`, and `octagon` algorithms. Their signatures and defaults come from
the pinned Earth Engine Python/JavaScript algorithm catalogue (SDK 1.7.49,
upstream commit `e189e4b89e785019ea5642ea8e80cb644749cd4a`). The official
references describe [`Kernel.fixed`](https://developers.google.com/earth-engine/apidocs/ee-kernel-fixed),
the [shape constructors](https://developers.google.com/earth-engine/api_docs),
and [focal operations](https://developers.google.com/earth-engine/apidocs/ee-image-focalmean).

`fixed` requires non-empty rectangular weights. Omitted dimensions and
`width=-1` / `height=-1` infer the corresponding dimensions from the weights;
omitted `x` / `y` and `-1` focus sentinels select `width // 2` and `height // 2`.
Explicit dimensions must match. Focus coordinates are zero-based offsets from
the left and top. `normalize` defaults to false. When enabled, nonnegative weights divide by
their exact sum; a zero sum fails. Negative source weights with normalization
are rejected because Google's method pages and convolution guide describe different
normalization policies. Negative weights are retained when normalization is disabled.
Normalization and magnitude scaling must produce finite results; see [weighted kernels](weighted-kernels.md).

The shape constructors default to `units="pixels"`, `normalize=True`, and
`magnitude=1`. Rectangle requires both `xRadius` and `yRadius`; the others
require `radius`. Local shapes use odd matrices with extent `ceil(radius)` on
each axis. Membership is evaluated against the original fractional radius at
integer pixel offsets: Euclidean distance for circle, Chebyshev distance for
square, the two axes for plus, the two diagonals for cross, Manhattan distance
for diamond, and the clipped-corner rule
`2*max(|x|,|y|)+min(|x|,|y|) <= 2*radius+1` for octagon. Rectangle applies the
independent x/y radii. Selected cells start at weight one and others at zero;
normalization divides by the selected-cell count, then magnitude scales each
weight.

The radius-3 masks match the examples in Google's [circle](https://developers.google.com/earth-engine/apidocs/ee-kernel-circle),
[square](https://developers.google.com/earth-engine/apidocs/ee-kernel-square),
[rectangle](https://developers.google.com/earth-engine/apidocs/ee-kernel-rectangle),
[plus](https://developers.google.com/earth-engine/apidocs/ee-kernel-plus),
[cross](https://developers.google.com/earth-engine/apidocs/ee-kernel-cross),
[diamond](https://developers.google.com/earth-engine/apidocs/ee-kernel-diamond),
and [octagon](https://developers.google.com/earth-engine/apidocs/ee-kernel-octagon)
pages. The public docs do not define fractional-radius rasterization or the
corner rule for every radius. Those cases are explicit local policies, not
claims of Google numerical parity. `Image.focalMean` and related methods
document a default radius of 1.5 and default circle kernel; the official SDK
serialization test preserves that default, but the focal consumer and raster
execution are validated separately.

Meters need projection-dependent resizing, so `units="meters"` and unknown
units fail explicitly. Matrices are limited to 33 rows, 33 columns, 1089 cells,
and focus offsets at most 32. Values must be finite real numbers; booleans and
integers outside `[-2**53, 2**53]` fail. Scans, normalization, allocation and
revalidation consume the shared 50,000-step work budget before their work.

This module validates construction and the immutable value contract. It does
not establish raster-engine execution, focal behavior, Google same-data parity,
or support for negative-weight kernels in downstream focal consumers.
