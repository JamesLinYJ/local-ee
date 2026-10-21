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
    "ImageCollection.reduce": ["Only implemented reducer families and local collection/data semantics are available."],
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
    "Filter.maxDifference": ["Finite numeric flat-field/value operands, inclusive absolute difference; missing/null does not match. A direct filter can provide a numeric join measure; compound measured conditions and spatial distances reject."],
    "Collection.reduceColumns": ["Static inline FeatureCollection linearFit/linearRegression only, <=1000 rows and <=32 flat selected inputs under shared compilation budgets; nonempty weights and image/raster reduction reject."],
    "Reducer.linearFit": ["Unweighted inline table reduceColumns only, finite metadata rows, full-rank two-column design; null/insufficient/degenerate cases covered. No raster engine or Google acceptance."],
    "Reducer.linearRegression": ["Unweighted inline table reduceColumns only; typed coefficient matrix and per-response residual RMS; n<=numX/rank-deficient outputs are null. No ImageCollection/raster regression or Google acceptance."],
}

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
for operation in ("Join.simple", "Join.inverted", "Join.saveFirst", "Join.saveAll", "Join.saveBest", "Join.apply"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Bounded local ImageCollections and flat finite scalar metadata conditions only; at most 1000 frames and shared compilation work budget. A single direct numeric maxDifference supplies measures for saveBest/saveFirst/saveAll; inclusive threshold and local stable order/ties. Vector/spatial/compound measured joins, nested selectors and inner unsupported; synthetic graph controls do not establish native-engine or Google equivalence."
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
