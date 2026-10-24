# Spectral preparation and bounded Image helpers

Example 62 (Python) and example 16 (JavaScript) use two versioned synthetic
STAC items. Each item has six pixel positions on the same declared 1-row,
6-column `EPSG:32649` grid; the local arrays, item records, band order, masks,
and point locations are all in
`tests/fixtures/ee-spectral-preparation-wave57-v1.json`. The scenes have
different NoData positions, so checks can detect mask or scene leakage. This
is synthetic local evidence; it does not read user imagery or call Google.

The example renames source storage bands from `B02/B03/B04` to
`blue/green/red`, explicitly selects `red/green/blue`, converts RGB to HSV and
back, applies a piecewise-linear calibration to the first selected band, and
applies a polynomial to the green band. The LUT uses `clamp`; the polynomial
coefficients are in increasing degree order. The fixed three-row endmember
matrix consumes explicitly selected `blue/green/red` values and requests
non-negative fractions that sum to one. Python wraps algorithm results in
`ee.Image` because the pinned client types several generated return values as
an unknown-band `Element`; JavaScript uses the same graph operations.

The workflows compile with both pinned clients into semantically identical
local process graphs. Each SDK graph covers two scenes with six pixel positions
per scene and retains each scene's distinct source ID. Five valid cells per
scene are evaluated against independent color and Fraction references. Across
both SDKs the RGB-to-HSV maximum absolute error is 1.11e-16; RGB-to-HSV-to-RGB
is 1.67e-16; LUT error is zero; and the polynomial maximum is 5.56e-17. The
composed color graph is 172 process nodes and 24,076 compact-JSON bytes per
scene. Its measured translator work is 49,694 of the shared 50,000-step cap,
so more composition can be rejected even though these fixed graphs pass.

The unmix expression compiles to one local_ee_unmix producer. The fixture's
independent oracle is an exact rational mixture, not a Python solver. Native
sample checks are enabled only when the separately built and manifested tile
probe is available; they consume returned native tile bands and compare every
scene against its exact fractions. If that manifest is absent, the integration
test skips instead of fabricating sample results.

The manifested run recorded for this fixture evaluated two scene cases and
36 component cells. Thirty finite values differed from the exact fractions by
at most `1.39e-16`; six component values were NoData at the scenes' distinct
masked pixels. Both the Python and JavaScript compiled sample graphs consumed
those returned tile bands and matched them exactly before the separate
fraction-reference comparison.

The `2e-12` absolute and zero relative tolerance used for unmix fixture
comparisons is specific to its exact-rational mixtures. It is not a universal
accuracy guarantee. The other six-pixel sample checks use independent
references and record their measured error; they do not establish arbitrary
image, full Spark batch, deployed service, browser, production-data, or Google
same-input acceptance.

## RGB, HSV, and calibration

| Operation | Python | JavaScript | Local contract |
| --- | --- | --- | --- |
| `Image.rgbToHsv` | `rgb.rgbToHsv()` | `rgb.rgbToHsv()` | Exactly three caller-ordered bands, interpreted as red, green, blue; the pinned reference expects values in `[0,1]`. Output is `hue`, `saturation`, `value`. Local out-of-range or masked samples become NoData. |
| `Image.hsvToRgb` | `hsv.hsvToRgb()` | `hsv.hsvToRgb()` | Exactly three caller-ordered bands, interpreted as hue, saturation, value; the pinned reference expects values in `[0,1]`. Output is `red`, `green`, `blue`. Local out-of-range or masked samples become NoData. |
| `Image.interpolate` | `image.interpolate(x, y, behavior='extrapolate')` | `image.interpolate(x, y, behavior)` | Reads only the first band and keeps its name. `x` and `y` are finite lists of equal length 2–16; `x` must increase strictly. Behavior defaults to `extrapolate`; accepted values are `extrapolate`, `clamp`, `input`, and `mask`. |
| `Image.polynomial` | `image.polynomial(coefficients)` | `image.polynomial(coefficients)` | Applies the finite coefficient list independently to every band, preserving names. Coefficients are ascending by degree, beginning with the constant term; local length is 1–64. |
| `Image.unmix` | `image.unmix(endmembers, sumToOne=False, nonNegative=False)` | `image.unmix(endmembers, sumToOne, nonNegative)` | The selected ordered input has 1–8 bands; the matrix has 1–8 finite rows, each with exactly one coefficient per input band. Both flags default to false and must be booleans. Local outputs are Float64 `unmix_0` … in row order; whole-spectrum NoData propagation and valid-Infinity rejection apply. Both constraints select constrained solves, not post-hoc clipping. Rank, conditioning, or unresolved numerical ties may fail closed under local bounds; no universal rank threshold or tie guarantee is claimed, and this is not a Google oracle. |

The unmix solver precomputes bounded support-face SVD operators; it does
not use normal equations or clamp a negative unconstrained solution. It uses
exact dyadic rank for the original coefficients, centers component contrasts
before the simplex transform, and bounds decimal arithmetic at 80 digits.
The retained singular-value ratio must be at least `2^-48`. A separate runtime
coefficient-error estimate must be at most `1e-8` times the local coefficient
scale: scale one for simplex-plus-nonnegative fits, otherwise
`max(1, ||candidate||∞)`. This check happens before feasibility filtering;
an unresolved face rejects the whole solve. Objective/norm uncertainty is
checked before choosing among candidates. Lexicographic tie-breaking applies
only to numerically indistinguishable coefficient vectors, and ambiguous
materially different minima reject. These are conservative local admission
and reproducibility policies, not universal accuracy or Google solver claims.

Resource admission remains restrictive: the normal three-band/three-endmember
simplex test admits at most **26 pixels per tile** under the unchanged
`100,000,000` tile-work cap; 27 pixels and a standard 256×256 tile reject.
This is a budget check, not measured throughput. The demonstrated
RGB→HSV→RGB graph also consumes 49,694 of 50,000 compiler work steps
(172 process nodes), so a larger composition can still reject. The current
component evidence does not establish that ordinary full-sized raster jobs
can run these combinations without future bounded execution work.

The local hue convention uses turns in `[0,1)`, chooses the red branch when
maximum channels tie, and sets hue to zero for achromatic RGB. HSV hue one
wraps to zero in HSV-to-RGB. These endpoint choices are local conventions;
the pinned API description does not settle every tie or endpoint case. The
fixture includes a red/green maximum tie and checks both directions against
independent formulas.

The public JavaScript `Image.unmix` wrapper takes its optional booleans
positionally. Python accepts the options by name. The example uses
`ee.Image(...)` around generated color, curve, and unmix results where the
Python SDK's return annotation is broader than the runtime image value.
Calling `.toDouble()` after `.toFloat()` does not restore precision already
lost at the Float32 cast.

## Band ordering, casts, identity, and metadata

These methods are documented here because band order, numeric type, scene
identity, and metadata define the inputs to spectral calculations. Python
examples show the pinned public wrapper form; JavaScript uses the same method
names and positional options. `Image.cat` is a static helper in both clients.

| Operation | Python | Local contract and bounds |
| --- | --- | --- |
| `Image.regexpRename` | `image.regexpRename(regex, replacement, all=True)` | Uses bounded RE2 matching and `$n` capture expansion. `all` defaults to true (local `None` also means true); false replaces only the first match. Unmatched names are copied; duplicate resulting names reject. Limits: 10,000 bands, 4,096 UTF-8 pattern bytes, 1 MiB RE2 program memory, 1 MiB subject/output UTF-8, and the shared 50,000-step budget. |
| `Image.slice` | `image.slice(start, end=None)` | Selects a contiguous positional range; end is exclusive, negative positions count from the end, and input order is retained. Local out-of-range bounds clamp as in Python slicing; reversed ranges are empty. Limit: 10,000 bands and shared 50,000-step work. |
| `Image.cat` | `ee.Image.cat(image1, image2, ...)` | Concatenates input bands in order. Duplicate names receive `_1`, `_2`, … suffixes; the first image supplies retained metadata. Constants require another real image to supply a finite grid; a constant-only result does not invent one. Limits: 10,000 inputs, 10,000 output bands, and shared 50,000-step work. |
| `Image.float` | `image.float()` | Alias for the existing Float32 cast path. Preserves names, masks, source, and properties; values are rounded at this cast stage. Array-image and array-band casts are supported. |
| `Image.double` | `image.double()` | Alias for the existing Float64 cast path. Preserves names, masks, source, and properties; a prior Float32 rounding boundary remains. Array-image and array-band casts are supported. |
| `Image.id` | `image.id()` | Returns an identity carried by exactly one actual local source item. Missing, ambiguous, empty identities and source-free constants reject; IDs are never synthesized from properties. Mapped collection calls use the actual loaded item. |
| `Image.metadata` | `image.metadata(property, name=None)` | Requires a present finite numeric property on an actual loaded source item. Produces a Double constant band; the default band name is the property key. Local finite metadata constants must lie within `[-2^53, 2^53]`; it borrows the actual finite source grid/footprint, does not inherit input pixel NoData, and retains image properties as a local policy. Collection mapping resolves each actual item. |

For the generated JavaScript wrappers the equivalent calls are
`image.regexpRename(regex, replacement, all)`, `image.slice(start, end)`,
`ee.Image.cat(image1, image2, ...)`, `image.float()`, `image.double()`,
`image.id()`, and `image.metadata(property, name)`. Optional values may be
omitted where the wrapper allows them. The server-side argument maps are
validated; extra keys and unsupported values reject rather than being
silently ignored.

## Fixed-shape array preparation

Array operations here are finite raster operations, not dynamic or ragged
arrays. All retain source masks and metadata according to the local policies
below. Current limits include rank 1–8 where rank applies, 64 values per
axis, 64 output cells, the shared 50,000-step work budget, and 500 compiled
graph nodes.

| Operation | Python | Local contract and bounds |
| --- | --- | --- |
| `Image.arrayDimensions` | `image.arrayDimensions()` | Emits the rank for each array band and zero for a scalar band; the output band names and image metadata are preserved. A masked source value stays NoData. |
| `Image.arrayDotProduct` | `image1.arrayDotProduct(image2)` | Computes the ordered sum of paired products for equal-length rank-1 vectors. Equal band counts pair positionally; one-band broadcasting is supported. Output names follow the non-broadcast operand (left names for equal counts), and image1 supplies metadata, with actual right-source fallback for a source-free left operand. Whole-vector masks intersect. Sourced operands must identify the same scene and pass common-grid validation. The PixelCompiler's Float32/Double precision stages apply. |
| `Image.arrayPad` | `image.arrayPad(lengths, pad=0.0)` | `lengths` has one non-negative integer target per rank axis; each output axis is `max(input, target)`, so padding appends only. Every array band must share one shape. Rank is 1–8, each axis is at most 64, and the bundle has at most 64 output cells. Names and metadata remain; the complete original array mask applies to appended cells too. Pad precision follows final source-cell precision; explicit `toFloat()` resets it. Non-finite/boolean pads and Float32 overflow reject; added on-grid pad constants must fit the local range [-2^53, 2^53]. Growing an array needs one concrete single-scene source/grid; source-free, mixed-scene, and multi-scene growth reject. |

The array methods have the same JavaScript forms:
`image.arrayDimensions()`, `image1.arrayDotProduct(image2)`, and
`image.arrayPad(lengths, pad)`. The array input and output graph remains
subject to the existing 500-node and 50,000-work caps; these limits are not
increased for nested band preparation.

## Verification boundary

The focused workflow tests use both fixture scenes and all six declared pixel
positions. They compare the pinned Python and JavaScript graphs after JSON
normalization, inspect source IDs and output bands, and check local sample
values. The independent unmix oracle is the fixture's exact rational mixture;
the Python test helper contains no unmix solver. When its separately built
native manifest is available, the integration test compares returned native
tile bands with those fractions. If that manifest is absent, the test skips.
Client serialization, local compilation, synthetic sample evaluation, and
native tile evidence are separate checks. No Google-side same-data result,
complete Spark batch, deployed service, browser, or private production-image
acceptance is claimed.
