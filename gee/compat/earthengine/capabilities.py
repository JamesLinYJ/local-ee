"""Declared Earth Engine compiler handlers and their current caveats."""

from ...ee_dates import SUPPORTED_DATE_FUNCTIONS
from ...ee_integer import SUPPORTED_INTEGER_FUNCTIONS


# Handler inventory, not a claim that every overload or parameter is supported,
# nor that Google-service numerical equivalence has been established.
SUPPORTED_FUNCTIONS = frozenset({
    *("Geometry." + n for n in (
        "contains", "containedIn", "disjoint", "intersects", "intersection",
        "union", "difference", "symmetricDifference",
    )),
    *("Feature." + n for n in (
        "contains", "containedIn", "disjoint", "intersects", "intersection",
        "union", "difference", "symmetricDifference",
    )),
    "Image.linkCollection", "ImageCollection.combine",
    *("Image." + n for n in (
        "unmix", "rgbToHsv", "hsvToRgb", "interpolate", "polynomial",
        "regexpRename", "slice", "cat", "float", "double", "id", "metadata",
        "arrayDimensions", "arrayDotProduct", "arrayPad",
    )),
    *('Element.' + n for n in (
        'getNumber', 'getString', 'getArray', 'toDictionary', 'replaceProperties',
    )),
    *('Feature.' + n for n in ('id', 'select', 'setGeometry', 'toArray')),
    *('Geometry.' + n for n in (
        'type', 'coordinates', 'geometries', 'isUnbounded', 'edgesAreGeodesics', 'geodesic',
    )),
    *('GeometryConstructors.' + n for n in ('BBox', 'MultiGeometry', 'LinearRing')),
    *('Filter.' + n for n in (
        'eq', 'gt', 'gte', 'lt', 'lte', 'neq', 'notEquals', 'greaterThanOrEquals',
        'lessThanOrEquals', 'stringStartsWith', 'stringEndsWith', 'rangeContains',
        'dayOfYear', 'always', 'never', 'hasGeometry',
    )),
    "Image.matrixCholeskyDecomposition", "Image.matrixLUDecomposition", "Image.matrixTranspose",
    "Image.matrixQRDecomposition", "Image.matrixSingularValueDecomposition",
    "Terrain", "Terrain.products", "Terrain.slope", "Terrain.aspect", "Terrain.hillshade",
    "Image.neighborhoodToBands",
    "Image.convolve",
    "Image.distance", "Image.fastDistanceTransform",
    *("Kernel." + n for n in ("gaussian", "laplacian4", "laplacian8", "sobel", "prewitt", "roberts", "rotate", "add")),
    *("Kernel." + n for n in ("euclidean", "manhattan", "chebyshev", "compass", "kirsch", "inverse")),
    "Reducer.unweighted",
    *("Kernel." + n for n in ("fixed", "circle", "square", "rectangle", "plus", "cross", "diamond", "octagon")),
    "Image.reduceNeighborhood",
    *("Image." + n for n in ("focalMean", "focalMin", "focalMax", "focalMedian", "focalMode",
                             "focal_mean", "focal_min", "focal_max", "focal_median", "focal_mode")),
    *("Reducer." + n for n in (
        "percentile", "intervalMean", "mode", "skew", "kurtosis",
        "circularMean", "circularStddev", "circularVariance",
    )),
    *("Reducer." + n for n in (
        "pearsonsCorrelation", "spearmansCorrelation", "kendallsCorrelation", "sensSlope",
        "covariance", "centeredCovariance", "fixedHistogram", "fixed2DHistogram",
        "toList", "toCollection",
    )),
    *("Reducer." + n for n in (
        "minMax", "product", "stdDev", "variance", "sampleVariance",
        "countEvery", "countDistinct", "countDistinctNonNull", "firstNonNull",
        "lastNonNull", "countRuns", "frequencyHistogram", "allNonZero",
        "anyNonZero", "and", "or", "bitwiseAnd", "bitwiseOr", "repeat", "forEach",
    )),
    "Collection.flatten",
    *("DateRange." + n for n in (
        "contains", "end", "intersection", "intersects", "isEmpty",
        "isUnbounded", "start", "union", "unbounded",
    )),
    *("AggregateFeatureCollection." + n for n in (
        "first", "count", "count_distinct", "min", "max", "mean", "product",
        "sum", "sample_sd", "sample_var", "total_sd", "total_var", "stats", "histogram",
    )),
    "Reducer.combine", "Reducer.group", "Reducer.setOutputs", "Reducer.getOutputs",
    "Date.parse", "Date.update", "Date.getRange", "Date.unitRatio",
    "Array.bitsToArray", "Array.cut", "Array.mask", "Number.expression",
    "String.match", "String.replace", "String.split",
    "Collection.distinct", "Collection.remap", "Collection.fromColumns",
    # Literal names keep the source-only inventory independent of importing
    # scientific code or needing a configured runtime in a clean checkout.
    *("Number." + n for n in (
        "toByte", "toInt8", "toInt16", "toInt32", "toInt64", "toLong", "toShort",
        "toUint8", "toUint16", "toUint32", "toFloat", "toDouble", "byte", "int8",
        "int16", "int32", "int64", "long", "short", "uint8", "uint16", "uint32",
        "float", "double", "digamma", "trigamma", "erfInv", "erfcInv",
    )),
    *("Array." + n for n in (
        "toByte", "toInt", "toInt8", "toInt16", "toInt32", "toInt64", "toLong",
        "toShort", "toUint8", "toUint16", "toUint32", "toFloat", "toDouble",
        "byte", "int", "int8", "int16", "int32", "int64", "long", "short",
        "uint8", "uint16", "uint32", "float", "double", "digamma", "trigamma",
        "erfInv", "erfcInv",
    )),
    "List.filter", "Dictionary.select", "Dictionary.remove",
    *SUPPORTED_DATE_FUNCTIONS,
    *SUPPORTED_INTEGER_FUNCTIONS,
    *("Image." + n for n in (
        "byte", "toByte", "uint8", "toUint8", "int8", "toInt8",
        "short", "toShort", "int16", "toInt16", "int", "toInt",
        "int32", "toInt32", "uint16", "toUint16", "uint32", "toUint32",
        "long", "toLong", "int64", "toInt64", "bitwiseAnd", "bitwise_and",
        "bitwiseOr", "bitwise_or", "bitwiseXor", "bitwise_xor", "bitwiseNot",
        "bitwise_not", "bitCount", "leftShift", "left_shift", "rightShift",
        "right_shift",
    )),
    "ImageCollection.load", "Image.load", "Image.constant", "Image", "ImageCollection",
    "Collection.filter", "Collection.map", "Collection.limit", "Collection.sort", "Collection.size", "Collection.first", "Collection.randomColumn",
    "ImageCollection.mosaic", "ImageCollection.qualityMosaic", "Image.select", "Image.rename", "Image.bandNames", "Image.toFloat", "Image.toDouble",
    "Image.normalizedDifference", "Image.parseExpression", "Image.updateMask", "Image.mask", "Image.unmask", "Image.addBands", "Image.clip", "Image.reduceRegion",
    "Image.where", "Image.clamp", "Image.unitScale", "Image.reduce", "Image.date", "Image.geometry", "Collection.geometry", "Feature.geometry", "Image.sample", "Image.sampleRegions", "Image.remap",
    "Collection.toList", "AggregateFeatureCollection.array", "ImageCollection.reduce", "ImageCollection.toBands", "ImageCollection.toArrayPerBand", "ImageCollection.fromImages", "ImageCollection.merge", "If", "List.map", "List.iterate",
    "Collection.merge", "Collection.iterate", "Collection.reduceColumns", "Reducer.linearFit", "Reducer.linearRegression", "Number.format",
    "Element.get", "Image.get", "Element.propertyNames", "Element.set", "Element.setMulti", "Element.copyProperties", "Image.copyProperties",
    "Date", "DateRange", "Date.millis", "Date.advance", "Date.fromYMD", "Date.get", "Date.format", "Projection", "Projection.crs", "Feature", "Collection", "FeatureCollection",
    "Number", "String", "List", "Dictionary",
    "Array",
    "ConfusionMatrix", "ConfusionMatrix.array", "ConfusionMatrix.order",
    "ConfusionMatrix.accuracy", "ConfusionMatrix.kappa", "Collection.errorMatrix",
    "ConfusionMatrix.consumersAccuracy", "ConfusionMatrix.producersAccuracy", "ConfusionMatrix.fscore",
    # Wave34 actual raster math and bounded static helpers.
    "Image.asin", "Image.acos", "Image.atan", "Image.atan2",
    "Image.sinh", "Image.cosh", "Image.tanh", "Image.cbrt",
    "Image.signum", "Image.gamma", "Image.digamma", "Image.trigamma",
    "Image.erf", "Image.erfc", "Image.erfInv", "Image.erfcInv",
    "Array.bitCount", "Array.bitwiseNot", "Array.bitwise_not", "Array.bitwiseAnd",
    "Array.bitwise_and", "Array.bitwiseOr", "Array.bitwise_or", "Array.bitwiseXor",
    "Array.bitwise_xor", "Array.leftShift", "Array.left_shift", "Array.rightShift",
    "Array.right_shift", "Array.identity", "Array.dotProduct", "Array.pad",
    "Number.bitwise_not", "Number.bitwise_and", "Number.bitwise_or", "Number.bitwise_xor",
    "Number.left_shift", "Number.right_shift", "Number.parse",
    # Bulk finite static families; detailed restrictions below.
    "Number.acos", "Number.and", "Number.asin", "Number.atan",
    "Number.cbrt", "Number.clamp", "Number.cosh", "Number.erf",
    "Number.erfc", "Number.exp", "Number.first", "Number.firstNonZero",
    "Number.first_nonzero", "Number.gamma", "Number.log", "Number.log10",
    "Number.max", "Number.min", "Number.not", "Number.or",
    "Number.signum", "Number.sinh", "Number.tan", "Number.tanh",
    "Number.unitScale",
    "Array.acos", "Array.and", "Array.asin", "Array.atan",
    "Array.cbrt", "Array.ceil", "Array.cos", "Array.cosh",
    "Array.eq", "Array.erf", "Array.erfc", "Array.exp",
    "Array.first", "Array.firstNonZero", "Array.first_nonzero", "Array.floor",
    "Array.gamma", "Array.gt", "Array.gte", "Array.log",
    "Array.log10", "Array.lt", "Array.lte", "Array.max",
    "Array.min", "Array.mod", "Array.neq", "Array.not",
    "Array.or", "Array.pow", "Array.round", "Array.signum",
    "Array.sin", "Array.sinh", "Array.tan", "Array.tanh",
    "List.containsAll", "List.equals", "List.frequency", "List.getArray",
    "List.getGeometry", "List.getNumber", "List.getString", "List.indexOf",
    "List.indexOfSublist", "List.insert", "List.join", "List.lastIndexOfSubList",
    "List.remove", "List.removeAll", "List.replace", "List.replaceAll",
    "List.rotate", "List.splice",
    "Dictionary.combine", "Dictionary.fromLists", "Dictionary.getArray", "Dictionary.getGeometry",
    "Dictionary.getNumber", "Dictionary.getString", "Dictionary.map", "Dictionary.rename",
    "Dictionary.size", "Dictionary.toArray",
    "String.decodeJSON", "String.encodeJSON", "String.equals", "String.index",
    "String.rindex", "String.slice", "String.toLowerCase", "String.toUpperCase",
    "String.trim",
    "Classifier.minimumDistance", "Classifier.smileRandomForest", "Classifier.train", "Classifier.schema",
    "Classifier.setOutputMode", "Classifier.confusionMatrix", "Classifier.explain", "FeatureCollection.classify", "Image.classify",
    *("List." + n for n in ("zip", "unzip", "flatten", "repeat", "reverse", "set", "swap", "reduce")),
    *("Image." + n for n in ("toArray", "arrayFlatten", "arrayProject", "arraySlice",
        "arrayGet", "arrayLength", "arrayLengths", "arrayTranspose", "arrayReduce", "arrayReshape", "arrayCat", "arrayRepeat", "matrixMultiply", "matrixSolve", "matrixInverse", "matrixPseudoInverse",
        "matrixDiagonal", "matrixToDiag", "matrixTrace", "matrixDeterminant", "matrixFnorm", "arrayAccum", "arrayArgmax", "arraySort")),
    *("Array." + n for n in ("add", "subtract", "multiply", "divide", "abs", "sqrt", "hypot", "atan2",
        "reduce", "accum", "slice", "project", "repeat", "cat", "eigen", "argmax", "sort",
        "matrixCholeskyDecomposition", "matrixDeterminant", "matrixTrace",
        "matrixDiagonal", "matrixToDiag", "matrixFnorm", "matrixQRDecomposition",
        "matrixLUDecomposition", "matrixSingularValueDecomposition")),
    *("Array." + n for n in ("get", "length", "toList", "reshape", "transpose", "matrixTranspose", "matrixMultiply", "matrixInverse", "matrixSolve", "matrixPseudoInverse")),
    *("Join." + n for n in ("simple", "inverted", "saveFirst", "saveAll", "saveBest", "inner", "apply")),
    *("Filter." + n for n in ("and", "or", "not", "dateRangeContains", "intersects", "equals", "lessThan", "greaterThan", "stringContains", "inList", "listContains", "calendarRange", "notNull", "maxDifference", "expression")),
    *("reduce." + n for n in ("median", "mean", "min", "max", "sum", "count")),
    *("Reducer." + n for n in ("mean", "median", "min", "max", "sum", "count", "first", "last", "sampleStdDev")),
    *("Image." + n for n in ("add", "subtract", "multiply", "divide", "pow", "mod", "eq", "neq", "gt", "gte", "lt", "lte", "and", "or", "min", "max", "abs", "sqrt", "log", "log10", "exp", "round", "floor", "ceil", "sin", "cos", "tan", "hypot", "not")),
    *("GeometryConstructors." + n for n in ("Rectangle", "Point", "Polygon", "MultiPolygon", "LineString", "MultiLineString", "MultiPoint")),
    *("Number." + n for n in ("add", "subtract", "multiply", "divide", "pow", "mod", "eq", "neq", "gt", "gte", "lt", "lte", "abs", "round", "floor", "ceil", "sqrt", "sin", "cos", "hypot", "atan2", "toInt", "int")),
    *("String." + n for n in ("cat", "length", "compareTo")),
    *("List." + n for n in ("get", "length", "size", "contains", "add", "cat", "sequence", "slice", "distinct", "sort")),
    *("Dictionary." + n for n in ("get", "keys", "values", "contains", "set")),
}) - {"Collection.sort", "FeatureCollection", "Image", "Image.get", "ImageCollection", "List", "Number"}


def get_capabilities():
    return {
        "compiler_functions": sorted(SUPPORTED_FUNCTIONS),
        "level": "C",
        "numerical_equivalence_to_google_verified": False,
        "restrictions": [
            ("Image.unmix accepts1..8 actual aligned scalar source bands and1..8 finite endmembers, "
             "with independent sumToOne/nonNegative constraints and Float64 unmix_0.. outputs. "
             "A shared bounded native producer uses explicit local rank/conditioning/tie policies; "
             "whole-spectrum NoData masks outputs and source Infinity rejects. Original compiler, "
             "native work/key/cell caps remain; dimensions are not a joint throughput guarantee. "
             "Source-free constants reject; full Spark and Google numerical equivalence are unverified."),
            ("RGB/HSV require exactly3 caller-ordered scalar channels in[0,1], mask invalid ranges "
             "and use documented local hue/zero conventions. interpolate reads the first band, "
             "literal2..16 increasing x/y knots and extrapolate/clamp/input/mask behavior; "
             "polynomial applies1..64 ascending finite coefficients to every scalar band. "
             "Closed Float64 graphs preserve staged casts/masks/metadata; larger compositions "
             "can exceed unchanged50000 work/500 nodes, with no Google rounding claim."),
            ("regexpRename uses bounded RE2/$n with unique output names; slice has local "
             "half-open negative-index/clamping policy. cat preserves first-image metadata "
             "and binds leading constants only after an actual source supplies a finite grid. "
             "float/double reuse existing scalar/single-array/bundle casts. Image.id reads "
             "one actual item ID; metadata uses a finite numeric property within +/-2^53 "
             "as an independently valid Double constant on the real grid/footprint."),
            ("arrayDimensions reports actual per-band rank with whole-array validity (scalar0). "
             "arrayDotProduct requires rank1 vectors, positional pairing or single-band broadcast "
             "and fresh scene/grid agreement. arrayPad appends finite typed values, preserves "
             "whole-array masks and requires a finite single-scene source to bind added cells. "
             "Fixed rank8/64-total-cell/work/graph caps remain; scalarize before raster export. "
             "Ragged arrayMask and Google dtype/shape parity remain unverified."),
            ("Image QR/SVD accept one explicitly typed fixed rank-2 array with axes1..8. "
             "Compact local QR returns Q(m,p),R(p,n); SVD returns U(m,p),S(p,p),V(n,p), p=min(m,n). "
             "Combined factors fit64 cells and share one native producer; select before ordinary algebra. "
             "Rectangular, zero and rank-deficient inputs are admitted; missing/nonfinite factor outputs mask "
             "the entire group and valid source Infinity rejects. Original metadata/casts/grid/time and all "
             "work limits remain. Factor signs, repeated-singular subspaces and compact shapes have no Google "
             "comparison; final Float32 casts may overflow. Component checks are not full Spark acceptance."),
            ("Image matrix Cholesky/LU require one explicitly typed fixed square array. Cholesky returns L; "
             "LU returns L/U/P with P*A=L*U and first-maximum partial pivots. Select factors before array algebra. "
             "All factors share a single bounded producer, whole-input mask and original metadata. Cholesky uses "
             "exact symmetry and positive computed pivots; LU uses exact rational elimination and zero-pivot NoData. "
             "Input/output64 cells remain, so LU is at most4x4. Original-scale arithmetic retains tiny diagonals; "
             "finite source-free folds do not invent grids. Final Float32 casts can overflow. Existing graph/work/key/"
             "cell limits still apply; local numerical policies and component checks are not full Spark or Google acceptance."),
            ("Terrain products/slope/aspect/hillshade and the deprecated Terrain alias use "
             "actual elevation in metres and four valid cardinal neighbors plus center. "
             "The source CRS/grid defines a local WGS84 tangent-chord metric; export scale "
             "does not redefine terrain. Flat aspect0 and periodic illumination are local "
             "policies; hillshade0..255 remains Float64 with NaN, not byte storage. Products "
             "retains bands/properties and rejects collisions. Invalid metrics, unbound "
             "sources, hillShadow and fillMinima reject. Local cop-dem-glo-30 requires the "
             "versioned normalized DEM contract; Google DEM aliases remain unsupported. Native budgets and Google/full "
             "Spark/deployment evidence remain separate."),
            ("Image.neighborhoodToBands emits one band per nonzero pixel-kernel cell, "
             "ignores signed coefficient magnitude and uses focus-relative input_dx_dy "
             "names in row-major order. Each neighbor has its own validity; masked center "
             "does not invalidate all outputs. Empty support and meter kernels reject. "
             "It shares bounded Float64 focal execution and full source-grid boundaries; "
             "naming/empty-image policies lack Google parity."),
            ("Image.convolve applies finite pixel kernels with exact binary64 product accumulation "
             "and one Float64 rounding. Valid centers require all nonzero-weight neighbors; no edge "
             "renormalization. Zero kernels yield zero on valid centers. Gaussian, distance and seven edge kernels, "
             "quarter-turn rotation, reciprocal and focus-aligned addition preserve bounded33x33 coefficients. "
             "Meter kernels and signed normalization reject; fractional Gaussian footprint and mask "
             "policies are local, without Google parity. Native halo/work limits and full input extent "
             "boundaries remain; full Spark/deployment acceptance is separate."),
            ("Image.distance accepts only an explicit raw Euclidean/Manhattan/Chebyshev Kernel "
             "with validated constructor provenance, unnormalized unit-magnitude weights, and radius0..16 pixels. "
             "It searches only offsets within the selected metric radius (Euclidean uses dx²+dy²<=radius²), "
             "uses finite nonzero unmasked targets, emits Float64 distances or NoData when none is found, "
             "and preserves each scalar band's name, properties, source keys and time. skipMasked controls "
             "only whether an input-masked output center stays masked. Source precision is retained through "
             "eligible selection and masking before search; existing arithmetic/cast precision boundaries remain. "
             "Source grids must be proven and full source bounds are retained before output ROI. "
             "Missing/null kernels, fixed/transformed/normalized/scaled kernels, meter units and constants reject. "
             "Radius, grid, graph and existing compiler/native-work limits remain. Local behavior has no "
             "Google same-data parity or full Spark/deployment acceptance."),
            ("Image.fastDistanceTransform accepts pixel neighborhoods1..4096 and squared_euclidean, "
             "manhattan or chebyshev metrics. Finite nonzero unmasked inputs are targets; each scalar band "
             "keeps its name, properties, source keys and time. The local Int32 output is valid at masked centers "
             "and uses a finite cap (N² squared Euclidean, N for the other metrics), including when no target "
             "exists; outputs are <=2²⁴ and safe for exact integer inputs to pinned Float32 callbacks. "
             "Source values are widened before eligible selection/masking; existing arithmetic/cast precision "
             "boundaries remain. Full source bounds and common-grid proofs precede output ROI. Defaults are "
             "neighborhood256, pixels and squared_euclidean; other units reject. Capped/no-target, masked-target "
             "and multiband behavior are explicit local policies without Google same-data verification or full "
             "Spark/deployment acceptance."),
            ("Pixel-unit focalMin/Max/Mean/Median/Mode and aliases retain bounded Float64 halos per "
             "iteration. reduceNeighborhood additionally supports actual positive weighted sum/mean/"
             "population variance/stdDev, support count/min/max, unit-weight product/sample dispersion/"
             "median/mode, minMax and shared-input combine/setOutputs. inputWeight mask/kernel/min "
             "uses binary source validity only; no fractional mask claim. Reducer.unweighted is an "
             "opaque neighborhood-only plan, not a generic regional/table/array modifier. Named radii<=16, "
             "fixed offsets<=32; focal iterations1..8; original compiler/node and native work caps. "
             "Meter kernels and optimization strategies reject. Output region/resampling stays after the "
             "neighborhood; missing tiles are not synthesized. Local empty/tie/fractional-shape policies "
             "and full Spark/deployment/Google parity remain separately unverified."),
            ("Finite List/inline table distribution reducers add percentile/intervalMean/mode, "
             "population skew/excess kurtosis and circular statistics in radians. "
             "Type7 interpolation, inclusive percentile-value interval, smallest tied mode and "
             "undefined-direction policies are local, not Google-verified. Histogram approximation, "
             "weights, Array/dynamic table consumers reject; raster support is limited to default "
             "neighborhood mode described above. maxRaw limits actual valid static rows. "
             "Original1000 rows/50000 work/1MB output caps remain."),
            ("Finite table/List statistical reducers support correlations, Sen slope, typed-vector covariance, "
             "fixed 1D/2D histograms and collecting lists/features. No raster/dynamic table/weight support. "
             "Null, covariance denominator, Sen intercept and histogram grid policies are explicit; "
             "some default output keys and Google numerical equivalence remain unverified. "
             "Original 50000 work, 1000 rows, 32 inputs, 10000 Array cells and 1MB output limits apply."),
            ("Additional finite Reducer leaves compute minMax/product/population stdDev/variance/sampleVariance, "
             "counts/distinct/runs/non-null endpoints/frequency tables/logical and bitwise reductions. "
             "repeat and forEach operate on independent input blocks. Only static List/inline table consumers; "
             "unchanged tree/row/work/output caps, explicit null/type/naming policies and no Google numerical parity."),
            ("Nested finite FeatureCollections support constructor/map then flatten with owned rows, "
             "source order/actual IDs and outer metadata; child metadata is discarded under the local policy. "
             "Depth96/nodes10000/rows1000 and shared50000 work/1MB output remain. Mixed/Image/dynamic children reject."),
            ("AggregateFeatureCollection statistics read <=1000 inline features or real declared image metadata. "
             "Finite numeric kernels, homogeneous string min/max, explicit null/empty/first/histogram policies; "
             "no pixel or dynamic sampled-table aggregation, no Google numerical comparison."),
            ("Reducer combine/group/setOutputs/getOutputs support static List.reduce and inline reduceColumns "
             "with scalar/regression leaves, bounded immutable trees and owned outputs. "
             "Raster/Array/dynamic-table consumers and nonempty weights reject; grouping and null policies are local."),
            ("DateRange accessors/contains/intersection/intersects/union/empty/unbounded use half-open finite "
             "UTC endpoints within ±2^53 milliseconds. Unbounded is private typed IR without invented dates; "
             "its endpoints, direct public output and date filtering reject. Empty-set policies are not Google-verified."),
            ("Finite static Number/Array casts support explicit integer widths and Float32/Float64. "
             "Number integer fractions truncate; Array integers round nearest with half ties toward positive infinity; both clamp. "
             "Array non-byte rounding and negative ties are local inferences, not Google-verified semantics. "
             "Integer inputs/results remain exact<=2^53, including Int64; nonfinite Float32 overflow rejects. "
             "Static digamma/trigamma and inverse erf/erfc retain bounded work, finite real domains and explicit pole rejection. "
             "These methods do not cast raster Images or provide arbitrary dynamic scalar/array algebra."),
            ("List.filter accepts finite static values with item predicates or actual Feature properties, "
             "preflighting all Filter branches even on empty input. Dictionary.select/remove use bounded RE2 fullmatch "
             "selectors, including literal-looking keys; unsupported RE2 syntax rejects even on empty inputs. "
             "Owned copies, source key order, null policy and shared50000 work/1MB output limits remain; no Google comparison."),
            ("Image scientific math uses an actual closed Float32 native SPI for asin/acos/atan/atan2, "
             "hyperbolic/cbrt/signum/Gamma derivatives/erf and inverses. Default untyped source/constants "
             "are visibly converted to Float32 (16777217 becomes16777216); explicit Double inputs require "
             "explicit toFloat. Invalid/nonfinite/domain/Float32 overflow becomes NaN. Binary real inputs "
             "require matching proven source lineages; no implicit nearest-neighbor alignment. Deferred "
             "constant math binds finite raster grids, with bounded individual map expansion when needed. "
             "Existing grid/key/cell/compiler/graph caps plus67108864 pixel-work apply. Actual standalone "
             "tile proof is separate from full Spark/service/browser/deployment/Google acceptance."),
            ("Static Array bitwise operations and Number snake aliases use constrained integer policies; "
             "Array.identity includes0x0, dotProduct equal rank1 vectors, trailing pad without truncation. "
             "Number.parse is bounded256-char complete ASCII decimal/radix2..36 parsing. "
             "Rank8/cells10000/exact2^53/shared50000 work/1MB output unchanged; no general PixelTypes, "
             "raster bitwise or Google dtype/formatting/numerical parity."),
            ("Bulk static Number/Array/List/Dictionary/String families perform actual finite local computations, not registration-only stubs. "
             "Number integers remain exact<=2^53 and nonfinite/domain/overflow errors reject; Array rank<=8/cells<=10000, exact same shape/no broadcasting, owned readonly outputs. "
             "List structural equality retains typed-array and bool/number rules; dictionary map is finite static two-argument evaluation, null drops keys. "
             "String offsets/casing/trim use the existing Python Unicode codepoint policy; JSON primitives/list/dictionary only, duplicate/nonfinite/unsafe integers/deep/cyclic/opaque values reject. "
             "All retain shared50000 compiler work and1MB public output; maxima are not guaranteed in combination. "
             "Rotation direction, collision/formatting and numeric rounding policies are documented locally; no Google same-data/numerical/dtype parity or raster-engine acceptance is implied."),
            ("Classifier.smileRandomForest uses actual pinned Apache-2.0 Smile1.5.3 with all six constructor parameters, "
             "1..256 trees, mtry null or1..p, minLeaf1..1000, bagFraction(0,1], maxNodes null or2..1000 and signed32 seed. "
             "Static inline rows and actual sampleRegions tables train only in the trusted JVM; the compiler does not fit models. "
             "Resolved1..8 numeric schema from explicit inputProperties or declared band_order,2..1000 rows,2..64 contiguous class labels from0, training float magnitude<=Double.MAX_VALUE/2; "
             "RF150000 object/copy/operation work plus3MB cumulative wire scans and1e9 tree-row-feature-leaf bound can reduce effective row capacity; prior table operations still cap at50000. "
             "Serial calling-thread seed, actual Smile stratified bagging, null maxNodes uses nonbinding N, CLASSIFICATION only. "
             "Schema/setOutputMode, Image.classify, and bounded FeatureCollection.classify support inline rows or fixed sampleRegions tables; feature predictions remain lazy in the trusted runtime. "
             "RF training confusionMatrix is actual resubstitution; its supported accessors and errorMatrix over sampled/classified tables lower to bounded lazy matrix/value processes. "
             "Model refs must identify an RF trainer, no user Java bytes/URLs/paths. Opaque matrices feed only supported accessors and cannot be returned directly or nested in dynamic containers. "
             "Actual Float32/Float64 input, selected NoData masks, valid infinity rejects, Int32 v, grid/time retained. "
             "Prediction bound1e9 pixels*keys*sum(actual tree depths), and1e9 row*actual-depth-sum prediction work for feature tables. "
             "Optional pinned RF runtime package required; no runtime downloads. RandomColumn uses the local SHA-256 row-key algorithm for inline Features, lazy sampled tables and trusted RF classified tables; it is deterministic locally and is not Google's random oracle. "
             "RF classified tables support filter, unsorted limit and randomColumn then errorMatrix/getInfo/CSV; immutable base schema, sequential headers, real IDs/geometry/metadata and dry-run lineage are preserved. "
             "Combined sampled/post-classified operations cap at16 with cumulative50000 table work; map/sort/retraining remain unsupported. "
             "Classifier.explain exposes actual importance, numberOfTrees and raw Smile outOfBagErrorEstimate with bounded typed dictionary reads and direct owned JSON; "
             "tree text/model persistence, other modes, generic runtime Array/Number algebra and arbitrary dynamic containers reject; "
             "no Google version/RNG/bagging/dtype equivalence or full Spark/deployment acceptance."),
            ("Classifier.explain requires an actual trained Smile RF model. Importance is the sum of actual tree Gini decreases, not normalized percentages. "
             "The three-key dictionary supports get/keys/contains/values, typed Dictionary/Number/List casts and at most64 selected keys; order and duplicates are preserved. "
             "Raw Smile1.5.3 OOB error can be0 when no OOB votes exist; it is not held-out accuracy. JSON-only projections remain lazy; keys/contains may resolve statically. "
             "Untrained/other classifiers, tree text, math, generic nesting, CSV/raster sinks reject. Existing RF150000/3MB and output limits remain; no Google numerical parity."),
            ("Image.remap selects one scalar bound band (first by default), returns only remapped, and retains properties/time/grid/footprint. "
             "Equal-length finite scalar from/to lists0..256; integer magnitude<=2^53; duplicate numeric keys including signed zero reject. "
             "Exact actual Float32/Float64 lookup, selected NoData remains masked, unmatched values mask or use finite default including0; valid infinity rejects. "
             "Physical output Float64 with NaN NoData, not verified Google dtype; generic Float32 callbacks require explicit toFloat. "
             "Array-valued mappings and global constant rasters reject. Native67108864 pixel-key work plus existing grid/key/decoded/work/graph caps remain."),
            ("Filter.expression parses bounded comparisons > >= < <= == !=, !, &&, || and parentheses into existing Filter IR; "
             "ASCII flat identifiers, finite numeric/string/bool literals, <=4096 chars/256 tokens/16 nesting/64 predicate nodes. "
             "No eval, arithmetic, functions, attributes, chained comparisons or null literals. Existing three-valued ordered-null policy and null equality rejection remain, no Google parity. "
             "Sampled FeatureCollections support filter, unsorted limit (null or0..1000), and randomColumn in at most16 ordered operations; randomColumn uses strict row keys and adds/overwrites schema fields without changing IDs or geometry. "
             "System:index resolves the original generated Feature.id during predicates only. Runtime revalidation/copy/filter/training share50000 work; "
             "sampler output limits still apply before operations. Sort, dynamic maps/scalar results/confusion matrices remain unsupported."),
            ("Image.sampleRegions supports bounded inline Point/MultiPoint/Polygon/MultiPolygon regions over a single spatial image: "
             "1..64 named scalar bands, <=1000 regions/10000 coordinates, <=1000 output rows/256 columns/50000 cells/1MB JSON and CSV. "
             "Copied properties default to non-system names; explicit [] copies none. Selected NoData drops rows; infinity rejects. "
             "Points use half-open floor grid ownership and polygons positive-area cell intersection, preserving overlapping-feature weights; "
             "this local planar boundary policy is not Google-verified. Native grid or projected meter scale, tileScale=1, optional center geometry only. "
             "Sample CSV/getInfo and runtime minimumDistance/RF training, prediction and error-matrix inputs use actual samples, canonical JSON string specs and strict producer refs. "
             "Training needs explicit schema1..8, labels0..63 and existing exact-model/work limits. Dynamic downstream feature operations beyond filter, unsorted limit, and randomColumn, "
             "general projections and classifiers beyond the declared minimumDistance/Smile RF subsets reject. "
             "Standalone actual tile kernels and synthetic task/CSV controls are not full Spark batch, deployment, browser or Google acceptance"),
            ("Image.sample uses a finite explicit region or the image's finite local footprint and a fixed source grid; "
             "it returns actual pixel rows through the native sampler, with center-covered planar polygons and half-open point-cell ownership. "
             "Bounded factor/approximate-numPixels subsampling uses the versioned deterministic grid hash; selection precedes null dropping. "
             "dropNulls, center geometries, source band order, and the shared table/work/output limits are explicit. "
             "Projection requires explicit scale in a supported projected EPSG meter grid; tileScale must be1. "
             "Approximate numPixels may exceed the row cap and then fails; Google RNG/row parity and spherical boundaries are unverified. "
             "Omitted/null classifier inputProperties resolves the exact declared band_order; explicit inputs override it. The declared minimumDistance, Smile RF, sampled-table and RF validation consumers accept this producer"),
            ("Classifier.train supports omitted/null inputProperties only from declared collection band_order, never from first-row keys or arbitrary columns. "
             "Exact1..8 unique flat UTF8 names, original order and full classProperty inclusion if listed; explicit inputs override metadata, empty list rejects. "
             "Image.sample v2 metadata survives audited table ops; sampleRegions v1 still requires explicit inputProperties. "
             "Inline FeatureCollections support bounded Element get/set/setMulti/propertyNames and FC-to-FC copyProperties over finite root JSON metadata. "
             "Row-preserving randomColumn/filter/limit/map-to-Features retain owned properties; merge metadata semantics and sampled metadata mutation remain unsupported. "
             "Shared50000 work/1MB JSON/depth/object caps still apply; no Google same-data/default-output equivalence claim."),
            ("Export.table.toDrive supports regional CSV and bounded static inline FeatureCollection CSV "
             "through the existing isolated batch entry point, without a JVM for pure tables. "
             "Limits include 1000 rows, 256 columns, 50000 default cells, 1 MB UTF-8 input/output "
             "and existing serialized EE/graph caps. Selectors retain order; default index/property/geometry "
             "columns, null/JSON cell encoding and model-aware WGS84 validation are explicit local policies "
             "without Google CSV parity. Other table formats/cloud destinations/maxVertices/priority reject. "
             "Trusted synthetic service/writer tests are not deployed/native-process/browser acceptance"),
            "Array.sort and Image.arraySort use same-rank keys with one selected non-singleton axis and matching axis length; all other key dimensions are singleton. Stable ascending ties are a local policy without Google comparison. Static typed arrays retain dtype within rank8/cells10000/shared50000 work, including unambiguous typed empty arrays and local scalar identity. Raster sorting requires uniform explicit toFloat/toDouble cells independently for values and keys, preserves each declared dtype, coupled slices and full value/key masks; rank1..8/cells64/500 graph cap. No raster-engine or Google acceptance",
            "ConfusionMatrix consumersAccuracy uses diagonal/row totals and producersAccuracy diagonal/column totals per pinned descriptions. fscore uses actual-row recall/predicted-column precision as an explicit inference. All return local finite rank1 Float64 arrays; Google shape/dtype parity is unverified. Finite positive beta, exact rational intermediates, undefined denominator rejection and existing counts/class/work limits apply",
            "Array.argmax returns the first row-major maximum's coordinate list, [] for rank0 and null for typed empty slices, within existing finite exact-domain/static budgets. Image.arrayArgmax supports one fixed rank1..8 array with uniform explicit top-level toFloat/toDouble cells, comparing their declared precision and returning actual first-maximum coordinates under the full input mask. Raster coordinate values are locally Float32 integers, not verified Google Integer dtype equivalence; uncast/mixed-topcast/scalar/bundle inputs reject. Work is precharged and64-cell/50000-work/500-node limits remain. No raster-engine or Google acceptance",
            "local Sentinel-2 with a limited pre-cloud-masked DN alias; local cop-dem-glo-30 requires verified v1 metadata, elevation metres and native grid evidence; no automatic Google DEM alias or arbitrary upload admission",
            "metadata-dependent collection maps expand a finite local item sequence; pure pixel maps retain the compact path",
            "UTC date fields supported with documented local policies for average year/month durations and ISO weeks; no Google numerical comparison",
            "qualityMosaic requires identical bands; equal quality uses the last local item, not yet Google-compared",
            ("Image integer casts and bit operations use a bounded native Float64/NaN SPI, finite source grids, "
             "SDK single-band broadcast and image1 band order. Casts truncate toward zero and clamp 8/16/32-bit "
             "ranges; int64 and bit values stay within exact +/-2^53, shifts use0..63, and bitCount is signed64 "
             "two's complement. Results remain Float64, including bounded casts and bitCount; closed native Double "
             "arithmetic is available; other Float32-only consumers need toFloat(). Integer dtype parity is unverified; "
             "shared50000 work,500 graph nodes,1MB wire, decoded-cell and native-work limits apply."),
            ("Exact eq/neq/lt/lte/gt/gte comparisons use the native path when any operand is Float64, preserving "
             "finite Float64 values and mask intersection; Float32 comparisons keep their existing callback path. "
             "Closed native Double core arithmetic is supported separately; arbitrary callbacks remain restricted."),
            "toDouble/toFloat convert physical cells; bounded Float64 mean/median/min/max/sum/count/first/last/sample-SD reductions and closed core arithmetic preserve precision; arbitrary Float64 pixel callbacks still reject",
            "binary updateMask only; raster consumers retain a planar EPSG:4326 geometry subset",
            "Geometry/Feature binary defaults use pinned local S2 for geodesic EPSG:4326; planar edges with explicit EPSG:4326 use GEOS. Non-4326 CRS, reprojection/ErrorMargin and full-sphere public encoding remain gaps. S2 binary64 boundary/roundtrip differences are measured; explicit spherical results reject at legacy planar raster/filter consumers. Unflagged raster inputs retain their earlier planar path without a GEE geodesic parity claim",
            "Filter.notNull tests flat local metadata names with at most 1000 properties and the shared compilation budget; null and missing fail while falsey non-null values pass",
            "Dictionary missing keys require a non-null default; explicit empty value-key lists stay empty; List.sequence count/end spacing and count/step ranges materialize at most 10000 finite values",
            "List zip/unzip truncate to shortest; flatten traverses Lists only and preserves typed atoms, depth<=96; repeat/reverse/set/swap preserve values without mutating sources, strict negative-index bounds; <=10000 top-level values and shared work/materialization budgets",
            "List.reduce supports <=1000 inline rows: scalar count/first/last and finite numeric sum/mean/min/max/median/sample-SD, plus unweighted two-input linearFit and <=32-input linearRegression. Null rows are excluded, invalid non-null fields still reject; empty sum/count=0, other empty/singleton-SD=null are local policies without Google comparison; typed regression arrays continue to downstream operations",
            "Classifier.minimumDistance supports Euclidean, Manhattan and cosine spectral-angle metrics, kNearest=1 and CLASSIFICATION over finite inline FeatureCollections: training 1..1000 rows, explicit 1..8 flat numeric input properties, integer labels 0..63, subsampling=1 and seed=0. Exact binary64-rational means and Euclidean/L1 distances determine a unique nearest class; cosine uses sign-aware exact dot/center-norm cross-products without floating normalization or acos. Ties and cosine zero-norm queries/centers reject at prediction. Feature classification preserves metadata and rejects output-name collisions. Training confusionMatrix genuinely resubstitutes and includes gaps in 0..max class order. Bounded sampleRegions runtime training has a separate contract; sample-trained minimumDistance confusionMatrix and FeatureCollection.classify remain unsupported. Mahalanobis/other modes and direct server-object JSON reject; no Google numerical comparison",
            "Image.classify supports the trained minimumDistance subset through local_ee_minimum_distance: required scalar bands are extracted by schema name and ordered explicitly, extra bands do not affect validity. Exact rational model centers reach a dedicated GeoTrellis kernel without Float32 narrowing; actual finite Float32/Float64 input values are used. One classification/outputName band preserves input properties, grid, time and footprint. Selected NoData masks the output; valid infinities, nearest-class ties and cosine zero queries reject, literal zero centers reject at compilation and sampled zero centers when the runtime model is encoded. Local physical output is Int32 NoData, labels0..63; Google dtype/tie parity is unverified. Version1 rational strings are canonical reduced fractions <=700 chars/2200 bits and finite binary64 magnitude, shared work/graph/grid/key/cell bounds plus67108864 pixel-class-band operations. Trusted actual tile-kernel controls are separate from unrun full Spark batch, sandbox/server/browser or Google acceptance",
            "static Array values only: finite exact-domain inputs, rank <=8, <=10000 cells and shared 50000-step work budget; explicit PixelTypes, empty constructors, negative indices and raster arrays reject; matrix kernels require rank 2 and matrixSolve full column rank; no Google numerical comparison",
            "static Array QR/LU/SVD decompositions require nonempty square matrices and return real typed matrix factors with precharged cubic work and combined output limits. QR/SVD signs and repeated-value bases follow NumPy/LAPACK; LU uses first-maximum partial pivots, requires nonzero computed pivots and rejects nonfinite elimination. Rectangular decompositions and Google/EJML numerical equivalence remain unverified",
            "Fixed single rank2 arrays with uniform explicit per-array toFloat/toDouble cells; either Double input promotes output, otherwise an explicit final Float32 cast retains input rounding. Existing stable literal full-column-rank solve keeps its bounded NumPy rcond=None scalar path. Actual raster-context solve also supports dynamic designs, wide and rank-deficient systems through one shared local_ee_matrix_values producer; matrixInverse and matrixPseudoInverse use the same native producer. Axes1..8, combined A+B input<=64 and output<=64 separately, compiler50000/graph500 unchanged. Fresh source/grid and matching temporal dimensions are mandatory; no fabricated constant global grid. Scaled Commons Math3.6.1 SVD uses its local numerical-rank cutoff; exact original-RHS BigDecimal dot products avoid normalization underflow, with exact constant-column centering only at full column rank. Zero-rank solve/pseudoinverse return zero; numerical-singular inverse, any missing input or nonfinite result masks the entire result matrix. Source Infinity rejects. Finite source-free constant inverse/pseudoinverse can fold; unrepresentable masked constant results reject. Native decoded/key/cell/work budgets are revalidated; shape/work admission is not a strict SVD iteration bound. Larger compositions may still exceed limits. Output masks/name/metadata/row-major order are retained. Whole-matrix nonfinite policy applies to the Float64 kernel; subsequent existing Float32 casts can overflow to Infinity, while source-free constant fold rejects nonfinite final casts. SDK compilation, independent synthetic graph and trusted GeoTrellis tile evidence do not establish full Spark, deployed/browser/export or Google numerical/rank/dtype parity.",
            "simple/inverted/saveFirst/saveAll/saveBest/inner joins use <=1000 local image frames and flat finite scalar metadata conditions; inclusive numeric maxDifference supplies a unique direct or conjunctive measure; multiple measures and measures under Or/Not reject when requested; spatial/vector joins and nested selectors reject; stable local order/ties and synthetic graph controls, no native-engine/Google acceptance",
            "Join.inner emits at most 1000 null-geometry Feature pairs retaining real Images; primary/secondary/measure keys must be distinct flat names; a requested measure is on the result Feature; shared work and public output budgets apply",
            "inline FeatureCollection metadata operations only: <=1000 features, bounded serialized callbacks and JSON/finite Array/concrete Image properties; maps may return homogeneous Features or Images, mixed types reject; merge requires explicit IDs; ordered missing/null comparisons use an unverified three-valued policy, null equality and complex comparisons reject; unsupported geometry processing, remote collections and vector execution reject",
            "Reducer.linearFit/linearRegression support unweighted inline FeatureCollection.reduceColumns and List.reduce, <=1000 rows and <=32 input columns with work budgets; insufficient/rank-deficient systems produce documented null outputs. Raster linearFit supports 1..8 homogeneous two-band frames. Raster linearRegression supports numX=1 through-origin, or numX=2 with a proven unit first predictor, numY=1..4, joint complete rows, n>numX and coefficients/RMS arrays; parallelScale=1 and binary NoData only. A three-observation Float64 through-origin coefficient graph matches an independent Fraction sample-graph reference; its RMS branch now fits under unchanged limits via bounded immutable-lineage caching; source-grid checks remain fresh. Outside these subsets general raster linearRegression and nonempty weightSelectors reject; independent graph controls are not native-engine/Google acceptance",
            "Multiple fixed-shape array bands use a bounded typed container (1..8 bands, <=64 total cells) with exact shared metadata provenance; exact name/index selection, rename and scoped metadata only. Select a single array before scalarization; true casts, generic array bundle operations and direct raster export reject. Deferred singleton labels remove redundant metadata nodes without fusing numeric callbacks. Work and 500-node graph limits still apply; the four-frame/two-response example supports full coefficients and predictions, while full RMS and all-field outputs still exceed the cap",
            "Number.format supports bounded finite static %s/%d/%f forms with limited sign/width/precision flags; half-up decimal rounding uses Python shortest decimal spelling, signed-64-bit exact %d only; scientific/hex/grouping and unverified string spellings reject, no Google rounding comparison",
            "Number.sin/cos take finite static numeric radians, exact-domain integers only, with precharged shared work. Float64 libm argument reduction is a local policy, not Google numerical parity",
            "Number/Array hypot use real stable Float64 kernels with finite results; static Array operands must have the same typed shape and share existing budgets. Static atan2 interprets left=x,right=y per pinned SDK documentation and calls libm/NumPy atan2(right,left); the official community harmonic example conflicts with this axis interpretation, so Google orientation remains unverified. Image.atan2 uses its independent native Float32 process with the same pinned x/y convention; its finite scope is documented separately",
            "Image.hypot uses existing pixel operations for the stable ratio norm, an explicit Float32 result and normal band pairing/broadcast/names, masks and left metadata/source fallback. Work is charged before constructing expressions; graph cap is unchanged. Known direct constant Float32 overflow rejects; a dynamic norm outside Float32 range can become infinity in local sample evaluation. Typed Double core operands retain precision until the explicit final Float32 cast; local staged rounding is not Google bitwise parity",
            "Image.arrayCat concatenates same-rank single fixed arrays along an existing axis with matching other dimensions and conjunction of whole-array masks. Image.arrayRepeat repeats complete axis blocks using a provably valid positive constant scalar copies Image; dynamic/masked/spatial copies reject. Row-major cells and dtype are retained, rank<=8/axes<=64/cells<=64 with precharged shared work and unchanged500-node graph cap; no raster-engine/Google acceptance",
            "matrixDiagonal preserves fixed rank2 cell dtype. One fixed rank2 single column with1..8 rows and uniform explicit toFloat/toDouble cells. Produces nxn matrix retaining original diagonal and input whole-array mask/name/metadata/source; canonical +0 off-diagonal Double cells share a precharged source-bound abs(input0)*0 expression. Source Infinity rejects in native arithmetic, NaN masks. Output<=64 cells, compiler50000/graph500 unchanged; larger compositions may exceed limits. No full Spark or Google equivalence claim. One fixed rank2 square array1..8 with uniform explicit toFloat/toDouble cells; staged diagonal addition and scalar output retain input whole-array mask/name/metadata/source. No implicit dtype inference. Existing50000 work/64cells/500nodes retained, maximum dimensions not a guarantee all graph combinations fit. Local staged binary32/binary64 behavior has sample-graph proofs, not full Spark/Google parity. One fixed rank2 square array1..4 with uniform explicit toFloat/toDouble cells. Precharged permutation products/parity and staged sums preserve full input mask and metadata. Polynomial expansion can cancel or overflow; not stable LU or Google parity. Existing50000 work/64cells/500graph nodes retained and larger public graphs may reject; direct IR construction alone is not raster execution.",
            "One fixed single-array rank1..8 image with uniform explicit toFloat/toDouble cells. Existing axis, optional/null SUM default or finite SUM/MIN/MAX only; actual staged row-major prefixes with input whole-array mask/name/metadata/source and no row deletion. Invalid axis/reducer, uncast/mixed cells, unknown arguments and budget excess reject. Compiler50000/64cells/500nodes unchanged, shapes not jointly guaranteed with full graph expansion. Float32 behavior preserved; Double sample-graph proof is distinct from full native array/Spark/Google acceptance. One fixed nonempty rank2 array with uniform explicit toFloat/toDouble cells. Real staged scaled Frobenius arithmetic normalizes by maximum absolute input, handles zero scale via local divide-by-zero0, preserves input whole-array mask and metadata. Finite source inputs only for native Double arithmetic; result overflow masks. Extreme/subnormal and nested-cast sample-graph controls verified. Precharged50000 work/64cells/500graph nodes unchanged; larger graph compositions can reject. No full Spark/Google dtype or ULP parity.",
            "Single fixed-array Image.select now shares exact-name/index and optional bounded rename semantics with array-band bundles, preserving real cells, masks and metadata. Regex/empty/duplicate array selectors remain unsupported; scalar Image selection keeps its existing path",
            "ImageCollection.toArrayPerBand supports1..8 homogeneous scalar frames and1..8 bands, axis0 and dropMasked=false, <=64 total cells; each named array uses only that band's all-frame validity conjunction. Dynamic dropMasked=true rejects. Image.arrayReshape reinterprets a single fixed array with valid constant rank1 lengths and1..8 dimensions, at most one inferred -1, preserving row-major cells, dtype, name, metadata and mask; dynamic/masked shape values and incompatible sizes reject. Existing shared work and500-node graph caps apply; no native-engine/Google acceptance",
            "static String cat and comparison check the shared 50000-step budget before allocation/work; String accepts finite numeric conversion only beyond strings; Python code-point Unicode and shortest numeric spelling are local policies without Google comparison",
            "Double conditional selection and Double-payload Image.where use two closed ternary native operations through the bounded values SPI, with selected-branch and where-fallback NoData policies. Fresh grid/asset evidence and matching temporal dimensions are validated before merging; no payload callbacks or ordinary-mask missing-key fallback. Finite binary64 constants, exact-domain raw integers, original work/key/cell caps retained; full Spark/Google acceptance is separate",
            "unmask uses Float64 on bounded aligned local grids; global footprint extension and implicit time/grid broadcasting reject; closed native Double core arithmetic is available; other Float32-only consumers need toFloat",
            "collection reductions preserve individual scenes; compiled graphs limited to 500 nodes",
            "region boundary weighting is not verified against Earth Engine",
            "addBands binds finite constants/date milliseconds to each destination item's finite local grid and footprint with independent masks; standalone constant rasters, logical constant projection queries and unsupported parameters rejected",
        ],
    }
