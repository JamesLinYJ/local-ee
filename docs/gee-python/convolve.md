# Bounded `Image.convolve`

The local compiler accepts `Image.convolve(kernel)` when the image has named scalar pixel bands and the kernel is a finite pixel `KernelSpec`. Each source band is lowered to a separate `local_ee_convolve` node, with the original band names, image properties, footprint, source grid, and time dimension retained. Static source-free images, array-valued images, unsupported arguments, and input expressions without a proven common source grid are rejected.

The kernel is interpreted in matrix orientation: for matrix column `x` and row `y`, the sample offset is `dx = x - focusX`, `dy = y - focusY`, and the value comes from source pixel `(column + dx, row + dy)`. Coefficients are not reversed. Zero coefficients are removed before compilation; an all-zero matrix becomes a single zero coefficient and produces zero on valid centers while retaining center NoData. Coefficients use exact Float64 bit encodings in a canonical, bounded specification with at most 1089 unique offsets, each within 32 pixels.

The native implementation uses strict complete support: a masked center stays NoData, and every nonzero-weight neighbor must be present and unmasked. Zero-weight neighbors are not required. Edges are not renormalized and missing source tiles are not synthesized. These are explicit local policies, and numerical or mask parity with Google's implementation has not been verified.

Convolution reads each finite source item's full bounding box before any band is compiled. An explicit `Image.clip()` remains upstream and masks the convolution input. Export-region masking and output resampling remain downstream, so a smaller export region does not reduce neighborhood input work. Pixel offsets refer to the source grid. The compiler retains the existing 50,000-step and 500-node limits.

The pinned dry-run driver records `filter_bands` without updating its band metadata.
The local focal/convolution bridges recover an explicit single-band filter from a
bounded, unambiguous trace through known band-preserving operations; they do not
infer a selection through merges or other shape-changing operations. Actual cubes
still require one metadata band and independent native tile validation. Dry-run
rename and merge metadata remain incomplete upstream; tests separately check the
compiler's logical names and the native bridge's one-band schema, without treating
dry-run metadata as evidence of a completed multiband Spark job.
Regression checks also execute the actual pinned process evaluator and registry
for load → single-band filter → focal/convolve → output resample/ROI, confirming
that the original input extent and selected source band survive downstream pushdown.

See [weighted kernels](weighted-kernels.md), [native computation](convolve-native.md),
and [example 48](../../examples/48_GEE_python_convolution.py). The official
[convolution guide](https://developers.google.com/earth-engine/guides/image_convolutions)
describes per-band linear combinations and edge kernels; the local policies above
remain explicit where no same-data Google comparison is available.
