"""Explicit finite spectral and raster preparation contracts, not Google parity."""

SPECTRAL_PREPARATION_LIMITS = {
    "Image.unmix": [
        "Actual finite source-bound scalar bands only,1..8 input bands and1..8 "
        "component rows of matching width. Canonical bounded v1 binary64 endmember "
        "wire; sumToOne and nonNegative are independent boolean constraints. One "
        "shared audited native producer returns Float64 components in endmember "
        "order, locally named unmix_0..; no source-free constant-fold approximation. "
        "Current source grid, per-item asset evidence and temporal dimensions must "
        "match. Whole-input NoData masks all components, valid Infinity rejects. "
        "Native support-face solver has local rank/conditioning and useful-uncertainty "
        "admission: unresolved global faces/ties reject rather than returning a "
        "purported optimum. Numerical policies are documented in spectral-preparation.md. "
        "Shared50000-work/500-node/1MB and native key, "
        "decoded-cell and1e8-per-tile/1e9-total work caps remain; advertised axes "
        "are not a joint throughput guarantee. Trusted actual GeoTrellis component "
        "evidence is separate from full Spark, production and Google numerical parity."
    ],
    "Image.rgbToHsv": [
        "Exactly three ordered scalar RGB input bands in[0,1]; bounded closed "
        "Float64 scalar graph returns hue,saturation,value. Real staged source "
        "precision, metadata, finite grid and whole-three-channel mask retained. "
        "Out-of-domain channels mask; grayscale hue and black saturation are0; "
        "ties use deterministic red/green/blue precedence. No implicit band-name "
        "reordering, unbound global grid or Google endpoint/dtype parity claim."
    ],
    "Image.hsvToRgb": [
        "Exactly three ordered scalar HSV channels in[0,1]; hue1 wraps to hue0. "
        "Closed Float64 scalar graph returns red,green,blue with staged inputs, "
        "shared channel mask and finite source/grid checks. Out-of-domain channels "
        "mask. Standard HSV conventions are local policy without a Google oracle."
    ],
    "Image.interpolate": [
        "First scalar input band only; equal-length finite literal x/y lists with "
        "strictly increasing x and finite positive Float64 interval widths. All "
        "four outside behaviors extrapolate,clamp,input,mask; omitted/null defaults "
        "to extrapolate. Explicit bounded scalar graph, unchanged50000-work/500-node "
        "caps; compound knot counts may exceed them. Preserves first-band name, "
        "source masks and metadata. No dynamic knots, arrays or Google rounding proof."
    ],
    "Image.polynomial": [
        "Every scalar input band, finite literal coefficients in ascending degree "
        "(constant first), evaluated by bounded Horner scalar graph. Preserves "
        "band order, source mask, staged casts, grid and image metadata. "
        "Constant polynomial still retains the real input validity. Unsupported "
        "dynamic/array coefficients reject; no Google dtype/rounding equivalence."
    ],
}

for _name in ("regexpRename", "slice", "cat", "float", "double"):
    SPECTRAL_PREPARATION_LIMITS["Image." + _name] = [
        "Bounded scalar/fixed-array band preparation with pinned exact API arguments. "
        "regexpRename uses RE2 and $n replacement references, first/all matches "
        "with unique valid resulting names; invalid syntax/collisions reject. "
        "slice uses finite integer half-open indices with documented local negative "
        "index and clamp policy. cat lowers through existing addBands collision "
        "suffixing, preserves first-image metadata and binds constants only after "
        "an actual source supplies a finite grid. float/double are real staged "
        "existing casts, including typed arrays, not new reinterpretation engines. "
        "Unchanged shared work/graph limits; precise per-operation scope in "
        "spectral-preparation.md. No Google naming/empty-boundary/dtype parity claim."
    ]

SPECTRAL_PREPARATION_LIMITS["Image.id"] = [
    "Reads exactly one actual local source item identity; no generated positional "
    "ID or fallback string. Derived images retain the established source lineage. "
    "Source-free or ambiguous source identity rejects; no Google asset path parity."
]
SPECTRAL_PREPARATION_LIMITS["Image.metadata"] = [
    "Actual numeric property on a concrete finite local raster source, including "
    "per-item ImageCollection map expansion. Double constant borrows real grid/"
    "footprint but has independently valid pixels, including source NoData. "
    "Default output name is the property name by local policy. Missing/null/"
    "nonnumeric/nonfinite metadata or abs(value)>2^53 rejects; integer range "
    "checked before conversion. No fabricated grid, provider request or Google parity."
]

for _name in ("arrayDimensions", "arrayDotProduct", "arrayPad"):
    SPECTRAL_PREPARATION_LIMITS["Image." + _name] = [
        "Fixed-shape typed raster arrays within rank8/64-total-cell and unchanged "
        "50000-work/500-node/1MB bounds. dimensions returns actual per-band rank "
        "(scalar0) under input validity. dotProduct accepts paired rank1 arrays, "
        "equal band counts or one-band broadcast, positional pairing, fresh matching "
        "scene/grid evidence, whole-input masks and real staged precision. pad "
        "appends finite values up to per-axis minimum lengths, never shrinks; "
        "padding preserves declared Float32/Double and whole-array validity and "
        "requires a concrete source grid when binding added cells. Same-shape "
        "array-band bundles only. Scalarize with arrayGet/arrayFlatten before "
        "raster export; direct array output remains unsupported. Dynamic ragged "
        "arrayMask, implicit reprojection/time broadcast and Google parity unverified."
    ]
