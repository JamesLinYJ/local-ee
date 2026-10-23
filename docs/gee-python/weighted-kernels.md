# Weighted and transformed Kernels

The local compiler constructs immutable finite `KernelSpec` values for the
pinned `Kernel.gaussian`, `laplacian4`, `laplacian8`, `sobel`, `prewitt`, and
`roberts` algorithms, and supports the `Kernel.rotate` and `Kernel.add`
operations. Signatures and defaults come from the pinned Earth Engine
JavaScript/Python algorithm catalogue. Google publishes the
[Gaussian](https://developers.google.com/earth-engine/apidocs/ee-kernel-gaussian),
[Laplacian-4](https://developers.google.com/earth-engine/apidocs/ee-kernel-laplacian4),
[Laplacian-8](https://developers.google.com/earth-engine/apidocs/ee-kernel-laplacian8),
[Sobel](https://developers.google.com/earth-engine/apidocs/ee-kernel-sobel),
[Prewitt](https://developers.google.com/earth-engine/apidocs/ee-kernel-prewitt),
[Roberts](https://developers.google.com/earth-engine/apidocs/ee-kernel-roberts),
[rotation](https://developers.google.com/earth-engine/apidocs/ee-kernel-rotate),
and [addition](https://developers.google.com/earth-engine/apidocs/ee-kernel-add) methods.

The edge constructors use the coefficient matrices printed on their method
pages. Their focus follows the existing `Kernel.fixed` default: `(width // 2,
height // 2)`, which gives Roberts `(1, 1)` in its 2x2 matrix. The Roberts page
shows the matrix but does not separately state that focus coordinate. Edge
constructors default to `normalize=false`; finite `magnitude` scales every
coefficient. `Kernel.rotate` accepts integer quarter turns: positive values
rotate clockwise, negative values counterclockwise, and multiples of four
return an owned copy. Rotation carries the focus through the matrix transform.

`Kernel.add` aligns the two focus coordinates, sums coincident weights, and
returns the smallest rectangular union containing both matrices. With
`normalize=false`, signed weights and cancellation are preserved. With
`normalize=true`, local addition accepts only a nonnegative result and divides
by its exact sum; a zero-sum result fails. Results above 33 rows, 33 columns,
1089 cells, or focus offsets of 32 pixels fail before output allocation.

For `Kernel.gaussian`, local pixel support uses the shape constructors' extent
rule: `ceil(radius)` and integer offsets with `abs(x) <= radius` and
`abs(y) <= radius`; cells outside a fractional radius are zero. Thus radius 1
produces a 3x3 smoothing kernel, and radius 3 produces 7x7. Google's method
page gives a radius-3 5x5 example without defining its boundary convention.
That conflicts with this local radius-inclusive policy, which is deliberate
and does not claim exact Google footprint parity. `sigma` must be positive and
finite. The sampled values use the continuous 2-D density
`exp(-(x²+y²)/(2*sigma²)) / (2*pi*sigma²)`. With `normalize=false`, the density
prefactor is retained and log-domain scaling avoids an intermediate overflow
or underflow; an output outside finite Float64 fails. With the default
`normalize=true`, the common density prefactor cancels, then the finite samples
are normalized to sum to `magnitude`.

The official method pages describe normalization as making weights sum to
one, while Google's [convolution guide](https://developers.google.com/earth-engine/guides/image_convolutions)
says that a kernel with negative coefficients normalizes to sum to zero. The
guide does not specify normalized coefficient values. The local compiler
therefore rejects `normalize=true` whenever the input coefficients include a
negative weight, including `Kernel.fixed` and the signed edge constructors;
it also rejects signed `Kernel.add` results. This avoids inventing a rule for
an unresolved documentation conflict.

Only `units="pixels"` is supported. Meters require projection-dependent
resizing and fail explicitly. Every constructor and transform retains the
shared limits of 33 rows, 33 columns, 1089 cells, focus offsets at most 32,
and 50,000 units of precharged compilation work. Signed kernels have the explicit
[convolution execution contract](convolve.md); focal reductions retain their own
positive-support restrictions. Static value checks do not establish a complete
deployed workflow or Google same-data numerical parity.
