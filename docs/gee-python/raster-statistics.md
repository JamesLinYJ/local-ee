# Bounded raster numeric reductions

This local compiler slice supports the one-input numeric reducers used by
**Image.reduce** and **ImageCollection.reduce**. Image.reduce applies the
reducer to the image's band values at each pixel and returns bands named by
the reducer outputs. ImageCollection.reduce applies a one-input reducer
independently to each input band across observations; each output band is
named <input band>_<reducer output>. These rules follow the official
[Image.reduce](https://developers.google.com/earth-engine/apidocs/ee-image-reduce)
and
[ImageCollection.reduce](https://developers.google.com/earth-engine/apidocs/ee-imagecollection-reduce)
contracts.

Accepted legacy leaves are sum, mean, min, max, count, first, last, median,
and sample standard deviation (sd). The finite numeric leaves are product,
population stdDev, population variance, sampleVariance, and minMax. minMax
emits separate min and max outputs. sampleVariance keeps the public output
name variance and uses the sample-variance pixel operation. sd emits stdDev
and retains the legacy sd operation. A reducer must consume exactly one
input; combine is accepted only with sharedInputs=true. setOutputs may rename
or remove outputs, as long as at least one unique output remains. Weighted,
multi-input, nonnumeric, grouped, repeated, and forEach reducers reject.

For a collection, all input bands must have one source lineage. A finite
ImageSequence keeps each image as a separate ordered observation, including
separate items with the same timestamp. It does not pre-collapse same-day
frames. The default parallelScale=1 is accepted; other values are currently
unsupported.

Before a typed reduction combines distinct item IDs, the compiler requires
projection evidence from each selected STAC asset or its item fallback:
proj:epsg or proj:code, plus a six-value proj:transform. The CRS and affine
pixel basis must match; origins may differ by an integer number of pixels.
This is the explicit subset read from the
[STAC Projection Extension](https://github.com/stac-extensions/projection);
other projection fields do not provide alignment proof.
One distinct item ID remains covered by the existing one-source contract and
does not require projection metadata. Distinct collection lineages, missing
or conflicting grid evidence, and fractional-pixel offsets reject. This check
does not resample data. Export options such as scale and crs are downstream
and are not alignment evidence.

Pixel operands use the native Float64 reduction path after source-grid checks.
Image.reduce retains the input image's metadata and footprint. Collection
reduction preserves the input collection footprint. Reducer descriptors,
output names, item counts, and pixel operations use the existing 50,000-step
work budget and graph limits.

These are explicit local compatibility policies with focused static compiler
coverage. They do not claim same-data Google Earth Engine numerical parity,
complete API parity, or a server-side execution comparison.

## Verification and numerical boundaries

The standalone trusted GeoTrellis tile probe covers product, population and
sample dispersion, min/max, all-NoData, singleton values, signed zero, adjacent
large Float64 values and subnormal moments. Standard deviations do not first
form a possibly overflowing variance. The existing sample `sd` uses the same
robust centered/scaled kernel with its sample denominator. Actual overflowing
results reject; representable underflow follows Float64. This probe and the
full adapter build do not start Spark or install a new runtime.

`toDouble` commutes across observation first/last selection to preserve source
precision; validity masks use a separate mask cube rather than passing numeric
results through Float32 callbacks. Earlier arithmetic is not retroactively
upgraded. Further general Float64 pixel arithmetic still requires explicit
conversion to the supported Float32 path.

[Example 45](../../examples/45_GEE_python_raster_statistics.py) and its tests
compose six statistics across bands, observations and arrays using both pinned
clients. The synthetic evaluator verifies values, repeated observations,
singleton sample results and masks independently; it is not a native workflow
runner. A one-band variance graph compiles 50 observations into 351 nodes;
100 observations exceed the unchanged 500-node cap. This measures compilation,
not runtime throughput. See [wave40 report](../../reports/gee-python-wave40.json).
