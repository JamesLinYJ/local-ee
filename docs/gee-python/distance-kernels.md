# Distance and compass Kernels

The local compiler now constructs finite values for the pinned 1.7.49
`Kernel.euclidean`, `Kernel.manhattan`, `Kernel.chebyshev`, `Kernel.compass`,
and `Kernel.kirsch` algorithms, and supports `Kernel.inverse`. Pinned signatures
and defaults are read from the bundled Earth Engine algorithm catalogue at
upstream revision `e189e4b89e785019ea5642ea8e80cb644749cd4a`.

Google documents the three distance constructors as pixel or meter kernels,
with `normalize=false` and `magnitude=1` by default. For an integer radius of
3, the published examples show a 7-by-7 matrix containing the distance from
each offset to the center: Euclidean distance is `sqrt(x*x + y*y)`, Manhattan
distance is `abs(x) + abs(y)`, and Chebyshev distance is
`max(abs(x), abs(y))`. The examples include corner values beyond the stated
radius, so radius defines the square extent rather than clipping cells by
distance. See Google's [Euclidean](https://developers.google.com/earth-engine/apidocs/ee-kernel-euclidean),
[Manhattan](https://developers.google.com/earth-engine/apidocs/ee-kernel-manhattan),
and [Chebyshev](https://developers.google.com/earth-engine/apidocs/ee-kernel-chebyshev)
references.

Local matrices are odd squares with `ceil(radius)` pixels of extent on each
side. Every cell in that square stores its metric distance, including the
corners. Google publishes integer-radius examples but does not define
fractional-radius rasterization; using `ceil` and retaining the full square for
fractional values is an explicit local policy. Radius must be a finite,
nonnegative real number. Radius 16 produces the maximum 33-by-33 matrix;
larger extents fail before matrix allocation. Radius zero produces a 1-by-1
zero matrix, so requesting normalization for radius zero fails because its sum
is zero. Normalization divides nonnegative distances by their exact sum before
applying magnitude. The focus is the center cell.

The [compass](https://developers.google.com/earth-engine/apidocs/ee-kernel-compass)
and [Kirsch](https://developers.google.com/earth-engine/apidocs/ee-kernel-kirsch)
constructors use the coefficient matrices printed in Google's references:

```text
compass             kirsch
[ 1,  1, -1]        [ 5, -3, -3]
[ 1, -2, -1]        [ 5,  0, -3]
[ 1,  1, -1]        [ 5, -3, -3]
```

Both default to `normalize=false` and `magnitude=1`. Magnitude scales every
coefficient. Local normalization with `normalize=true` is rejected for these
signed matrices because the method pages say values sum to one while Google's
[convolution guide](https://developers.google.com/earth-engine/guides/image_convolutions)
describes signed kernels normalizing to zero without specifying the coefficient
transformation.

`Kernel.inverse` returns a fresh immutable kernel with unchanged dimensions and
focus. Each nonzero value becomes its reciprocal; zero values remain zero, as
documented by Google's [inverse reference](https://developers.google.com/earth-engine/apidocs/ee-kernel-inverse).
If a finite nonzero value has a reciprocal outside the Float64 range, the local
compiler rejects it explicitly. Python SDK calls that pass `None` for optional
constructor parameters omit those arguments during serialization and therefore
use the pinned defaults. Explicit nulls in a raw invocation are invalid.

Only `units="pixels"` is supported; meter-based kernels need projection-aware
resizing and are rejected. All values retain the existing limits of 33 rows,
33 columns, 1089 cells, focus offsets no greater than 32, and the shared 50,000
step compilation budget. The focused tests compare all three published
radius-3 matrices, the compass and Kirsch coefficients, SDK serialization,
normalization, parameter errors, fractional-radius policy, reciprocal limits,
ownership, work bounds, and compilation of a distance kernel into
`Image.convolve`. These checks establish local compiler behavior, not Google
same-data numerical parity or full raster deployment acceptance.
