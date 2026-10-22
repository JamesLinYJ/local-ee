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
    "ImageCollection.reduce": ["Only implemented reducer families and local collection/data semantics are available. linearFit supports1..8 ordered two-band frames, complete rows and centered OLS. linearRegression supports numX=1 through-origin or numX=2 with proven numeric literal-one first predictor, numY=1..4,1..8 homogeneous frames. All inputs/responses share complete-case masks; n<=numX/rank-degenerate masks coefficients and RMS. Typed coefficient/residual array bands must be selected then scalarized; only parallelScale=1, shared work/500-node cap and Float32 callback limits. Max dimensions/frames are not jointly guaranteed; combined four-frame two-response output exceeds cap, individual response paths are verified. No raster E/Google acceptance."],
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
    "Image.toFloat": ["Uses the local adapter to cast raster cells to Float32; Float32 callback arithmetic is the supported path, not a claim of Google numerical parity."],
    "Image.toDouble": [
        "Uses the local adapter to cast raster cells to Float64. Bounded native temporal reducers support mean, median, min, max, sum, count, first, last, and sampleStdDev; general Float64 callback pixel arithmetic remains unsupported. Cast toFloat before callback arithmetic when Float32 precision is acceptable; Google parity is unverified."
    ],
    "reduce": ["Only the explicitly implemented reducer names and local semantics are available."],
    "Filter.notNull": ["Flat local metadata names only, at most 1000 properties under the shared compilation budget; missing/null fail while non-null falsey values pass. No Google comparison."],
    "Dictionary.get": ["Missing keys require an explicit non-null default; default null/omitted rejects. Existing null values remain null."],
    "Dictionary.values": ["Explicit empty keys returns []; absent/null keys selects natural sorted keys. Missing requested keys reject."],
    "List.sequence": ["Supports count/end equal spacing and count/step ranges; at most 10000 finite values. No Google numerical comparison."],
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
        "Bounded static Euclidean minimum-distance only, kNearest=1 and CLASSIFICATION. Training 1..1000 inline Features, explicit unique flat schema 1..8 numeric properties, complete finite inputs/exact integers <=2^53 and integer labels 0..63; subsampling=1, seed=0 only. Exact binary64-rational class means and squared distances are a local numeric policy; equal nearest distances explicitly reject instead of guessing a tie. Untrained schema returns null, trained schema retains input order. Feature classification copies original metadata, rejects output-name collisions, <=1000 features and shared 50000-step work. Training confusionMatrix resubstitutes real predictions with axes 0..max class including gaps, <=4096 cells. Direct/nested server-object JSON, Image.classify, remote sampling, other metrics/k/modes and other classifiers remain unsupported; no Google comparison or whole classification compatibility claim."
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
for operation in ("Image.toArray", "Image.arrayFlatten", "Image.arrayProject", "Image.arraySlice", "Image.arrayGet", "Image.arrayLength", "Image.arrayLengths", "Image.arrayTranspose", "Image.arrayReduce", "Image.matrixMultiply"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Fixed-shape single-array-band intermediate images only: rank <=8, <=64 elements/axis and <=64 total cells; shared 50000-step work and 500 graph-node limits. Scalar bands toArray have a common mask requiring every band valid; layout/reduction/arithmetic/matrix outputs preserve the whole-array mask. Static Array constants can provide coefficient arrays. No dynamic shapes, multiple array bands, scalar/broadcast coercion, empty axes or direct array raster export; use arrayFlatten/arrayGet for scalar output. Project requires ascending unique axes with dropped axes length 1; slice/get require constant coordinates; rank-zero flatten rejects. Reduce supports single-output sum/mean/min/max/count/median/sampleStdDev only, no fieldAxis; singleton sampleStdDev rejects. Existing Float32 callback limits apply and unsupported Float64 arithmetic rejects. Source-preserving synthetic graph numerical controls are not actual raster-engine or Google acceptance."
    ]
for operation in ("ConfusionMatrix", "ConfusionMatrix.array", "ConfusionMatrix.order", "ConfusionMatrix.accuracy", "ConfusionMatrix.kappa"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Static typed integer Array square matrices only, 0..64 classes, <=4096 cells and nonnegative total counts <=2^53 under shared 50000-step work. Explicit unique integral order labels within +/-2^53 are retained; [] is not a default-order alias. Accuracy/Kappa use exact integer intermediates and finite Float64 ratios; undefined denominators reject. Raw lists, floating count arrays, direct/nested ConfusionMatrix JSON, Feature property storage and unimplemented per-class metrics reject. If and Dictionary.get preserve the internal type. No Google comparison or classifier training claim."
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
