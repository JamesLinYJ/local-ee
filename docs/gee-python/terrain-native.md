# Native Terrain metric and numerical contract

`local_ee_terrain` consumes exactly one actual raster band and one canonical
`spec` string. The Scala parser independently requires compact sorted ASCII
JSON of at most 1024 bytes with exactly `azimuth`, `elevation`, `operation`,
and `v`. Angles are sixteen lowercase hexadecimal binary64 bit strings,
finite and normalized to `[0,360)` with positive zero. Slope and aspect require
the canonical 270°/45° defaults; hillshade uses both supplied angles.

The metric comes from the source layer's actual layout extent and CRS. For each
needed pixel center, the native code transforms the source coordinate to
WGS84, maps the ellipsoid surface point to WGS84 ECEF, and projects the
east-west and south-north chord differences into the center's local east/north
tangent basis. A conditioned 2×2 solve converts the two elevation differences
to local gradients. This local tangent-chord policy handles geographic degrees,
projected metres or feet, and grid convergence without treating native axis
units as metres. It is a declared local metric; it is not claimed to reproduce
the undocumented distance or edge choices of Google Earth Engine. Non-finite
transforms, coordinates at the poles, spacing below ECEF resolution, and
singular or ill-conditioned local bases fail clearly. Pixel-center indexing is
limited to `2^52` columns and rows so every `index + 0.5` remains exactly
representable in binary64. Global tile offsets use checked 64-bit arithmetic.

All four cardinal neighbors and the center must be valid. A raster edge, NaN
source cell, absent tile, or absent same-time neighbor yields Float64 NaN. No
missing key is synthesized; `SpaceTimeKey` buffering only uses the same
instant. The original keys, source grid and time values stay attached to the
output. Slope is `atan(hypot(gEast,gNorth))` in degrees. Aspect is the
downslope bearing clockwise from true north; a flat pixel is locally defined
as zero and rounded bearings at 360° are canonicalized to zero. Hillshade uses
the Lambert dot product of the upward surface normal and the sun vector,
clamps illumination to `[0,1]`, then rounds with
`floor(clamp(illumination) * 255 + 0.5)`. Its physical output remains Float64,
so zero and 255 are valid data and NaN alone marks missing cells.

The central east-west and south-north elevation differences have independent
power-of-two mantissa/exponent representations. This avoids deriving both
differences from a scale dominated by an unrelated high center or orthogonal
pair, and permits finite differences larger than binary64's largest value.
Gradient combinations and slope conversion are range-stable; tiny slopes are
converted in log space so a subnormal gradient can still produce a representable
degree result. This stability is bounded by binary64 input precision and local
metric conditioning; it does not invent precision already absent from source
pixels.

Preflight preserves the existing caps: 100,000 source keys, 100,000,000
aggregate decoded cells, 10,000,000 decoded cells per tile, 100,000,000 work
units per tile and 1,000,000,000 in aggregate. Work charges include source
validation, six halo-cache array initializations, projected-center transforms,
WGS84/ECEF conversion, per-output source reads, tangent-metric construction and
solve, independently scaled differences, and the selected renderer. It also
reports one transform-result tuple allocation per projected center and the
nine explicit arrays per tile (six coordinate-cache arrays, twelve-double
scratch, output storage, and single-band wrapper storage). For 256×256 tiles,
the model is 21,037,312 work units per tile, 189,335,808 for nine tiles,
599,076 maximum coordinate transforms/result tuples, 81 explicit arrays and
the corresponding explicit-array byte estimate. No cap is raised.

`tests/test_ee_terrain_kernel.py` has default source-contract checks and an
opt-in actual JVM probe (`LOCAL_EE_RUN_TERRAIN_KERNEL_TEST=1`). The trusted
probe builds the locked adapter, calls the actual GeoTrellis tile kernel on
manual halos and through collection `BufferTilesRDD`, and does not start a
SparkContext, service, or user script. Its independent reference uses pyproj
CRS transforms and a Decimal-backed ECEF/tangent 2×2 solve. Evidence includes
geographic equatorial and latitude-60° grids, UTM metres and projected US
survey feet, flat/cardinal surfaces, custom illumination, exact flat hillshade
values of 0 and 255, masks, missing tile seams, time isolation, large common
offsets, a valid `1e308` center, opposing `-Double.MaxValue`/`Double.MaxValue`
neighbors, and a subnormal cross-gradient below equal `1e308` east/west
neighbors. The probe also checks canonical-wire rejection, the 256×256 budget
readback, half-cell indexing rejection, global columns above `Int.MaxValue`,
and invalid/polar/singular metrics.

The completed local probe compared 14 cases and 504 output cells through each
path, with 1,294 actual coordinate transforms and matching transform-result
objects across both runs, 990 counted explicit arrays, eight temporal keys,
and a largest absolute slope/aspect difference of `5.56e-9` degrees against
the `2e-7` degree tolerance. Hillshade integers matched exactly, including
valid 0 and 255. The locked 256×256 one-tile estimate read back as 21,037,312
work units; the 3×3 estimate was 189,335,808, below the unchanged aggregate
cap. Rejection counts are reported by separate category: nine canonical-wire
cases, seven work-budget cases, and five grid/metric cases. The wire count is
not an aggregate of all negative checks. These are actual GeoTrellis tile and
collection-buffer results, not a SparkContext job.

Passing this probe establishes synthetic tile-kernel and collection-buffer
behavior only. It does not establish a complete Spark RDD task, service or
deployment acceptance, private-data behavior, or numerical equivalence against
a Google Earth Engine result. See [Terrain compilation](terrain.md) for the
public subset and workflow boundaries.
