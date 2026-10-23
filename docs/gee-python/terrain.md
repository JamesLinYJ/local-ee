# Bounded `ee.Terrain`

Catalog boundary: normalized local `cop-dem-glo-30/v1` elevation items are now
admitted alongside the existing Sentinel-2 path; see the [DEM contract](local-dem.md).
Legacy or arbitrary uploaded DEMs and Google DEM aliases are not admitted.
Wave45 compiler fixtures still inject synthetic elevation metadata under their
historical fixture ID. Wave46 separately exercises actual synthetic DEM files.
A deployed end-to-end terrain job remains unverified. Renaming a reflectance
band to `elevation` does not make it elevation data.

The offline compiler supports the pinned SDK calls `ee.Terrain.products`,
`ee.Terrain.slope`, `ee.Terrain.aspect`, `ee.Terrain.hillshade`, and the
deprecated `ee.Algorithms.Terrain` alias. `products` appends logical bands in
the order `slope`, `aspect`, `hillshade` to every original input band and
retains the image properties and footprint. Existing bands with any of those
three names cause an explicit collision error. The individual methods return
one band named for the selected operation and retain image metadata.

The input must be a nonempty scalar image. A single band may have any name; a
multiband image must contain a band named `elevation`, and that band is the
only input to the terrain calculation. Its source values must already represent
elevation in metres. The compiler does not infer or apply scale/offset
conversions. Static source-free images, array-valued bands, a missing elevation
band, and an unproven common source grid are rejected.

Each derivative is represented by one `local_ee_terrain` node with a canonical
bounded specification. The compiler selects the actual input grid, casts source
values to Float64 before first/last observation selection, proves a common grid
for combined observations, and plans the full source bounds before output
region masking or resampling. This keeps neighborhood reads on the source
pixels. The native implementation uses the actual cube CRS and affine layout;
for transformable geographic and projected grids it builds east/north
distances from the four neighboring pixel centers in a local WGS84 tangent
chord basis. It does not treat angular coordinates as metres. The center and
all four orthogonal neighbors must be valid, so image edges and incomplete
neighborhoods are NoData. Flat aspect is locally defined as zero.

`hillshade` accepts finite static numeric `azimuth` and `elevation` arguments.
Omitted and SDK-serialized `null` values use the official defaults of 270 and
45 degrees. Both angles are normalized modulo 360 before the native process;
dynamic values, booleans, NaN, and infinity are rejected. The native brightness
is rounded to the integer range 0–255, but the physical output remains Float64
with NaN for missing pixels. This preserves zero brightness and the mask; it
does not claim the official unsigned-byte storage type.

These policies provide bounded compilation and a local metric basis. They do
not establish Google Earth Engine numerical equivalence. The official API
describes four-connected gradients, degree outputs, the `products` bands and
metadata, and hillshade defaults in its [products](https://developers.google.com/earth-engine/apidocs/ee-terrain-products),
[slope](https://developers.google.com/earth-engine/apidocs/ee-terrain-slope),
[aspect](https://developers.google.com/earth-engine/apidocs/ee-terrain-aspect),
and [hillshade](https://developers.google.com/earth-engine/apidocs/ee-terrain-hillshade)
references. Local protocol and graph limits remain 50,000 work steps and 500
process nodes.

See [native metric and numerical validation](terrain-native.md) for the exact
distance policy and its evidence, and [example 50](../../examples/50_GEE_python_terrain.py)
for products, smoothing, per-observation terrain and neighborhood feature bands.
The example requires a supplied local elevation collection; it does not fetch a
Google DEM or silently reinterpret a reflectance band as elevation.
