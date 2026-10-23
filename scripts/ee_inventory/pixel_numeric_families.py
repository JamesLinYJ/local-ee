"""Explicit finite scope for native pixel math and static numeric helpers."""


PIXEL_NUMERIC_LIMITS = {}
for _operation in (
    "asin", "acos", "atan", "atan2", "sinh", "cosh", "tanh", "cbrt",
    "signum", "gamma", "digamma", "trigamma", "erf", "erfc", "erfInv", "erfcInv",
):
    PIXEL_NUMERIC_LIMITS["Image." + _operation] = [
        "Actual native Float32 tile math through a closed top-level SPI; ordered x[/y] "
        "input, singleton v output, original band pairing/names, grid/time and masks. "
        "Default untyped source/constant operands are visibly converted to Float32; "
        "precision outside Float32 is not preserved. Explicit Double arithmetic rejects "
        "until toFloat. Binary real operands require the same proven source lineage, "
        "not an implicit nearest-neighbor alignment. Constant subtrees need a real "
        "finite grid; no global constant raster. NaN/nonfinite inputs, invalid real domains, "
        "poles and nonfinite/Float32-overflow outputs become NaN. JVM Math/locked Commons "
        "Math3.6.1 with bounded digamma/trigamma reflection for negative nonpoles; atan2 "
        "uses SDK x,y and JVM atan2(y,x), retaining signed zero. Existing compiler50000/"
        "graph500/grid/key/decoded-cell and67108864 pixel-work limits. Trusted standalone "
        "tile proof is separate from unrun full Spark/service/browser/deployment/Google parity."
    ]

for _operation in (
    "bitCount", "bitwiseNot", "bitwise_not", "bitwiseAnd", "bitwise_and",
    "bitwiseOr", "bitwise_or", "bitwiseXor", "bitwise_xor",
    "leftShift", "left_shift", "rightShift", "right_shift",
):
    PIXEL_NUMERIC_LIMITS["Array." + _operation] = [
        "Finite nonempty static integer Arrays, rank8/cells10000/shared50000 work and1MB "
        "output; exact magnitude<=2^53. AND/OR/XOR require identical shapes and nonnegative "
        "operands; left shift nonnegative and nonoverflowing, signed right shift; counts0..63 "
        "are scalar or same shape. bitCount uses signed64 two's-complement; NOT signed "
        "complement. Results remain exact-domain owned readonly Arrays. Negative binary "
        "width policies, PixelTypes/raster implementation and Google dtype parity unverified."
    ]

for _operation in (
    "bitwise_not", "bitwise_and", "bitwise_or", "bitwise_xor", "left_shift", "right_shift",
):
    PIXEL_NUMERIC_LIMITS["Number." + _operation] = [
        "Pinned alias delegates to the existing audited canonical Number integer operation; "
        "signed64 integral domain, constrained nonnegative binary/left shift, signed right "
        "shift0..63, overflow rejects. No Image/raster algorithm or broader coercion implied."
    ]

for _operation in ("identity", "dotProduct", "pad"):
    PIXEL_NUMERIC_LIMITS["Array." + _operation] = [
        "Actual bounded static identity(size>=0, zero yields0x0), equal-length rank1 dot product, or "
        "trailing pad to at least each requested nonnegative axis length (no truncation). "
        "Finite exact-domain input, rank8/cells10000/shared50000 work/1MB output remain; "
        "integer dot products exact, floating products use rational accumulation and one "
        "Float64 conversion. Omitted/null pad=0, unchanged input and owned outputs. "
        "Explicit PixelTypes, general broadcasting and Google dtype/numeric parity unverified."
    ]

PIXEL_NUMERIC_LIMITS["Number.parse"] = [
    "Finite static ASCII string up to256 chars, decimal/fraction/exponent at radix10 "
    "(omitted/null default), complete signed integers at radix2..36; no prefixes or partial "
    "parse. Exact integer magnitude<=2^53 and finite Float64 output. Preserves negative "
    "zero; extreme underflow returns signed zero by local policy. Work is precharged "
    "before lexing/conversion. Shared50000 work/1MB output; Google formatting/parity unverified."
]


for _operation in ("fixed", "circle", "square", "rectangle", "plus", "cross", "diamond", "octagon"):
    PIXEL_NUMERIC_LIMITS["Kernel." + _operation] = [
        "Finite immutable pixel-unit masks at most33x33/1089 cells; fixed focus inside mask, "
        "offsets<=32; shape radii<=16. Shared50000 compilation budget. Meter units reject. "
        "Finite normalization/magnitude; negative source weights with normalization reject. "
        "Fractional boundaries and octagon policy lack Google parity. "
        "Opaque kernel values must enter an audited consumer, not public JSON or truthiness."
    ]

for _operation in ("gaussian", "laplacian4", "laplacian8", "sobel", "prewitt", "roberts", "rotate", "add"):
    PIXEL_NUMERIC_LIMITS["Kernel." + _operation] = [
        "Actual immutable finite pixel-unit coefficients, at most33x33/1089 cells and offsets<=32. "
        "Gaussian uses radius-inclusive ceil(radius) extent, finite-grid positive normalization "
        "or unnormalized continuous2D density; signed normalized kernels reject. "
        "Clockwise integer quarter-turn rotation preserves focus; add aligns focuses with finite "
        "Float64 addition. Shared50000 work; opaque values require an audited consumer. "
        "Meters reject; fractional radius, Roberts focus and numerical policies lack Google parity."
    ]

PIXEL_NUMERIC_LIMITS["Image.convolve"] = [
    "Real one-band native Float64 weighted spatial operation per logical band; exact binary64 "
    "products/sum with one nearest-even Float64 rounding, explicit final overflow rejection. "
    "Local complete-support policy: masked center or missing nonzero neighbor gives NoData; "
    "zero taps require no neighbor and all-zero kernel gives0 only on valid centers. "
    "Matrix uses center+offset without flipping. Preserve actual grid, observed keys/time; "
    "full finite input bounds precede export ROI/reprojection. Pixel offsets<=32, at most1089 "
    "coefficients; nonzero radius smaller than tile dimensions; source-free constants reject. "
    "Compiler50000/graph500 and native cell/key caps unchanged; per-tile1e8/total1e9 modeled "
    "work, including exact accumulator costs.3x3/256-square accepts, dense7x7 rejects. "
    "Standalone GeoTrellis and independent Fraction proof are separate from unrun full Spark, "
    "deployed browser/export, real data, performance and Google parity."
]

for _operation in ("focalMin", "focalMax", "focalMean", "focalMedian", "focalMode",
                   "focal_min", "focal_max", "focal_mean", "focal_median", "focal_mode"):
    PIXEL_NUMERIC_LIMITS["Image." + _operation] = [
        "Five unweighted scalar neighborhood reductions through bounded native Float64 halos. "
        "Pixel units,1..8 iterations,1089 offsets<=32; nonzero radius must be smaller than both tile dimensions. "
        "Missing keys are not synthesized; skipMasked=false fills only existing tiles. "
        "Smallest tied mode, local fractional shapes and focal center-mask policy; no Google parity. "
        "Positive support only; meters reject; compiler50000/graph500 caps unchanged. "
        "Export/aggregate regions and resolution cannot push through focal; full finite input item bounds loaded. "
        "Actual standalone kernel and GeoTrellis collection buffer evidence is separate from full Spark/deployment."
    ]

for _operation in ("euclidean", "manhattan", "chebyshev", "compass", "kirsch", "inverse"):
    PIXEL_NUMERIC_LIMITS["Kernel." + _operation] = [
        "Actual immutable finite pixel-unit distance/edge/reciprocal kernels, at most33x33/1089 "
        "cells and offsets<=32. Distance kernels retain full square ceil(radius) extent; "
        "positive normalization uses exact accumulation; signed normalization rejects. "
        "Inverse preserves zero coefficients/focus and rejects reciprocal overflow. "
        "Opaque kernels require an audited consumer; shared50000 work unchanged. "
        "Meters reject; fractional radius and reciprocal numerical policy lack Google parity."
    ]

PIXEL_NUMERIC_LIMITS["Reducer.unweighted"] = [
    "Opaque validated single-input numeric reducer plan accepted only by Image.reduceNeighborhood. "
    "Uses unit weights over nonzero kernel support and binary source validity. Shared-input "
    "combine/setOutputs must precede unweighted; no repeat/group/nested unweighted. "
    "Other reduction contexts, public JSON and truthiness reject; shared50000 work unchanged."
]

PIXEL_NUMERIC_LIMITS["Image.reduceNeighborhood"] = [
    "Native Float64 positive-weight sum/mean/population variance/stdDev; count/min/max use "
    "positive support; product/sampleVariance/sampleStdDev/median/default mode require uniform "
    "effective weights, mask or unweighted. Uniform weights normalize only for those operations, "
    "never sum. Binary source validity; kernel/mask/min weights are explicit. Single-input "
    "shared combine/setOutputs supports multiple named outputs per band; full descriptor "
    "validation includes dropped outputs. Zero support returns NoData and sample count<2 "
    "returns NoData. skipMasked=false fills only existing tiles; observed keys/time preserved. "
    "Exact dyadic sums and rational moments with final nearest-even Float64 rounding; final "
    "overflow fails. Source bounds precede output ROI/resampling; proven common grid required. "
    "Pixel offsets<=32,1089 taps; nonzero radius smaller than tile dimensions. Negative/empty "
    "kernels, meter units, optimization and histogram mode parameters reject. Compiler50000/"
    "graph500/JSON1MB and native key/cell/work caps unchanged. Standalone numerical checks "
    "do not establish full Spark/deployed workflow/private data or Google same-data parity."
]

for _operation in ("Terrain", "Terrain.products", "Terrain.slope", "Terrain.aspect", "Terrain.hillshade"):
    PIXEL_NUMERIC_LIMITS[_operation] = [
        "Finite actual elevation grid in metres; one band or named elevation. Four cardinal "
        "neighbors and center must be valid; borders/missing neighbors remain NoData. "
        "Actual source CRS/pixel centers transform to WGS84 ECEF and local east/north chord "
        "basis, independently of export CRS/scale. Degenerate, unresolved and polar metrics "
        "reject. Slope/aspect in degrees, flat aspect0; periodic finite illumination angles, "
        "Lambert hillshade rounded to0..255. Physical output remains Float64 NaN, including "
        "hillshade; no unsigned-byte storage claim. Products retains bands/properties and "
        "rejects name collisions; Terrain is its deprecated alias. Full input bounds, "
        "proven common grids and Float64 before temporal selection. Compiler50000/graph500/"
        "JSON1MB and native key/cell/work caps unchanged; one-pixel halo smaller than tile "
        "dimensions. No implicit height scaling, hillShadow or fillMinima. Metric, rounding "
        "and mask policies are local; versioned local cop-dem-glo-30/v1 DEM metadata is "
        "admitted, while Google DEM aliases and generic uploaded rasters are not. Full Spark/deployment/private "
        "data/Google parity unverified."
    ]

PIXEL_NUMERIC_LIMITS["Image.neighborhoodToBands"] = [
    "Per input band, emit each nonzero kernel cell in row-major order with focus-relative "
    "input_dx_dy names. Signed coefficients accepted, magnitudes ignored; each output "
    "copies its neighbor value and validity independently, without requiring a valid "
    "center. Reuses one-offset Float64 focal with skipMasked=false; absent keys never "
    "synthesized. Empty support, unbound constants and meter kernels reject.33x33/1089 "
    "cells, offsets<=32 and compiler50000/graph500/JSON1MB/native caps unchanged. "
    "Source grid/extent precedes export resampling/ROI. Naming/empty-image policies "
    "lack Google parity; trusted component evidence is separate from full deployed workflows."
]

PIXEL_NUMERIC_LIMITS["Image.distance"] = [
    "Nearest valid finite nonzero pixel per input band; original euclidean/manhattan/"
    "chebyshev Kernel provenance required, with pixel radius0..16, normalize=false and "
    "magnitude1. Missing/null, fixed, transformed and metre kernels reject. Radius "
    "eligibility uses exact binary64 radius; Euclidean compares squared integer offsets "
    "before final square root. Center targets yield0, absent targets yield NaN, and "
    "skipMasked controls center validity only. Physical output Float64; ordinary "
    "callback arithmetic requires explicit toFloat. Preserve observed keys/time, full "
    "source bounds and common-grid proof before output ROI/resampling. Compiler50000/"
    "graph500/JSON1MB caps remain; native halo must be smaller than the tile dimensions, "
    "decoded cells<=1e7/tile and1e8/aggregate, work<=1e8/tile and1e9/aggregate. "
    "fastDistanceTransform has a separate capped local contract. Trusted tile tests are not "
    "full Spark, deployment, private-data or Google same-data acceptance."
]

PIXEL_NUMERIC_LIMITS["Image.fastDistanceTransform"] = [
    "Finite bound raster inputs, each scalar band searched independently on its proven "
    "source grid. Missing/null parameters use neighborhood256, pixels and squared_euclidean; "
    "also supports manhattan/chebyshev, integral neighborhoods1..4096. Finite unmasked "
    "nonzero values are targets; every observed center receives Int32 distance capped at "
    "N*N for squared Euclidean or N otherwise, including no-target cases. These explicit "
    "local cutoff/mask-target/multiband/dtype policies lack Google same-data verification. "
    "Exact integer output<=2^24 supports ordinary Float32 sqrt/comparisons. Custom cropped "
    "Boolean fragments span multiple tile hops while preserving sparse keys and time; "
    "integer-envelope Euclidean and directional L1/Linf transforms use linear cell work. "
    "Full source extent precedes output ROI/resampling. Compiler50000/graph500/JSON1MB "
    "remain; native source<=100k keys, working cells<=1e7/tile and1e8/aggregate, "
    "work<=1e8/tile and1e9/aggregate include fragments and scratch. Specification acceptance "
    "does not guarantee a layout fits those budgets. Full Spark/service/deployment and "
    "private-data acceptance are separate."
]
