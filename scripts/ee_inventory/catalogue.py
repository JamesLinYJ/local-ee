"""Curated partial limits and official-client helper lowerings.

These declarations do not establish complete API support.
"""

KNOWN_PARTIAL_LIMITS: dict[str, list[str]] = {
    "ImageCollection.load": ["A non-null versioned collection load is rejected."],
    "Image.load": ["Image version values other than the unversioned sentinel are rejected."],
    "Collection.map": ["dropNulls=true routes through finite per-image evaluation and remains subject to the 1000-frame local cap."],
    "Image.updateMask": ["Binary masks only; fractional masks and opacity semantics are not supported."],
    "Image.mask": ["The getter path is declared; the mask setter path is rejected."],
    "Image.unmask": [
        "Requires bounded aligned local grids and identical observation instants; defaults to valid zero and retains the input footprint. Global constants with sameFootprint=false, implicit time/grid broadcasting, and non-finite or out-of-range Float64 values reject.",
        "Physical output is Float64. Bounded native temporal reducers support mean, median, min, max, sum, count, first, last, and sampleStdDev; general Float64 callback arithmetic remains unsupported. No Google-service comparison.",
    ],
    "Image.constant": [
        "Finite numeric scalar literals and supported finite scalar arithmetic can be bound to a concrete destination raster when used through addBands, including per-observation date().millis() values. The scalar must remain within the exact Float64 range (absolute value <= 2^53). Standalone/global constant grids, projection queries, implicit broadcasting, arrays and arbitrary constant-image semantics remain unsupported; exact Google boundary-grid equivalence is unverified."
    ],
    "Image.addBands": [
        "Constant bands are supported only when bound to a destination with a finite local raster grid; the output uses that grid and footprint with an independent valid-pixel mask. Per-observation date constants preserve the source observation identity. Unbound/global constants, explicit constant source footprints, arbitrary projection behavior and cross-grid semantics are unsupported; exact Google parity is unverified."
    ],
    "Image.reduceRegion": ["crsTransform, bestEffort, and custom tileScale are rejected; local pixel/resource limits also apply."],
    "Projection": ["Projection transforms are rejected; supported local geometry/grid behavior is narrower than GEE."],
    "GeometryConstructors": ["Geodesic and non-EPSG:4326 geometry semantics are rejected by the local translator."],
    "ImageCollection.reduce": ["Only implemented reducer families and local collection/data semantics are available. linearFit supports1..8 ordered two-band frames, complete rows and centered OLS. linearRegression supports numX=1 through-origin or numX=2 with proven numeric literal-one first predictor, numY=1..4,1..8 homogeneous frames. All inputs/responses share complete-case masks; n<=numX/rank-degenerate masks coefficients and RMS. Typed coefficient/residual array bands must be selected then scalarized; only parallelScale=1, shared work/500-node cap and Float32 callback limits. Deferred singleton labels preserve all numeric callbacks. Max dimensions/frames are not jointly guaranteed: four-frame two-response full coefficients and predictions fit; full RMS and all-field combinations exceed cap, individual response paths are verified. No raster E/Google acceptance."],
    "ImageCollection.qualityMosaic": ["Requires a nonempty local collection, the requested quality band, and identical band names/order on every image. Invalid quality pixels are excluded and the selected scene's payload masks are retained; equal valid qualities currently select the last collection item. These semantics have not been compared with Google."],
    "Date.difference": ["Inputs must resolve to local millisecond scalars in the supported calendar range; only year, month, week, day, hour, minute, and second units are accepted. Year/month use average-duration constants as a local policy, and direct Google numerical parity is unverified."],
    "Date.getRelative": ["Inputs must resolve to local scalar dates in years 1..9999; only UTC is supported. Selected calendar pairs use ISO Monday-based week rules; week-of-month, same-unit, unsupported pairs, and unsupported containing units are rejected. Week boundaries are not Google-verified."],
    "Date.getFraction": ["Inputs must resolve to local scalar dates in years 1..9999; only UTC is supported. Week fractions use ISO Monday-based boundaries, with no direct Google boundary comparison."],
    "Number.bitCount": ["Static scalar inputs only; accepts exact signed-64-bit integers and counts the 64-bit two's-complement representation. Raster Image.bitCount is not implied."],
    "Number.bitwiseNot": ["Static scalar inputs only; accepts exact signed-64-bit integers and applies the smallest containing signed width among 8/16/32/64 bits. Raster Image.bitwiseNot is not implied."],
    "Number.bitwiseAnd": ["Static scalar inputs only; verified subset is nonnegative exact signed-64-bit integer operands. Negative operand coercion and raster Image.bitwiseAnd are not supported by this handler."],
    "Number.bitwiseOr": ["Static scalar inputs only; verified subset is nonnegative exact signed-64-bit integer operands. Negative operand coercion and raster Image.bitwiseOr are not supported by this handler."],
    "Number.bitwiseXor": ["Static scalar inputs only; verified subset is nonnegative exact signed-64-bit integer operands. Negative operand coercion and raster Image.bitwiseXor are not supported by this handler."],
    "Number.leftShift": ["Static scalar inputs only; shift counts must be 0..63, the left operand must be nonnegative, and the result must fit signed 64-bit. Raster Image.leftShift is not implied."],
    "Number.rightShift": ["Static scalar inputs only; accepts exact signed-64-bit operands and shift counts 0..63, with signed arithmetic right shift. Raster Image.rightShift is not implied."],
    "Image.toFloat": ["Uses the local adapter to cast scalar raster cells to Float32. A fixed-shape single array band casts every scalar cell and retains its whole-array mask, shape, name and metadata; no placeholder cast or bundle coercion. Float32 callback arithmetic is the supported path, not a claim of Google numerical parity."],
    "Image.toDouble": [
        "Uses the local adapter to cast scalar raster cells to Float64. Bounded native temporal reducers support mean, median, min, max, sum, count, first, last, and sampleStdDev; general Float64 callback pixel arithmetic and array-valued Image.toDouble remain unsupported. Cast toFloat before callback arithmetic when Float32 precision is acceptable; Google parity is unverified."
    ],
    "reduce": ["Only the explicitly implemented reducer names and local semantics are available."],
    "Filter.notNull": ["Flat local metadata names only, at most 1000 properties under the shared compilation budget; missing/null fail while non-null falsey values pass. No Google comparison."],
    "Dictionary.get": ["Missing keys require an explicit non-null default; default null/omitted rejects. Existing null values remain null."],
    "Dictionary.values": ["Explicit empty keys returns []; absent/null keys selects natural sorted keys. Missing requested keys reject."],
    "List.sequence": ["Supports count/end equal spacing and count/step ranges; at most 10000 finite values. No Google numerical comparison."],
    "Number.sin": ["Finite static numeric radians only; integer magnitude<=2^53, bool/nonfinite/invalid inputs reject. Precharged shared work; Float64 libm argument reduction is a local policy, not Google numerical parity."],
    "Number.cos": ["Finite static numeric radians only; integer magnitude<=2^53, bool/nonfinite/invalid inputs reject. Precharged shared work; Float64 libm argument reduction is a local policy, not Google numerical parity."],
    "Number.format": ["Bounded static %s/%d/%f and limited padding/sign flags only; exact integer %d, half-up rounding on Python shortest decimal spelling, no scientific/hex/grouping or Google rounding comparison."],
    "Filter.maxDifference": ["Finite numeric flat-field/value operands, inclusive absolute difference; missing/null does not match. A unique direct or And-nested filter provides a numeric join measure; multiple measures and measures under Or/Not reject when a measure is requested; spatial distances reject."],
    "Collection.reduceColumns": ["Static inline FeatureCollection linearFit/linearRegression only, <=1000 rows and <=32 flat selected inputs under shared compilation budgets; nonempty weights and image/raster reduction reject."],
    "Reducer.linearFit": ["Inline table reduceColumns and bounded two-input ImageCollection.reduce only. Raster path uses 1..8 ordered frames, x/y complete rows and centered OLS; fewer than 2 rows or zero x variance masks both scale/offset. Raster mask model is binary NoData, no fractional weighting or unweighted() adapter; parallelScale=1 only. Table null/degenerate cases remain covered. Independent sample-point numerical controls do not establish actual raster-engine or Google acceptance."],
    "Reducer.linearRegression": ["Unweighted inline table/List rows have typed coefficients/RMS and null underdetermined outputs. Raster ImageCollection path supports numX=1 through-origin or numX=2 with proven literal-one first predictor, numY=1..4 and1..8 ordered homogeneous frames; joint complete-case rows, n>numX, and both output arrays masked on degeneracy. RMS uses residual sum squares/n; repeated observations preserve row weights. Binary NoData, parallelScale=1, shared work/graph and Float32 callback limits; generic independent predictor systems, image/reduceRegion, fractional weights and Google acceptance remain unsupported."],
}

for operation in ("List.zip", "List.unzip", "List.flatten", "List.repeat", "List.reverse", "List.set", "List.swap"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Static List layout only, <=10000 top-level values and shared 50000-step work budget before loops/allocation. Zip/unzip truncate to the shortest input/inner list; empty outer unzip returns []. Flatten recursively traverses only Lists, preserves typed Array/Image/other atoms, depth<=96 and bounded total scans/output. Repeat count 0..10000; the pinned SDK omits required value for repeat(None,count), and this wire form rejects as missing an argument. Set/swap negative indices count from end with strict bounds and no clamping. Sources are not mutated; public depth/object/1MB budgets still apply. No Google comparison."
    ]
for operation in ("Classifier.minimumDistance", "Classifier.train", "Classifier.schema", "Classifier.setOutputMode", "Classifier.confusionMatrix", "FeatureCollection.classify"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Bounded static Euclidean, Manhattan and cosine spectral-angle minimum-distance, kNearest=1 and CLASSIFICATION. Training 1..1000 inline Features, explicit unique flat schema 1..8 numeric properties, complete finite inputs/exact integers <=2^53 and integer labels 0..63; subsampling=1, seed=0 only. Exact binary64-rational class means and Euclidean/L1 distances; cosine ranks signed dot/center-norm by exact cross-products without floating normalization or acos. Equal nearest distances and cosine zero-norm queries/centers reject at prediction. These are local numeric policies without Google parity. Untrained schema returns null, trained schema retains input order. Feature classification copies original metadata, rejects output-name collisions, <=1000 features and shared 50000-step work. Training confusionMatrix resubstitutes real predictions with axes 0..max class including gaps, <=4096 cells. Image.classify has its own bounded model/native-kernel contract. Direct/nested server-object JSON, remote sampling, Mahalanobis/k>1/other modes and other classifiers remain unsupported; no Google comparison or whole classification compatibility claim."
    ]
KNOWN_PARTIAL_LIMITS["Classifier.train"].append(
    "Also accepts the bounded local Image.sampleRegions table directly: train runs on actual sampled rows, requires explicit schema1..8/class property present in declared columns, and emits the same exact rational v1 model. Graph input must directly reference the audited sampler; dry-run retains only schema/source traces. Fixed training source/grid is independent of target map/export options. Dynamic confusionMatrix/FeatureCollection.classify and direct model JSON still reject. See Image.sampleRegions limits."
)
KNOWN_PARTIAL_LIMITS["Image.classify"] = [
    "Trained static minimumDistance only: Euclidean/Manhattan/cosine, k=1 CLASSIFICATION, schema1..8 scalar bands selected by name and explicitly ordered. Extra bands and masks excluded. Version1 exact reduced rational centers (strings<=700 chars/2200 bits, finite binary64 magnitude), sorted integer labels0..63; API/engine/Scala validate independently. Real input Float32/Float64 retained without generic callback narrowing; output is one Int32 NoData band, default classification or explicit flat outputName, preserving source metadata/time/finite footprint. Selected NoData masks output; valid Infinity, unique-nearest ties and cosine zero queries reject; zero center rejects when encoding prediction. Shared50000-work/500-node/grid/key/cell limits plus67108864 pixel-class-band operations apply. S/C and independent sampled graph N plus actual standalone GeoTrellis tile-kernel controls only: full Spark cube, batch sandbox, HTTP/browser, deployed runtime, Google dtype/tie/numerical equivalence unverified. Bounded sampleRegions runtime models also compile through strict sampler/train producer references; their fixed training scene/grid stays independent of target map/export options. Dynamic feature classification/confusionMatrix, other classifiers/modes/k, arrays and unbound constant rasters unsupported. See reports/gee-python-wave24.json."
]
KNOWN_PARTIAL_LIMITS["Image.sampleRegions"] = [
    "Bounded inline planar WGS84 Point/MultiPoint/Polygon/MultiPolygon regions over one spatial image; 1..64 named scalar bands, <=1000 regions/10000 coordinates, <=1000 actual result rows/256 columns/50000 cells/1MB JSON and CSV. Default copied properties exclude system names; explicit[] copies none, schema collisions reject. Selected NoData drops rows, sampled infinity rejects. Points use half-open floor cell ownership; polygons select positive-area intersections; overlapping features keep independent rows and training weights. Optional snapped center geometries. These are local finite-grid policies without spherical/Google boundary parity. Native grid or explicit projected meter scale; projection without scale, tileScale!=1 and meter scale on geographic CRS reject. Runtime sample tables support getInfo/CSV and minimumDistance training with explicit schema1..8, integer classes0..63 and exact rational means under shared work/model/graph budgets. Samples/model specs are canonical JSON strings; dynamic refs must directly identify audited sampler/trainer nodes. Dynamic downstream FeatureCollection operations/confusionMatrix and other classifiers reject. Native key/decoded-cell limits plus67108864 candidate-tile-pixel-region work apply; asset-grid service preflight is separate. Standalone actual tile kernel and trusted synthetic task/file controls are not full Spark/service/browser/deployment/Google acceptance."
]
KNOWN_PARTIAL_LIMITS["List.reduce"] = [
    "At most 1000 inline rows, shared work budget. Scalar count counts all non-null values; first/last return the first/last non-null typed value. Numeric sum/mean/min/max/median/sampleStdDev require finite real values, exact integers <=2^53, and skip nulls. Empty/all-null sum/count=0, other empty outputs and sample-SD below two values=null are documented local policies without Google comparison. Unweighted linearFit/linearRegression take ordered rows of exactly numX+numY inputs (<=32); null rows/fields exclude the row but other invalid fields still reject. Rank-deficient/n<=numX regression returns null outputs; typed coefficients/RMS are real computed values. Remote values, reducer combinations/weights and native raster execution are outside scope."
]
for operation in ("String", "String.cat", "String.length", "String.compareTo"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Static strings and finite numeric constructor values only; concatenation and comparisons share the 50000-step compilation budget, checked before concatenation allocation. Unicode uses Python code points and numeric conversion uses Python shortest spelling with an integral .0 removed; these local policies have no Google comparison."
    ]
for operation in ("Collection.merge", "Collection.iterate", "Collection.aggregate_array"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Inline FeatureCollection metadata operations are bounded to 1000 features and shared work limits; callbacks are serialized expressions. Merge requires explicit IDs and prefixes them with 1_/2_, rather than inventing automatic IDs. Remote/vector execution and unsupported geometry processing reject."
    ]

for operation in ("Array", "Array.get", "Array.length", "Array.toList", "Array.reshape", "Array.transpose", "Array.matrixTranspose", "Array.matrixMultiply", "Array.matrixInverse", "Array.matrixSolve", "Array.matrixPseudoInverse"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Static finite numeric arrays only, exact integer domain <=2^53, rank <=8, cells <=10000 and shared 50000-step work budget. Explicit PixelType, empty constructors, negative indices and raster array pixels are unsupported; matrix kernels require rank 2 and matrixSolve full column rank. Independent static numerical controls are not native raster-engine or Google acceptance."
    ]
for operation in ("Array.add", "Array.subtract", "Array.multiply", "Array.divide", "Array.abs", "Array.sqrt"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Static finite arrays only, <=10000 cells/rank 8 and shared 50000-step budget. Binary operands require identical shapes; scalar/broadcast coercion rejects. Divide by zero returns zero; negative square roots and nonfinite results reject. Integer add/subtract/multiply/abs preserve exact results up to 2^53. No raster or Google acceptance."
    ]
for operation in ("Array.reduce", "Array.accum"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Bounded nonempty static arrays only. Reduce supports single-output sum/mean/min/max/count/median/sampleStdDev, unique valid axes and retained singleton dimensions; fieldAxis and sampleStdDev counts below two reject. Accum supports sum/min/max only. Integer sums outside 2^53 reject. Float64 stable sum/mean/median control finite intermediate overflow; cumulative sums use ordered Float64 addition. No raster or Google comparison."
    ]
for operation in ("Array.slice", "Array.project", "Array.repeat", "Array.cat"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Static typed arrays, <=10000 cells/axis, rank 8 and shared 50000-step budget. Slice supports negative offsets and positive step; derived empty axes are retained. Project requires ascending unique retained axes and every dropped axis length exactly one. Repeat concatenates whole arrays, with copies 0..10000; cat requires 1..1000 typed Arrays with matching other dimensions. Raw nested-list cat coercion and unordered projection are unverified and reject. No raster/Google acceptance."
    ]
for operation in ("Array.eigen", "Array.matrixCholeskyDecomposition", "Array.matrixDeterminant", "Array.matrixTrace", "Array.matrixDiagonal", "Array.matrixToDiag", "Array.matrixFnorm"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Bounded nonempty rank-2 finite static arrays only; work and output preflight before allocation/factorization. Eigen and Cholesky require exact real symmetry, Cholesky positive definiteness; determinant requires square input. Eigen returns descending values with row eigenvectors, largest-component-positive signs and LAPACK basis for repeated values: these local presentation policies lack Google/EJML comparison. Diagonal is a column; toDiag requires a column; rectangular trace/diagonal supported. Independent static controls are not raster-engine acceptance."
    ]
for operation in ("Array.matrixQRDecomposition", "Array.matrixLUDecomposition", "Array.matrixSingularValueDecomposition"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Finite nonempty square static matrices only, required array parameter; real readonly factor Arrays in dictionaries: QR{Q,R}, LU{L,U,P} with P*A=L*U, SVD{U,S,V} with A=U*S*V-transpose. Combined output cells<=10000 and cubic work are checked before allocation/factorization, shared50000 steps. QR/SVD signs and repeated-value bases use NumPy/LAPACK policy; singular QR/SVD may reconstruct without a unique basis. LU first-maximum partial pivots preserve previous L columns; computed zero pivots and nonfinite elimination reject. Rectangular factor shapes and Google/EJML numerical behavior unverified; not raster factorization support."
    ]
for operation in ("Image.toArray", "Image.arrayFlatten", "Image.arrayProject", "Image.arraySlice", "Image.arrayGet", "Image.arrayLength", "Image.arrayLengths", "Image.arrayTranspose", "Image.arrayReduce", "Image.matrixMultiply"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Fixed-shape single-array-band intermediate images only: rank <=8, <=64 elements/axis and <=64 total cells; shared 50000-step work and 500 graph-node limits. Scalar bands toArray have a common mask requiring every band valid; layout/reduction/arithmetic/matrix outputs preserve the whole-array mask. Static Array constants can provide coefficient arrays. No dynamic shapes, multiple array bands, scalar/broadcast coercion, empty axes or direct array raster export; use arrayFlatten/arrayGet for scalar output. Project requires ascending unique axes with dropped axes length 1; slice/get require constant coordinates; rank-zero flatten rejects. Reduce supports single-output sum/mean/min/max/count/median/sampleStdDev only, no fieldAxis; singleton sampleStdDev rejects. Existing Float32 callback limits apply and unsupported Float64 arithmetic rejects. Source-preserving synthetic graph numerical controls are not actual raster-engine or Google acceptance."
    ]
KNOWN_PARTIAL_LIMITS["Image.matrixSolve"] = [
    "Fixed-shape single RasterArrayImage operands, explicit per-cell toFloat on both sides. Literal static full-column-rank design A(m,n),1<=m<=8,1<=n<=4,m>=n; raster B(m,k),1<=k<=4. NumPy Float32 lstsq(A,I,rcond=None) computes a real finite pseudoinverse after precharged work; output(n,k) is actual Float32 pixel arithmetic with the conjunction of both whole-array masks. Constant cast chains preserve each Float32/Double rounding step and share cached literal values. Total input cells<=64, shared50000 steps and500 process nodes retained. Missing/unknown arguments, dynamic A, non-Float32 cells, underdetermined/rank-deficient designs and nonfinite coefficients reject. Float32 rank cutoff, finite local grids and callback rounding are local policies, not Google/EJML parity; not general dynamic per-pixel matrixSolve or Float64 array support."
]
KNOWN_PARTIAL_LIMITS["ImageCollection.toArrayPerBand"] = [
    "Bounded ordered local Collection/ImageSequence of1..8 homogeneous scalar Images with1..8 unique same-name/same-order bands, axis=0, dropMasked=false only; <=64 total array cells. Each band concatenates actual cells in frame order and conjoins that band's masks across every frame, without cross-band contamination or dropping observations. Named array bundles retain finite source/footprint provenance and have no inherited scene date. Shared50000 work/500 process nodes remain. Dynamic dropMasked=true, nonzero axis, array-valued frames and schema mismatch reject; not ImageCollection.toArray's variable-row semantics, actual raster-engine or Google acceptance."
]
KNOWN_PARTIAL_LIMITS["Image.arrayReshape"] = [
    "Single fixed-shape RasterArrayImage, typed rank1 lengths array Image with a provably valid unmasked shape, and required dimensions1..8. Constant integer lengths1..64 with at most one inferred -1; product must equal input cells<=64. Reinterprets row-major cells without arithmetic or dtype conversion and preserves input name, mask and source metadata. Dynamic/masked lengths, zero/invalid dimensions, incompatible products, multiple inferred dimensions and unknown/missing arguments reject. Shared50000 work and500 process-node budgets remain; no general dynamic reshaping or native-engine/Google acceptance."
]
KNOWN_PARTIAL_LIMITS["Image.arrayCat"] = [
    "Single fixed-shape RasterArrayImage operands with equal rank1..8, matching non-concatenated dimensions, and a required existing axis. Concatenates actual row-major cells with the conjunction of both whole-array masks, left name/metadata and existing source fallback. Output axes/cells<=64, shared50000 work precharged before output construction and500 process-node cap unchanged. Scalar/multi-array-band operands, shape mismatch, missing/unknown arguments and dynamic layouts reject; no dtype conversion or raster-engine/Google equivalence claim."
]
KNOWN_PARTIAL_LIMITS["Image.arrayRepeat"] = [
    "Single fixed-shape RasterArrayImage, required existing axis and copies Image holding one provably valid finite positive integer constant scalar band. Repeats the entire axis block in row-major order, preserving source cells, dtype, name, metadata and whole-array mask. Dynamic, masked, spatially bounded or multiband copies, zero/negative/nonintegral counts and missing/unknown arguments reject. Output rank<=8/axes<=64/cells<=64, shared50000 precharged work and500 process-node cap retained. No variable-length arrays, actual raster-engine or Google acceptance."
]
KNOWN_PARTIAL_LIMITS["Image.matrixDiagonal"] = [
    "Required value is one fixed-shape rank2 RasterArrayImage, rectangular allowed within existing64-cell budget. Returns min(rows,columns)x1 column of actual diagonal Pixel references; no numeric conversion, full input mask and image name/metadata/source retained, including off-diagonal missingness. Work precharged before output construction. Scalar/multiband arrays, non-rank2 and missing/unknown arguments reject; no actual raster-engine/Google acceptance."
]
KNOWN_PARTIAL_LIMITS["Image.matrixToDiag"] = [
    "Required value is a fixed rank2 single-column RasterArrayImage,1..8 rows and explicit top-level toFloat on every input cell. Produces an nxn fixed matrix with original diagonal cells and real Float32 zero off-diagonal cells under the full input mask, retaining name/metadata/source. Output<=64 cells, shared50000 work precharged and500 graph cap unchanged. Rank1/row vectors, uncast/Double cells and missing/unknown arguments reject; not unrestricted type promotion or Google equivalence."
]
KNOWN_PARTIAL_LIMITS["Image.matrixTrace"] = [
    "Required value is one fixed Float32 square RasterArrayImage with1..8 rows. Actual diagonal addition explicitly rounds each stage to Float32 and returns a scalar Image under the entire input mask, including off-diagonal missing cells. Name/metadata/source retained, work precharged and500-node cap unchanged. Rectangular trace is not exposed in this local subset, non-Float32/rank/shape/unknown/missing inputs reject. Rounding/overflow/cancellation policy is local and has no Google comparison."
]
KNOWN_PARTIAL_LIMITS["Image.matrixTrace"].append(
    "Known literal Float32 overflow rejects during constant folding; finite dynamic Float32 inputs can produce infinity in local sampled evaluation. Explicit staging does not establish identical constant/dynamic error handling, actual-engine or Google overflow semantics."
)
KNOWN_PARTIAL_LIMITS["Image.matrixDeterminant"] = [
    "Required value is one fixed Float32 square RasterArrayImage with1..4 rows. Real signed determinant products and sums explicitly round each arithmetic stage to Float32, return a scalar Image with full input mask and original name/metadata/source; singular matrices may return zero. Shared50000 work charged before expression construction,64-cell and500-process caps retained; general4x4 raster outputs can still exceed500. This bounded polynomial kernel is not a numerically stable pivoted LU or Google-equivalent algorithm. Non-Float32/non-square/unsupported size/unknown/missing inputs reject."
]
KNOWN_PARTIAL_LIMITS["Image.matrixDeterminant"].append(
    "Known literal Float32 product overflow rejects during constant folding; dynamic finite Float32 matrix products can produce infinity or other nonfinite results in local sampling. This material numerical limitation is documented separately from mask preservation; no native/Google overflow acceptance."
)
KNOWN_PARTIAL_LIMITS["Array.argmax"] = [
    "Required array is a typed finite static Array within existing rank<=8/cells<=10000/exact integer domain<=2^53. Returns one integer coordinate per axis for the first row-major maximum, [] for rank0 and null for typed empty slices. No Float64 copy before comparison. Shared50000 work precharged before the scan; raw Lists, nonfinite/unsupported types and missing/unknown arguments reject. Direct empty constructors still require unsupported PixelType. No Google comparison."
]
KNOWN_PARTIAL_LIMITS["Image.arrayArgmax"] = [
    "Required image is one fixed rank1..8 RasterArrayImage with every cell explicitly top-level toFloat, axes/cells<=64. Actual strict-greater comparisons and conditional coordinate selection retain the first row-major maximum, returning shape(rank,) under the entire input mask including nonwinning missing cells, with original name/image/source. Local coordinate values are explicit Float32 integers; Google Integer result dtype and rounding equivalence are unverified. Rank0/Double/scalar/multiple array bands and missing/unknown arguments reject. Shared50000 work precharged before Pixel/output construction;500 graph cap unchanged. No variable arrays, raster-engine or Google acceptance."
]
KNOWN_PARTIAL_LIMITS["Image.arrayAccum"] = [
    "Required input/axis, optional reducer omitted or null defaults to sum. Single fixed RasterArrayImage with every cell explicitly top-level toFloat, rank1..8/axes and cells<=64; existing nonnegative integer axis only. Actual inclusive prefix sum/min/max in original row-major axis order, each new arithmetic stage explicitly Float32, retaining original name/image/full-array mask. Other reducers, unweighted modifiers, raw scalar/multiple array bands, invalid axes and missing/unknown arguments reject. Work precharged before output construction,50000 work and500 graph nodes retained. No skip-missing prefixes, dynamic shapes, generic Float64 or Google rounding comparison."
]
KNOWN_PARTIAL_LIMITS["Image.matrixFnorm"] = [
    "Required value is a single fixed rank2 RasterArrayImage with explicit top-level toFloat cells. Real scaled Frobenius norm: scale=max(abs(cells)), square and sum ratios to scale, sqrt then multiply by scale; existing zero-safe division makes an all-zero matrix return zero. Explicit Float32 arithmetic stages, original scalar band name/metadata/source and full-array mask retained. Avoids direct input-square overflow/underflow, but final Float32 range/cancellation remain local limitations: dynamic output may be nonfinite and known constant conversion overflow rejects. Precharged50000 work,64 cells and500 process-node cap retained; large dynamic matrices can exceed the cap. No generic Float64/Google-equivalent norm guarantee."
]
KNOWN_PARTIAL_LIMITS.setdefault("Image.select", []).append(
    "Typed fixed array Images and array-band bundles share exact-name/nonnegative-integer selection and optional bounded newNames. Single-array selection preserves actual cells, casts, mask, source and logical metadata. Empty/duplicate/regex selectors and mismatched or empty rename names reject in this subtype; ordinary scalar Image selection retains its existing separate semantics. Shared work is precharged before selected wrappers; this is a bounded overload, not full Image.select parameter compatibility."
)
for operation in ("Number.hypot", "Number.atan2"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Finite static Number operands left/right only, integers in exact Float64 domain<=2^53; bool/nonfinite/non-numeric/missing/unknown inputs reject. Work charged before real Float64 libm kernel and nonfinite result rejected. atan2 uses x=left,y=right according to the pinned SDK vector description and explicit Array right=y documentation, so the kernel is atan2(right,left). An official community harmonic tutorial uses the opposite call order; Google same-data orientation, signed-zero and last-bit parity remain unverified."
    ]
for operation in ("Array.hypot", "Array.atan2"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Typed static Array operands of exactly matching shape, rank<=8/cells<=10000, no broadcasting; precharge5*cells+1 before Float64 copies and actual NumPy hypot/atan2 kernel, shared50000 work. Finite readonly Float64 output, inputs unchanged. atan2 explicitly follows pinned SDK left=x,right=y and computes NumPy arctan2(right,left); the official community harmonic example conflicts, and Google numerical/axis parity is unverified. Direct empty constructors still reject; existing typed empty slices retain their shape."
    ]
KNOWN_PARTIAL_LIMITS["Image.hypot"] = [
    "Scalar raster bands only, normal single-band broadcast/natural-order pairing and longer-input labels, left metadata/source fallback and NoData propagation. Actual existing Pixel operations implement high=max(abs(x),abs(y)),low=min(abs(x),abs(y)),high*sqrt(1+(low/high)^2), with zero-safe division and explicit Float32 output. Precharged band/expression work, operands<=10000 bands and unchanged500-process cap; nonrepresentable direct constant Float32 output rejects. A dynamic norm exceeding Float32 range can become infinity in local sample evaluation, e.g. two finite3.3e38 inputs; actual native/Google overflow handling remains unverified. Explicit Float64 callbacks still require user-chosen toFloat. Staged local rounding differs from a fused hypot and has no Google bitwise proof. Raster arrays/bundles and Image.atan2 remain unsupported."
]
for operation in ("ConfusionMatrix", "ConfusionMatrix.array", "ConfusionMatrix.order", "ConfusionMatrix.accuracy", "ConfusionMatrix.kappa"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Static typed integer Array square matrices only, 0..64 classes, <=4096 cells and nonnegative total counts <=2^53 under shared 50000-step work. Explicit unique integral order labels within +/-2^53 are retained; [] is not a default-order alias. Accuracy/Kappa use exact integer intermediates and finite Float64 ratios; undefined denominators reject. Raw lists, floating count arrays, direct/nested ConfusionMatrix JSON and Feature property storage reject. If and Dictionary.get preserve the internal type. Per-class metrics are separately declared partial handlers. No Google comparison or classifier training claim."
    ]
for operation in ("ConfusionMatrix.consumersAccuracy", "ConfusionMatrix.producersAccuracy", "ConfusionMatrix.fscore"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Bounded typed static ConfusionMatrix counts and existing class/work limits only. Consumers uses diagonal/row sum and producers diagonal/column sum per pinned documentation. Fbeta uses actual-row recall and predicted-column precision as an explicit inference; positive finite beta with exact rational intermediates avoids overflow/underflow. Returns a local rank1 Float64 vector, not verified Google rank/dtype equivalence. Undefined class denominators and invalid/unknown inputs reject; original label order retained. Independent rational and trained inline-feature workflows are not raster-engine or Google acceptance."
    ]
KNOWN_PARTIAL_LIMITS["Array.sort"] = [
    "Typed static finite numeric Array, same-rank optional keys (null defaults to values); one key-selected axis matches the payload length while other key dimensions are singleton. Default matrices with multiple varying dimensions reject. Actual stable ascending permutation moves complete slices and retains dtype; ties and one-cell scalar identity are local policies, not Google verified. Unambiguous typed empty slices preserve shape. Rank8/cells10000/exact integer domain and precharged shared50000 work apply; valid shapes may exceed nlogn work budget."
]
KNOWN_PARTIAL_LIMITS["Image.arraySort"] = [
    "One fixed rank1..8 array with explicit top-level Float32 value and key cells; same-rank keys identify one matching non-singleton axis with other dimensions singleton. Stable strict-gt adjacent compare-exchange moves full slices together, preserves input name/metadata/source fallback and conjunction of all payload/key validity. Default/null keys sort values, ambiguous keys/Double/scalar/bundles reject. Work is precharged before quadratic DAG construction;64 cells/shared50000 work/500 graph nodes retained. Float32 key quantization can change ties; no Google tie/dtype or actual raster-engine acceptance."
]
KNOWN_PARTIAL_LIMITS["Collection.errorMatrix"] = [
    "Inline FeatureCollection <=1000 complete finite integer actual/predicted labels and flat property names only. Missing/null and invalid label types reject; explicitly filter notNull first when desired. Default order spans 0..max label, at most 64 classes; explicit unique order counts only pairs whose two labels match it, including sparse/negative orders, and [] returns a typed 0x0 matrix. Empty collections need an explicit order. Shared work/cell limits apply. No remote feature sampling, classifier training or Google acceptance."
]
for operation in ("Join.simple", "Join.inverted", "Join.saveFirst", "Join.saveAll", "Join.saveBest", "Join.inner", "Join.apply"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Bounded local ImageCollections and flat finite scalar metadata conditions only; at most 1000 frames and shared compilation work budget. A unique direct or conjunctive numeric maxDifference supplies measures; multiple measures and measures under Or/Not reject when requested. Inner emits <=1000 null-geometry Feature pairs retaining Images, with optional measure on the pair Feature and distinct keys. Inclusive threshold and local stable order/ties; vector/spatial joins and nested selectors unsupported. Synthetic graph controls do not establish native-engine or Google equivalence."
    ]


CLIENT_ALIAS_LOWERINGS = [
    {
        "client_api": "Filter.eq",
        "serialized_calls": ["Filter.equals"],
        "detail": "The convenience method maps eq to the canonical equals algorithm.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.neq",
        "serialized_calls": ["Filter.equals", "Filter.not"],
        "detail": "The convenience method builds eq and negates it.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.lt",
        "serialized_calls": ["Filter.lessThan"],
        "detail": "The convenience method maps lt to the canonical lessThan algorithm.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.gte",
        "serialized_calls": ["Filter.lessThan", "Filter.not"],
        "detail": "The convenience method builds lt and negates it.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.gt",
        "serialized_calls": ["Filter.greaterThan"],
        "detail": "The convenience method maps gt to the canonical greaterThan algorithm.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.lte",
        "serialized_calls": ["Filter.greaterThan", "Filter.not"],
        "detail": "The convenience method builds gt and negates it.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.inList",
        "serialized_calls": ["Filter.listContains"],
        "detail": "The official helper swaps field/value roles while constructing Filter.listContains; there is no distinct Filter.inList RPC signature.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.date",
        "serialized_calls": ["DateRange", "Filter.dateRangeContains"],
        "detail": "The helper builds a DateRange and then a dateRangeContains filter on system:time_start.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.bounds",
        "serialized_calls": ["Feature", "Filter.intersects"],
        "detail": "The helper constructs a Feature and an intersects filter for the all-geometry field.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Filter.metadata",
        "serialized_calls": ["Filter.equals", "Filter.not", "other Filter.* operators"],
        "detail": "The helper maps a metadata operator string to a Filter algorithm and can wrap it with Filter.not.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Collection.filterDate",
        "serialized_calls": ["DateRange", "Filter.dateRangeContains", "Collection.filter"],
        "detail": "The client helper creates a date filter and applies Collection.filter.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Collection.filterBounds",
        "serialized_calls": ["Feature", "Filter.intersects", "Collection.filter"],
        "detail": "The client helper creates a bounds filter and applies Collection.filter.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Collection.filterMetadata",
        "serialized_calls": ["Filter.*", "Collection.filter"],
        "detail": "The helper resolves the operator name to a Filter call and applies Collection.filter.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Collection.sort",
        "serialized_calls": ["Collection.limit"],
        "detail": "The pinned client calls Collection.limit with an undefined max and the property/order arguments; the backend must honor that exact serialized form.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "ImageCollection.first",
        "serialized_calls": ["Collection.first"],
        "detail": "The typed client method serializes through the generic Collection.first operation.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "ImageCollection.select",
        "serialized_calls": ["Collection.map", "Image.select"],
        "detail": "The client maps Image.select over the collection; it is not a separate API algorithm signature.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
    {
        "client_api": "Image.cat / Image.rgb",
        "serialized_calls": ["Image.constant", "Image.addBands", "Image.select"],
        "detail": "These client-side constructors lower to constant/addBands and optional select calls.",
        "source": "vendor/earthengine-js/earthengine.cjs",
    },
]
