"""Declared Earth Engine compiler handlers and their current caveats."""

from ...ee_dates import SUPPORTED_DATE_FUNCTIONS
from ...ee_integer import SUPPORTED_INTEGER_FUNCTIONS


# Handler inventory, not a claim that every overload or parameter is supported,
# nor that Google-service numerical equivalence has been established.
SUPPORTED_FUNCTIONS = frozenset({
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
        "arrayGet", "arrayLength", "arrayLengths", "arrayTranspose", "arrayReduce", "arrayReshape", "arrayCat", "arrayRepeat", "matrixMultiply", "matrixSolve",
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
             "columns, null/JSON cell encoding and planar WGS84 validation are explicit local policies "
             "without Google CSV parity. Other table formats/cloud destinations/maxVertices/priority reject. "
             "Trusted synthetic service/writer tests are not deployed/native-process/browser acceptance"),
            "Array.sort and Image.arraySort use same-rank keys with one selected non-singleton axis and matching axis length; all other key dimensions are singleton. Stable ascending ties are a local policy without Google comparison. Static typed arrays retain dtype within rank8/cells10000/shared50000 work, including unambiguous typed empty arrays and local scalar identity. Raster sorting requires explicit Float32 value/key cells, retains coupled slices and full value/key masks; rank1..8/cells64/500 graph cap. No raster-engine or Google acceptance",
            "ConfusionMatrix consumersAccuracy uses diagonal/row totals and producersAccuracy diagonal/column totals per pinned descriptions. fscore uses actual-row recall/predicted-column precision as an explicit inference. All return local finite rank1 Float64 arrays; Google shape/dtype parity is unverified. Finite positive beta, exact rational intermediates, undefined denominator rejection and existing counts/class/work limits apply",
            "Array.argmax returns the first row-major maximum's coordinate list, [] for rank0 and null for typed empty slices, within existing finite exact-domain/static budgets. Image.arrayArgmax supports one fixed rank1..8 array with explicit top-level Float32 cells, returning actual first-maximum coordinates under the full input mask. Raster coordinate values are locally Float32 integers, not verified Google Integer dtype equivalence; scalar/Double/bundle inputs reject. Work is precharged and64-cell/50000-work/500-node limits remain. No raster-engine or Google acceptance",
            "local Sentinel-2 only; limited pre-cloud-masked DN alias",
            "metadata-dependent collection maps expand a finite local item sequence; pure pixel maps retain the compact path",
            "UTC date fields supported with documented local policies for average year/month durations and ISO weeks; no Google numerical comparison",
            "qualityMosaic requires identical bands; equal quality uses the last local item, not yet Google-compared",
            "Number bitwise operations accept constrained integer domains; Image bitwise and integer casts remain unsupported",
            "toDouble/toFloat convert physical cells; bounded Float64 mean/median/min/max/sum/count/first/last/sample-SD reductions preserve precision; generic Float64 pixel callbacks still reject",
            "binary updateMask only; planar EPSG:4326 input geometries",
            "Python named GeoJSON CRS is decoded; explicit spherical edges, non-EPSG:4326 geometry, left-inside interiors and reprojection tolerances reject; omitted edge flags retain the existing local planar policy",
            "Filter.notNull tests flat local metadata names with at most 1000 properties and the shared compilation budget; null and missing fail while falsey non-null values pass",
            "Dictionary missing keys require a non-null default; explicit empty value-key lists stay empty; List.sequence count/end spacing and count/step ranges materialize at most 10000 finite values",
            "List zip/unzip truncate to shortest; flatten traverses Lists only and preserves typed atoms, depth<=96; repeat/reverse/set/swap preserve values without mutating sources, strict negative-index bounds; <=10000 top-level values and shared work/materialization budgets",
            "List.reduce supports <=1000 inline rows: scalar count/first/last and finite numeric sum/mean/min/max/median/sample-SD, plus unweighted two-input linearFit and <=32-input linearRegression. Null rows are excluded, invalid non-null fields still reject; empty sum/count=0, other empty/singleton-SD=null are local policies without Google comparison; typed regression arrays continue to downstream operations",
            "Classifier.minimumDistance supports Euclidean, Manhattan and cosine spectral-angle metrics, kNearest=1 and CLASSIFICATION over finite inline FeatureCollections: training 1..1000 rows, explicit 1..8 flat numeric input properties, integer labels 0..63, subsampling=1 and seed=0. Exact binary64-rational means and Euclidean/L1 distances determine a unique nearest class; cosine uses sign-aware exact dot/center-norm cross-products without floating normalization or acos. Ties and cosine zero-norm queries/centers reject at prediction. Feature classification preserves metadata and rejects output-name collisions. Training confusionMatrix genuinely resubstitutes and includes gaps in 0..max class order. Bounded sampleRegions runtime training has a separate contract; sample-trained minimumDistance confusionMatrix and FeatureCollection.classify remain unsupported. Mahalanobis/other modes and direct server-object JSON reject; no Google numerical comparison",
            "Image.classify supports the trained minimumDistance subset through local_ee_minimum_distance: required scalar bands are extracted by schema name and ordered explicitly, extra bands do not affect validity. Exact rational model centers reach a dedicated GeoTrellis kernel without Float32 narrowing; actual finite Float32/Float64 input values are used. One classification/outputName band preserves input properties, grid, time and footprint. Selected NoData masks the output; valid infinities, nearest-class ties and cosine zero queries reject, literal zero centers reject at compilation and sampled zero centers when the runtime model is encoded. Local physical output is Int32 NoData, labels0..63; Google dtype/tie parity is unverified. Version1 rational strings are canonical reduced fractions <=700 chars/2200 bits and finite binary64 magnitude, shared work/graph/grid/key/cell bounds plus67108864 pixel-class-band operations. Trusted actual tile-kernel controls are separate from unrun full Spark batch, sandbox/server/browser or Google acceptance",
            "static Array values only: finite exact-domain inputs, rank <=8, <=10000 cells and shared 50000-step work budget; explicit PixelTypes, empty constructors, negative indices and raster arrays reject; matrix kernels require rank 2 and matrixSolve full column rank; no Google numerical comparison",
            "static Array QR/LU/SVD decompositions require nonempty square matrices and return real typed matrix factors with precharged cubic work and combined output limits. QR/SVD signs and repeated-value bases follow NumPy/LAPACK; LU uses first-maximum partial pivots, requires nonzero computed pivots and rejects nonfinite elimination. Rectangular decompositions and Google/EJML numerical equivalence remain unverified",
            "single fixed-shape raster arrays support real per-cell toFloat casts. Image.matrixSolve requires both arrays explicitly Float32, a literal constant full-column-rank design matrix (1..8 rows,1..4 predictors,rows>=predictors), and a matching raster right side with1..4 columns. It emits real pseudoinverse-times-pixel expressions with the whole-array mask and Float32 output; NumPy Float32 rank cutoff and callback rounding are local policies. Dynamic designs, rank deficiency, unsupported array Float64 arithmetic and budget excess reject; no raster-engine/Google acceptance",
            "simple/inverted/saveFirst/saveAll/saveBest/inner joins use <=1000 local image frames and flat finite scalar metadata conditions; inclusive numeric maxDifference supplies a unique direct or conjunctive measure; multiple measures and measures under Or/Not reject when requested; spatial/vector joins and nested selectors reject; stable local order/ties and synthetic graph controls, no native-engine/Google acceptance",
            "Join.inner emits at most 1000 null-geometry Feature pairs retaining real Images; primary/secondary/measure keys must be distinct flat names; a requested measure is on the result Feature; shared work and public output budgets apply",
            "inline FeatureCollection metadata operations only: <=1000 features, bounded serialized callbacks and JSON/finite Array/concrete Image properties; maps may return homogeneous Features or Images, mixed types reject; merge requires explicit IDs; ordered missing/null comparisons use an unverified three-valued policy, null equality and complex comparisons reject; unsupported geometry processing, remote collections and vector execution reject",
            "Reducer.linearFit/linearRegression support unweighted inline FeatureCollection.reduceColumns and List.reduce, <=1000 rows and <=32 input columns with work budgets; insufficient/rank-deficient systems produce documented null outputs. Raster linearFit supports 1..8 homogeneous two-band frames. Raster linearRegression supports numX=1 through-origin, or numX=2 with a proven unit first predictor, numY=1..4, joint complete rows, n>numX and coefficients/RMS arrays; parallelScale=1 and binary NoData only. Outside these subsets general raster linearRegression and nonempty weightSelectors reject; independent controls are not native-engine/Google acceptance",
            "Multiple fixed-shape array bands use a bounded typed container (1..8 bands, <=64 total cells) with exact shared metadata provenance; exact name/index selection, rename and scoped metadata only. Select a single array before scalarization; true casts, generic array bundle operations and direct raster export reject. Deferred singleton labels remove redundant metadata nodes without fusing numeric callbacks. Work and 500-node graph limits still apply; the four-frame/two-response example supports full coefficients and predictions, while full RMS and all-field outputs still exceed the cap",
            "Number.format supports bounded finite static %s/%d/%f forms with limited sign/width/precision flags; half-up decimal rounding uses Python shortest decimal spelling, signed-64-bit exact %d only; scientific/hex/grouping and unverified string spellings reject, no Google rounding comparison",
            "Number.sin/cos take finite static numeric radians, exact-domain integers only, with precharged shared work. Float64 libm argument reduction is a local policy, not Google numerical parity",
            "Number/Array hypot use real stable Float64 kernels with finite results; static Array operands must have the same typed shape and share existing budgets. Static atan2 interprets left=x,right=y per pinned SDK documentation and calls libm/NumPy atan2(right,left); the official community harmonic example conflicts with this axis interpretation, so Google orientation remains unverified. Image.atan2 uses its independent native Float32 process with the same pinned x/y convention; its finite scope is documented separately",
            "Image.hypot uses existing pixel operations for the stable ratio norm, an explicit Float32 result and normal band pairing/broadcast/names, masks and left metadata/source fallback. Work is charged before constructing expressions; graph cap is unchanged. Known direct constant Float32 overflow rejects; a dynamic norm outside Float32 range can become infinity in local sample evaluation. Explicit Float64 callback operands still reject; local staged rounding is not Google bitwise parity",
            "Image.arrayCat concatenates same-rank single fixed arrays along an existing axis with matching other dimensions and conjunction of whole-array masks. Image.arrayRepeat repeats complete axis blocks using a provably valid positive constant scalar copies Image; dynamic/masked/spatial copies reject. Row-major cells and dtype are retained, rank<=8/axes<=64/cells<=64 with precharged shared work and unchanged500-node graph cap; no raster-engine/Google acceptance",
            "Single fixed-array Image.matrixDiagonal extracts a rank2 rectangular diagonal as a column while retaining cell casts and whole-array mask. Image.matrixToDiag takes an explicit Float32 single column of1..8 cells and inserts real Float32 zeros. Image.matrixTrace supports Float32 square matrices1..8, matrixDeterminant square1..4, using actual staged Float32 sums/products and scalar outputs with the entire input mask. Work is precharged,64-cell/500-node caps retained; general4x4 raster graphs can still exceed the cap. Polynomial determinant cancellation/overflow is a local policy, not stable LU or Google equivalence",
            "Image.arrayAccum supports fixed single-array Float32 prefix sum/min/max along an existing axis, with omitted/null reducer meaning sum; preserves whole-array mask and frame order without row deletion. Image.matrixFnorm uses real staged Float32 scaled Frobenius arithmetic on fixed rank2 arrays, with zero-safe normalization and full input mask. Dynamic outputs can overflow and larger graphs still reject at500; work is precharged,64-cell/50000-work caps retained. These are local numerical subsets without raster-engine/Google acceptance",
            "Single fixed-array Image.select now shares exact-name/index and optional bounded rename semantics with array-band bundles, preserving real cells, masks and metadata. Regex/empty/duplicate array selectors remain unsupported; scalar Image selection keeps its existing path",
            "ImageCollection.toArrayPerBand supports1..8 homogeneous scalar frames and1..8 bands, axis0 and dropMasked=false, <=64 total cells; each named array uses only that band's all-frame validity conjunction. Dynamic dropMasked=true rejects. Image.arrayReshape reinterprets a single fixed array with valid constant rank1 lengths and1..8 dimensions, at most one inferred -1, preserving row-major cells, dtype, name, metadata and mask; dynamic/masked shape values and incompatible sizes reject. Existing shared work and500-node graph caps apply; no native-engine/Google acceptance",
            "static String cat and comparison check the shared 50000-step budget before allocation/work; String accepts finite numeric conversion only beyond strings; Python code-point Unicode and shortest numeric spelling are local policies without Google comparison",
            "unmask uses Float64 on bounded aligned local grids; global footprint extension and implicit time/grid broadcasting reject; cast explicitly toFloat before generic callback arithmetic",
            "collection reductions preserve individual scenes; compiled graphs limited to 500 nodes",
            "region boundary weighting is not verified against Earth Engine",
            "addBands binds finite constants/date milliseconds to each destination item's finite local grid and footprint with independent masks; standalone constant rasters, logical constant projection queries and unsupported parameters rejected",
        ],
    }
