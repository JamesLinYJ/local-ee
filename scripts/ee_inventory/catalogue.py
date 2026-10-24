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
        "Physical output is Float64. Bounded native temporal reducers support mean, median, min, max, sum, count, first, last, and sampleStdDev; closed native Double core arithmetic is supported; arbitrary callbacks remain unsupported. No Google-service comparison.",
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
    "ImageCollection.reduce": ["Only implemented reducer families and local collection/data semantics are available. linearFit supports1..8 ordered two-band frames, complete rows and centered OLS. linearRegression supports numX=1 through-origin or numX=2 with proven numeric literal-one first predictor, numY=1..4,1..8 homogeneous frames. All inputs/responses share complete-case masks; n<=numX/rank-degenerate masks coefficients and RMS. Typed coefficient/residual array bands must be selected then scalarized; only parallelScale=1 and shared work/500-node caps. Float32 callback limits remain for other consumers; a separately verified three-observation Float64 through-origin coefficient and RMS graph uses the closed native scalar path; bounded immutable lineage caching removes repeated scans without relaxing work or grid checks. Deferred singleton labels preserve all numeric callbacks. Max dimensions/frames are not jointly guaranteed: four-frame two-response full coefficients and predictions fit; full RMS and all-field combinations exceed cap, individual response paths are verified. No raster E/Google acceptance."],
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
    "Image.toFloat": ["Real scalar or single fixed-shape raster-array per-cell Float32 casts, preserving layout/name/mask/metadata; subsequent toDouble cannot restore lost precision. Existing callbacks retain staged Float32 behavior. Conversion overflow can create Infinity, which a subsequent closed Double native arithmetic input rejects. No Google dtype/numerical equivalence claim."],
    "Image.toDouble": [
        "Real scalar or single fixed-shape raster-array per-cell Float64 casts; array rank<=8/cells<=64, preserving row-major layout, name, input whole-array mask and metadata. Nested toFloat boundaries actually round. Bounded native temporal statistics and closed Double core arithmetic are supported separately; other callbacks/array bundles remain restricted. Source-free global raster output and Google dtype equivalence are not established."
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
    "Reducer.linearRegression": ["Unweighted inline table/List rows have typed coefficients/RMS and null underdetermined outputs. Raster ImageCollection path supports numX=1 through-origin or numX=2 with proven literal-one first predictor, numY=1..4 and1..8 ordered homogeneous frames; joint complete-case rows, n>numX, and both output arrays masked on degeneracy. RMS uses residual sum squares/n; repeated observations preserve row weights. Binary NoData, parallelScale=1, shared work/graph limits. A three-observation Float64 through-origin coefficient graph has an independent Fraction sample-graph proof; its RMS branch also fits after bounded immutable lineage caching; grid validation remains uncached. Other Float32 callback limits remain; generic independent predictor systems, image/reduceRegion, fractional weights and Google acceptance remain unsupported."],
}

for operation in ("List.zip", "List.unzip", "List.flatten", "List.repeat", "List.reverse", "List.set", "List.swap"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Static List layout only, <=10000 top-level values and shared 50000-step work budget before loops/allocation. Zip/unzip truncate to the shortest input/inner list; empty outer unzip returns []. Flatten recursively traverses only Lists, preserves typed Array/Image/other atoms, depth<=96 and bounded total scans/output. Repeat count 0..10000; the pinned SDK omits required value for repeat(None,count), and this wire form rejects as missing an argument. Set/swap negative indices count from end with strict bounds and no clamping. Sources are not mutated; public depth/object/1MB budgets still apply. No Google comparison."
    ]
for operation in ("Classifier.minimumDistance", "Classifier.train", "Classifier.schema", "Classifier.setOutputMode", "Classifier.confusionMatrix", "FeatureCollection.classify"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Bounded static Euclidean, Manhattan and cosine spectral-angle minimum-distance, kNearest=1 and CLASSIFICATION. Training 1..1000 inline Features, resolved unique flat schema 1..8 numeric properties, complete finite inputs/exact integers <=2^53 and integer labels 0..63; subsampling=1, seed=0 only. Exact binary64-rational class means and Euclidean/L1 distances; cosine ranks signed dot/center-norm by exact cross-products without floating normalization or acos. Equal nearest distances and cosine zero-norm queries/centers reject at prediction. These are local numeric policies without Google parity. Untrained schema returns null, trained schema retains input order. Feature classification copies original metadata, rejects output-name collisions, <=1000 features and shared 50000-step work. Training confusionMatrix resubstitutes real predictions with axes 0..max class including gaps, <=4096 cells. Image.classify has its own bounded model/native-kernel contract. Direct/nested server-object JSON, remote sampling, Mahalanobis/k>1/other modes and other classifiers remain unsupported; no Google comparison or whole classification compatibility claim."
    ]
KNOWN_PARTIAL_LIMITS["Classifier.train"].append(
    "Also accepts the bounded local Image.sampleRegions table directly: train runs on actual sampled rows, requires explicit schema1..8/class property present in declared columns, and emits the same exact rational v1 model. Graph input must directly reference the audited sampler; dry-run retains only schema/source traces. Fixed training source/grid is independent of target map/export options. Dynamic confusionMatrix/FeatureCollection.classify and direct model JSON still reject. See Image.sampleRegions limits."
)
KNOWN_PARTIAL_LIMITS["Classifier.train"].append(
    "Omitted/null inputProperties resolves only declared inline FeatureCollection properties.band_order or validated Image.sample v2 source metadata. Exact declared order,1..8 unique flat UTF8 names<=256codepoints,noNUL/reserved fields. No row-key inference or automatic class-property exclusion; label remains an input when explicitly named by metadata. Explicit non-null inputs override metadata;[] rejects. sampleRegions v1 lacks band_order and still requires explicit inputs. Backend training specs remain explicit; no new engine algorithm or Google-default equality claim."
)
for operation in ("Element.get", "Element.set", "Element.setMulti", "Element.propertyNames", "Element.copyProperties"):
    KNOWN_PARTIAL_LIMITS.setdefault(operation, []).append(
        "Also supports bounded inline FeatureCollection root properties, finite JSON only; precharged shared50000 work,1000features,10000metadata properties,depth96 and1MB escaped JSON, compound budgets can reject smaller inputs. Immutable owned metadata copies; row-preserving randomColumn/filter/limit/map-to-Features and static minimumDistance classification preserve collection props including empty output. map-to-Images remains ImageSequence. copyProperties supports inline FC-to-FC only; mixed receivers/dynamic sampled mutations reject clearly. merge metadata conflict semantics not implemented. Pinned SDK GeoJSON FC constructor drops root properties; use serialized Element.set/setMulti. Node-looking root metadata stays opaque in the closed CSV graph."
    )
SMILE_RF_LIMIT = (
    "Actual pinned Apache-2.0 Smile1.5.3 RandomForest, not Spark MLlib. Six constructor parameters retained: "
    "trees1..256, mtry null or1..p, minLeaf1..1000, bagFraction(0,1], maxNodes null or2..1000, seed signed32. "
    "Runtime-only training from canonical inline numeric rows or audited sampleRegions/filter/unsorted-limit producers; "
    "resolved1..8 schema,2..1000rows,2..64 contiguous labels from0, exact-domain integers and finite training magnitude<=Double.MAX_VALUE/2. "
    "RF150000 object/copy/operation work, separate3MB cumulative wire scans and1e9 tree-row-feature-leaf bound may reduce effective row capacity; inherited table operations remain bounded at50000. "
    "Serial calling-thread RNG, stratified bagging with replacement at1 and without replacement below1, null maxNodes uses N with no hidden depth cap. "
    "CLASSIFICATION only; schema and setOutputMode supported. Image.classify uses a trusted opaque JVM model from an RF trainer, "
    "preserves actual Float32/Float64, masks/grid/time/metadata, singleton Int32 v; valid infinity rejects. "
    "Prediction uses checked1e9 pixels*keys*sum(actual tree depths). Dedicated locked optional SPI/dependency package, no runtime downloads or user Java deserialization. "
    "RF FeatureCollection.classify and resubstitution/validation matrices have a separate bounded runtime table contract; explain supports only the closed actual Smile diagnostic dictionary and JSON projections. Other modes remain unsupported. "
    "No Google Smile version, seed, sampling, dtype or numerical equivalence and no full Spark/sandbox/service/browser/deployment acceptance."
)
KNOWN_PARTIAL_LIMITS["Classifier.smileRandomForest"] = [SMILE_RF_LIMIT]
KNOWN_PARTIAL_LIMITS["Classifier.explain"] = [
    "Trained Smile1.5.3 RF only; actual importance (sum of tree Gini decreases), numberOfTrees and raw outOfBagErrorEstimate. "
    "No normalized importance, tree text or other classifiers. Raw OOB may be0 when no held-out votes exist; not independent validation accuracy or Google equivalence. "
    "Bounded typed dictionary get/keys/contains/values and compatible casts, <=64 selected keys preserving order/duplicates; only direct owned JSON result. "
    "No generic nesting, dynamic algebra, CSV/raster sink or compiler fitting. Exact trainer schema/tree count, direct producer and existing RF150000/3MB/output budgets revalidated. "
    "Official Python/JS graph parity, actual trusted JVM and an independent fixed-stump oracle are component evidence, not full Spark/service/browser/deployment/Google acceptance."
]
for operation in ("Classifier.train", "Classifier.schema", "Classifier.setOutputMode"):
    KNOWN_PARTIAL_LIMITS[operation].append(SMILE_RF_LIMIT)
KNOWN_PARTIAL_LIMITS["Image.classify"] = [
    "Trained static minimumDistance only: Euclidean/Manhattan/cosine, k=1 CLASSIFICATION, schema1..8 scalar bands selected by name and explicitly ordered. Extra bands and masks excluded. Version1 exact reduced rational centers (strings<=700 chars/2200 bits, finite binary64 magnitude), sorted integer labels0..63; API/engine/Scala validate independently. Real input Float32/Float64 retained without generic callback narrowing; output is one Int32 NoData band, default classification or explicit flat outputName, preserving source metadata/time/finite footprint. Selected NoData masks output; valid Infinity, unique-nearest ties and cosine zero queries reject; zero center rejects when encoding prediction. Shared50000-work/500-node/grid/key/cell limits plus67108864 pixel-class-band operations apply. S/C and independent sampled graph N plus actual standalone GeoTrellis tile-kernel controls only: full Spark cube, batch sandbox, HTTP/browser, deployed runtime, Google dtype/tie/numerical equivalence unverified. Bounded sampleRegions runtime models also compile through strict sampler/train producer references; their fixed training scene/grid stays independent of target map/export options. Dynamic feature classification/confusionMatrix, other classifiers/modes/k, arrays and unbound constant rasters unsupported. See reports/gee-python-wave24.json."
]
KNOWN_PARTIAL_LIMITS["Image.classify"].append(SMILE_RF_LIMIT)
KNOWN_PARTIAL_LIMITS["Image.remap"] = [
    "One bound scalar band, first by default or exact unique bandName. Equal-length finite scalar mappings0..256; int magnitude<=2^53, numeric duplicate keys including signed zero reject. Exact actual Float32/Float64 lookup, selected NoData never filled, unmatched mask or finite default including0; valid Infinity rejects. Only output band remapped, retaining properties/time/grid/source/footprint. Local physical Float64/NaN output; generic Float32 arithmetic needs explicit toFloat. Array-valued mappings/global constants reject. Work/graph/grid/key/decoded bounds plus67108864 pixel-key work; standalone tile controls do not establish full Spark/service/browser or Google dtype/numerical equivalence."
]
KNOWN_PARTIAL_LIMITS["Filter.expression"] = [
    "Bounded pure parser for flat ASCII fields, finite numeric/string/bool literals, > >= < <= == != ! && || and parentheses;4096chars/256tokens/16nesting/64predicate nodes and shared work budget. No eval/SQL/arithmetic/calls/attributes/chained comparisons/null literals. Produces existing filter IR and retains local null/three-valued rules without Google parity."
]
for operation in ("Collection.filter", "Collection.limit"):
    KNOWN_PARTIAL_LIMITS.setdefault(operation, []).append(
        "Also supports runtime sampled tables: normalized scalar/notNull/boolean predicates or unsorted count null/0..1000, at most16 order-preserving operations including randomColumn, spec<=16384 UTF8bytes, predicate64nodes/depth16. Current tracked columns/IDs/geometry retained; system:index resolves original Feature.id for predicates. Base sampler row/cell/byte limits apply before transforms. Revalidation, full nested copies, filtering/randomization and training retain shared50000 work. Sorting/arbitrary computed columns/scalar evaluation remain unsupported."
    )
for operation in ("Collection.filter", "Collection.limit"):
    KNOWN_PARTIAL_LIMITS[operation].append(
        "Also supports actual RF classified tables with direct trusted producer lineage, canonical ordered specs and sequential headers. Source sampled operations and post-classified operations share16/50000 caps; inherited work enters the separate RF150000 matrix budget. Real IDs, geometry and metadata preserved. See classified-tables.md; full Spark/browser/Google parity unverified."
    )
KNOWN_PARTIAL_LIMITS["Collection.randomColumn"] = [
    "Bounded inline and actual sampled FeatureCollections, all five API arguments. Default random/uniform/seed0/rowKeys[system:index]. Local sha256-rowkeys-v1 over ordered typed scalar values, signed64 seed; uniform Float64[0,1), normal Box-Muller mean0/sigma1. No Google RNG/value oracle. Explicit empty rowKeys gives a constant; equal tuples equal values; reordered rows retain values. Default key uses properties.system:index then actual Feature.id, never invents positional IDs. Missing/null/complex/nonfinite keys reject; strings<=4096codepoints, numericabs<=2^53, bool distinct. Output flat<=256chars, noNUL or reserved system:index/.geo; overwrite keeps position, new columns precede.geo. <=64unique rowKeys,16operations,256columns,1000rows,50000cells,1MB JSON+CSV and unchanged shared50000 work/500nodes/16384operation-byte limits; compound caps can reduce effective size. Schema lineage and owned CSV result context preserve added/overwritten columns and declared band_order; pending never generates rows/RNG. Also accepts trusted RF classified tables through the same bounded filter/unsorted-limit/randomColumn chain, then errorMatrix/getInfo/CSV. Combined sampled/post operations<=16, cumulative50000 table work; actual IDs/geometry/root metadata and sequential headers retained. Arbitrary remote collections, ImageCollections, dynamic map/sort/retraining unsupported."
]
KNOWN_PARTIAL_LIMITS["Image.sample"] = [
    "Finite local spatial image with explicit planar WGS84 Point/MultiPoint/Polygon/MultiPolygon ROI or finite source footprint. Fixed source grid,1..64 scalar bands; polygon pixel centers covered including boundary, points half-open containing cell and duplicates once. All pixels by default; factor(0,1] or approximate numPixels0..1000 mutually exclusive, signed32 seed, local splitmix64-grid-v1 Bernoulli choices before dropNulls. Google RNG/selected-row parity unverified. numPixels population includes masked pixels; may exceed1000 rows and fails without truncation/reseeding. dropNulls=false preserves null selected values and missing finite-grid tiles. Optional actual WGS84 center geometries; band_order metadata; omitted/null classifier inputProperties may resolve its exact1..8 ordered names, while explicit inputs override metadata. Native source key/shape/duplicate checks and bounded global row/column ordering. Shared1000rows/256columns/50000cells/1MB JSON+CSV,10000coordinates,67108864 work and finite grid/key budgets. Existing actual-grid EPSG/meter restrictions,tileScale1 only. Full Spark/batch/service/browser/deployment/Google acceptance remains separate."
]
KNOWN_PARTIAL_LIMITS["Image.sampleRegions"] = [
    "Bounded inline planar WGS84 Point/MultiPoint/Polygon/MultiPolygon regions over one spatial image; 1..64 named scalar bands, <=1000 regions/10000 coordinates, <=1000 actual result rows/256 columns/50000 cells/1MB JSON and CSV. Default copied properties exclude system names; explicit[] copies none, schema collisions reject. Selected NoData drops rows, sampled infinity rejects. Points use half-open floor cell ownership; polygons select positive-area intersections; overlapping features keep independent rows and training weights. Optional snapped center geometries. These are local finite-grid policies without spherical/Google boundary parity. Native grid or explicit projected meter scale; projection without scale, tileScale!=1 and meter scale on geographic CRS reject. Runtime sample tables support getInfo/CSV and minimumDistance training with explicit schema1..8, integer classes0..63 and exact rational means under shared work/model/graph budgets. Samples/model specs are canonical JSON strings; dynamic refs must directly identify audited sampler/trainer nodes. Audited randomColumn/filter/unsorted-limit chains derive current columns and support declared MD/RF consumers; other classifiers and unsupported dynamic transforms reject. Native key/decoded-cell limits plus67108864 candidate-tile-pixel-region work apply; asset-grid service preflight is separate. Standalone actual tile kernel and trusted synthetic task/file controls are not full Spark/service/browser/deployment/Google acceptance."
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
        "Finite nonempty rank2 static matrices, required array parameter; real readonly factors. Compact QR uses Q(m,p)/R(p,n); compact SVD uses U(m,p)/S(p,p)/V(n,p) with A=U*S*V-transpose, p=min(m,n). LU remains square with L/U/P and P*A=L*U. Combined output cells<=10000 and dense m*n*p work are checked before allocation/factorization, shared50000 steps; previous square charges remain unchanged. QR/SVD compact shapes, signs and repeated-value bases are local NumPy/LAPACK choices without Google/EJML parity. LU first-maximum partial pivots preserve previous L columns; computed zero pivots and nonfinite elimination reject. Static support alone does not establish raster-engine execution."
    ]
for operation in ("Image.toArray", "Image.arrayFlatten", "Image.arrayProject", "Image.arraySlice", "Image.arrayGet", "Image.arrayLength", "Image.arrayLengths", "Image.arrayTranspose", "Image.arrayReduce", "Image.matrixMultiply"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "Fixed-shape single-array-band intermediate images only: rank <=8, <=64 elements/axis and <=64 total cells; shared 50000-step work and 500 graph-node limits. Scalar bands toArray have a common mask requiring every band valid; layout/reduction/arithmetic/matrix outputs preserve the whole-array mask. Static Array constants can provide coefficient arrays. No dynamic shapes, multiple array bands, scalar/broadcast coercion, empty axes or direct array raster export; use arrayFlatten/arrayGet for scalar output. Project requires ascending unique axes with dropped axes length 1; slice/get require constant coordinates; rank-zero flatten rejects. Reduce supports single-output sum/mean/min/max/count/median/sampleStdDev only, no fieldAxis; singleton sampleStdDev rejects. Fixed-shape Double add/subtract/multiply/divide can use the native scalar path and preserve whole-array masks; larger graphs still reject; bounded solve/inverse/pseudoinverse have a separate native matrix contract. Other Float32-only callbacks require explicit casts. Source-preserving synthetic graph numerical controls are not actual raster-engine or Google acceptance."
    ]
KNOWN_PARTIAL_LIMITS["Image.matrixSolve"] = [
    "Fixed single rank2 arrays with uniform explicit per-array toFloat/toDouble cells; either Double input promotes output, otherwise an explicit final Float32 cast retains input rounding. Existing stable literal full-column-rank solve keeps its bounded NumPy rcond=None scalar path. Actual raster-context solve also supports dynamic designs, wide and rank-deficient systems through one shared local_ee_matrix_values producer; matrixInverse and matrixPseudoInverse use the same native producer. Axes1..8, combined A+B input<=64 and output<=64 separately, compiler50000/graph500 unchanged. Fresh source/grid and matching temporal dimensions are mandatory; no fabricated constant global grid. Scaled Commons Math3.6.1 SVD uses its local numerical-rank cutoff; exact original-RHS BigDecimal dot products avoid normalization underflow, with exact constant-column centering only at full column rank. Zero-rank solve/pseudoinverse return zero; numerical-singular inverse, any missing input or nonfinite result masks the entire result matrix. Source Infinity rejects. Finite source-free constant inverse/pseudoinverse can fold; unrepresentable masked constant results reject. Native decoded/key/cell/work budgets are revalidated; shape/work admission is not a strict SVD iteration bound. Larger compositions may still exceed limits. Output masks/name/metadata/row-major order are retained. Whole-matrix nonfinite policy applies to the Float64 kernel; subsequent existing Float32 casts can overflow to Infinity, while source-free constant fold rejects nonfinite final casts. SDK compilation, independent synthetic graph and trusted GeoTrellis tile evidence do not establish full Spark, deployed/browser/export or Google numerical/rank/dtype parity."
]
for operation in ("Image.matrixInverse", "Image.matrixPseudoInverse"):
    KNOWN_PARTIAL_LIMITS[operation] = list(KNOWN_PARTIAL_LIMITS["Image.matrixSolve"])
for operation in ("Image.matrixQRDecomposition", "Image.matrixSingularValueDecomposition"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "One fixed rank2 raster array with uniform explicit Float32/Double cells; image parameter. "
        "Compact local factor layout p=min(m,n): QR Q(m,p)/R(p,n), SVD U(m,p)/S(p,p)/V(n,p), "
        "combined outputs64 and input64 cells, axes1..8. Rectangular/zero/rank-deficient matrices admitted. "
        "Named factors share one native producer, original metadata, casts and whole-input mask; select a "
        "factor before array algebra/export. Missing/nonfinite Float64 factors mask the whole group; valid "
        "Infinity rejects, terminal Float32 casts may overflow. All grid/time/key/work/compiler limits remain. "
        "Local compact shapes/signs/repeated-value bases are not Google parity; trusted components are not "
        "full Spark, physical export or deployment acceptance."
    ]

for operation in ("Image.matrixCholeskyDecomposition", "Image.matrixLUDecomposition"):
    KNOWN_PARTIAL_LIMITS[operation] = [
        "One fixed square array with uniform explicit toFloat/toDouble cells; parameter image. Cholesky returns L with L*L-transpose=A, exact symmetry and strictly positive computed pivots required; LU returns logical array bands L/U/P with P*A=L*U, first-maximum absolute partial pivots and unit L. Select a factor before ordinary array algebra/export; all factors share one actual native producer, original metadata and whole-input mask. Original-scale exact binary64 residual products with bounded-precision square root/division preserve extreme diagonal ranges without global A normalization. Nonpositive/zero pivots, missing input or nonfinite Float64 result mask every factor; valid source Infinity rejects. Axis1..8/input64 and combined output64 unchanged (LU at most4x4); shared compiler50000/process500/key/cell/work limits remain. Finite valid source-free constants may fold without inventing a grid; unrepresentable constants reject. Explicit final Float32 conversion can still overflow. Local pivot/rounding/domain policies, not Google equivalence. Standalone numerical components do not establish full Spark, browser, export or deployment acceptance."
    ]
KNOWN_PARTIAL_LIMITS["Image.matrixTranspose"] = [
    "Pinned same-signature alias of Image.arrayTranspose: swap any two constant valid axes in one fixed array, defaults0/1; preserve exact row-major cell identities, declared precision, whole mask/name/source/metadata, with no arithmetic or dtype narrowing. Shared rank8/cells64/compiler50000/graph500 bounds remain. Explicit null axes, invalid/boolean axes, scalar and multi-array bundles reject; select one factor first. SDK and synthetic graph controls do not establish full Spark or Google acceptance."
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
    "One fixed rank2 single column with1..8 rows and uniform explicit toFloat/toDouble cells. Produces nxn matrix retaining original diagonal and input whole-array mask/name/metadata/source; canonical +0 off-diagonal Double cells share a precharged source-bound abs(input0)*0 expression. Source Infinity rejects in native arithmetic, NaN masks. Output<=64 cells, compiler50000/graph500 unchanged; larger compositions may exceed limits. No full Spark or Google equivalence claim."
]
KNOWN_PARTIAL_LIMITS["Image.matrixTrace"] = [
    "One fixed rank2 square array1..8 with uniform explicit toFloat/toDouble cells; staged diagonal addition and scalar output retain input whole-array mask/name/metadata/source. No implicit dtype inference. Existing50000 work/64cells/500nodes retained, maximum dimensions not a guarantee all graph combinations fit. Local staged binary32/binary64 behavior has sample-graph proofs, not full Spark/Google parity."
]
KNOWN_PARTIAL_LIMITS["Image.matrixTrace"].append(
    "Known literal Float32 overflow rejects during constant folding; finite dynamic Float32 inputs can produce infinity in local sampled evaluation. Explicit staging does not establish identical constant/dynamic error handling, actual-engine or Google overflow semantics."
)
KNOWN_PARTIAL_LIMITS["Image.matrixDeterminant"] = [
    "One fixed rank2 square array1..4 with uniform explicit toFloat/toDouble cells. Precharged permutation products/parity and staged sums preserve full input mask and metadata. Polynomial expansion can cancel or overflow; not stable LU or Google parity. Existing50000 work/64cells/500graph nodes retained and larger public graphs may reject; direct IR construction alone is not raster execution."
]
KNOWN_PARTIAL_LIMITS["Image.matrixDeterminant"].append(
    "Known literal Float32 product overflow rejects during constant folding; dynamic finite Float32 matrix products can produce infinity or other nonfinite results in local sampling. This material numerical limitation is documented separately from mask preservation; no native/Google overflow acceptance."
)
KNOWN_PARTIAL_LIMITS["Array.argmax"] = [
    "Required array is a typed finite static Array within existing rank<=8/cells<=10000/exact integer domain<=2^53. Returns one integer coordinate per axis for the first row-major maximum, [] for rank0 and null for typed empty slices. No Float64 copy before comparison. Shared50000 work precharged before the scan; raw Lists, nonfinite/unsupported types and missing/unknown arguments reject. Direct empty constructors still require unsupported PixelType. No Google comparison."
]
KNOWN_PARTIAL_LIMITS["Image.arrayArgmax"] = [
    "Required image is one fixed rank1..8 RasterArrayImage with every cell uniformly explicit top-level toFloat/toDouble, axes/cells<=64. Actual strict-greater comparisons and conditional coordinate selection retain the first row-major maximum, returning shape(rank,) under the entire input mask including nonwinning missing cells, with original name/image/source. Local coordinate values are explicit Float32 integers; Google Integer result dtype and rounding equivalence are unverified. Rank0/uncast/mixed-topcast/scalar/multiple array bands and missing/unknown arguments reject. Shared50000 work precharged before Pixel/output construction;500 graph cap unchanged. No variable arrays, raster-engine or Google acceptance."
]
KNOWN_PARTIAL_LIMITS["Image.arrayAccum"] = [
    "One fixed single-array rank1..8 image with uniform explicit toFloat/toDouble cells. Existing axis, optional/null SUM default or finite SUM/MIN/MAX only; actual staged row-major prefixes with input whole-array mask/name/metadata/source and no row deletion. Invalid axis/reducer, uncast/mixed cells, unknown arguments and budget excess reject. Compiler50000/64cells/500nodes unchanged, shapes not jointly guaranteed with full graph expansion. Float32 behavior preserved; Double sample-graph proof is distinct from full native array/Spark/Google acceptance."
]
KNOWN_PARTIAL_LIMITS["Image.matrixFnorm"] = [
    "One fixed nonempty rank2 array with uniform explicit toFloat/toDouble cells. Real staged scaled Frobenius arithmetic normalizes by maximum absolute input, handles zero scale via local divide-by-zero0, preserves input whole-array mask and metadata. Finite source inputs only for native Double arithmetic; result overflow masks. Extreme/subnormal and nested-cast sample-graph controls verified. Precharged50000 work/64cells/500graph nodes unchanged; larger graph compositions can reject. No full Spark/Google dtype or ULP parity."
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
    "One fixed rank1..8 array with uniform explicit top-level toFloat/toDouble value and key cells independently, preserving each declared precision; same-rank keys identify one matching non-singleton axis with other dimensions singleton. Stable strict-gt adjacent compare-exchange moves full slices together, preserves input name/metadata/source fallback and conjunction of all payload/key validity. Default/null keys sort values, ambiguous keys/uncast/mixed-topcast/scalar/bundles reject. Work is precharged before quadratic DAG construction;64 cells/shared50000 work/500 graph nodes retained. Float32 key quantization can change ties; no Google tie/dtype or actual raster-engine acceptance."
]
KNOWN_PARTIAL_LIMITS["Image.where"] = [
    "Finite named scalar bands and broadcast test/value bands only. Double payloads use a closed native ternary where_select operation without payload callbacks, preserving nested Float32 rounding, signed zero and selected values. Missing test/value retains input; masked input stays masked. Fresh common-grid proof for distinct observations and rejection of explicit same-item asset-grid conflicts; no implicit spatial/time broadcasting. Source-free wire constants may be any finite binary64 value; raw integer constants retain +/-2^53 exactness. Work50000/graph500 unchanged, full Spark/browser/Google acceptance not established."
]
KNOWN_PARTIAL_LIMITS["Collection.errorMatrix"] = [
    "Inline FeatureCollection <=1000 complete finite integer actual/predicted labels and flat property names only. Missing/null and invalid label types reject; explicitly filter notNull first when desired. Default order spans 0..max label, at most 64 classes; explicit unique order counts only pairs whose two labels match it, including sparse/negative orders, and [] returns a typed 0x0 matrix. Empty collections need an explicit order. Shared work/cell limits apply. No remote feature sampling, classifier training or Google acceptance."
]
RF_VALIDATION_LIMIT = (
    "Actual RF runtime FeatureCollection.classify for canonical inline or audited sampleRegions/filter/limit tables, "
    "0..1000 prediction rows, explicit trained1..8 schema, finite binary64/exact-domain integers, original logical headers/rows/IDs/geometry retained; output collisions/missing/null inputs reject. "
    "Training confusionMatrix predicts retained real training rows (resubstitution, not OOB). Runtime errorMatrix preserves actual rows/predicted columns and explicit unique order<=64; omitted order0..max, empty requires explicit order, missing/null and undefined denominators reject. "
    "All seven existing bounded confusion accessors return owned JSON getInfo tasks; classified tables also support CSV. "
    "Opaque models/matrices have strict direct consumers; dry-run carries only schemas/traces. Existing50000 compiler,500nodes/table-operation caps plus separate per-process RF150000 object/3MB cumulative-wire and actual-depth prediction budgets apply. "
    "Classified tables support filter, unsorted limit and randomColumn through direct trusted operation producers, then errorMatrix/getInfo/CSV; combined sampled/post16 operations and cumulative50000 table work remain. Weak64 identity attestations avoid quadratic schema rescans, never cache rows/models/tracers, charge bookkeeping/header copies and fully revalidate misses. Other modes/classifiers, arbitrary dynamic scalar/array algebra and nested dynamic containers unsupported. Existing local metric shape/axis policies are not Google-verified; no full Spark/browser/deployment or same-data Google claim."
)
for operation in ("Classifier.smileRandomForest", "Classifier.confusionMatrix", "FeatureCollection.classify",
                  "Collection.errorMatrix", "ConfusionMatrix.array", "ConfusionMatrix.order",
                  "ConfusionMatrix.accuracy", "ConfusionMatrix.kappa", "ConfusionMatrix.consumersAccuracy",
                  "ConfusionMatrix.producersAccuracy", "ConfusionMatrix.fscore"):
    KNOWN_PARTIAL_LIMITS.setdefault(operation, []).append(RF_VALIDATION_LIMIT)
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


# Batch static families keep their per-name evidence limits in one cohesive table.
from .static_families import STATIC_FAMILY_LIMITS
from .table_families import TABLE_FAMILY_LIMITS

KNOWN_PARTIAL_LIMITS.update(STATIC_FAMILY_LIMITS)
KNOWN_PARTIAL_LIMITS.update(TABLE_FAMILY_LIMITS)

from .feature_preparation import FEATURE_PREPARATION_LIMITS

KNOWN_PARTIAL_LIMITS.update(FEATURE_PREPARATION_LIMITS)

from .pixel_numeric_families import PIXEL_NUMERIC_LIMITS

KNOWN_PARTIAL_LIMITS.update(PIXEL_NUMERIC_LIMITS)

from .integer_images import INTEGER_IMAGE_LIMITS

KNOWN_PARTIAL_LIMITS.update(INTEGER_IMAGE_LIMITS)

from .float64_images import FLOAT64_IMAGE_LIMITS

for operation, limits in FLOAT64_IMAGE_LIMITS.items():
    KNOWN_PARTIAL_LIMITS.setdefault(operation, []).extend(limits)
