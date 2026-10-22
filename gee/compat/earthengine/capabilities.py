"""Declared Earth Engine compiler handlers and their current caveats."""

from ...ee_dates import SUPPORTED_DATE_FUNCTIONS
from ...ee_integer import SUPPORTED_INTEGER_FUNCTIONS


# Handler inventory, not a claim that every overload or parameter is supported,
# nor that Google-service numerical equivalence has been established.
SUPPORTED_FUNCTIONS = frozenset({
    *SUPPORTED_DATE_FUNCTIONS,
    *SUPPORTED_INTEGER_FUNCTIONS,
    "ImageCollection.load", "Image.load", "Image.constant", "Image", "ImageCollection",
    "Collection.filter", "Collection.map", "Collection.limit", "Collection.sort", "Collection.size", "Collection.first",
    "ImageCollection.mosaic", "ImageCollection.qualityMosaic", "Image.select", "Image.rename", "Image.bandNames", "Image.toFloat", "Image.toDouble",
    "Image.normalizedDifference", "Image.parseExpression", "Image.updateMask", "Image.mask", "Image.unmask", "Image.addBands", "Image.clip", "Image.reduceRegion",
    "Image.where", "Image.clamp", "Image.unitScale", "Image.reduce", "Image.date", "Image.geometry", "Collection.geometry", "Feature.geometry",
    "Collection.toList", "AggregateFeatureCollection.array", "ImageCollection.reduce", "ImageCollection.toBands", "ImageCollection.fromImages", "ImageCollection.merge", "If", "List.map", "List.iterate",
    "Collection.merge", "Collection.iterate", "Collection.reduceColumns", "Reducer.linearFit", "Reducer.linearRegression", "Number.format",
    "Element.get", "Image.get", "Element.propertyNames", "Element.set", "Element.setMulti", "Element.copyProperties", "Image.copyProperties",
    "Date", "DateRange", "Date.millis", "Date.advance", "Date.fromYMD", "Date.get", "Date.format", "Projection", "Projection.crs", "Feature", "Collection", "FeatureCollection",
    "Number", "String", "List", "Dictionary",
    "Array",
    *("Image." + n for n in ("toArray", "arrayFlatten", "arrayProject", "arraySlice",
        "arrayGet", "arrayLength", "arrayLengths", "arrayTranspose", "arrayReduce", "matrixMultiply")),
    *("Array." + n for n in ("add", "subtract", "multiply", "divide", "abs", "sqrt",
        "reduce", "accum", "slice", "project", "repeat", "cat", "eigen",
        "matrixCholeskyDecomposition", "matrixDeterminant", "matrixTrace",
        "matrixDiagonal", "matrixToDiag", "matrixFnorm")),
    *("Array." + n for n in ("get", "length", "toList", "reshape", "transpose", "matrixTranspose", "matrixMultiply", "matrixInverse", "matrixSolve", "matrixPseudoInverse")),
    *("Join." + n for n in ("simple", "inverted", "saveFirst", "saveAll", "saveBest", "inner", "apply")),
    *("Filter." + n for n in ("and", "or", "not", "dateRangeContains", "intersects", "equals", "lessThan", "greaterThan", "stringContains", "inList", "listContains", "calendarRange", "notNull", "maxDifference")),
    *("reduce." + n for n in ("median", "mean", "min", "max", "sum", "count")),
    *("Reducer." + n for n in ("mean", "median", "min", "max", "sum", "count", "first", "last", "sampleStdDev")),
    *("Image." + n for n in ("add", "subtract", "multiply", "divide", "pow", "mod", "eq", "neq", "gt", "gte", "lt", "lte", "and", "or", "min", "max", "abs", "sqrt", "log", "log10", "exp", "round", "floor", "ceil", "sin", "cos", "tan", "not")),
    *("GeometryConstructors." + n for n in ("Rectangle", "Point", "Polygon", "MultiPolygon", "LineString", "MultiLineString", "MultiPoint")),
    *("Number." + n for n in ("add", "subtract", "multiply", "divide", "pow", "mod", "eq", "neq", "gt", "gte", "lt", "lte", "abs", "round", "floor", "ceil", "sqrt", "toInt", "int")),
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
            "static Array values only: finite exact-domain inputs, rank <=8, <=10000 cells and shared 50000-step work budget; explicit PixelTypes, empty constructors, negative indices and raster arrays reject; matrix kernels require rank 2 and matrixSolve full column rank; no Google numerical comparison",
            "simple/inverted/saveFirst/saveAll/saveBest/inner joins use <=1000 local image frames and flat finite scalar metadata conditions; inclusive numeric maxDifference supplies a unique direct or conjunctive measure; multiple measures and measures under Or/Not reject when requested; spatial/vector joins and nested selectors reject; stable local order/ties and synthetic graph controls, no native-engine/Google acceptance",
            "Join.inner emits at most 1000 null-geometry Feature pairs retaining real Images; primary/secondary/measure keys must be distinct flat names; a requested measure is on the result Feature; shared work and public output budgets apply",
            "inline FeatureCollection metadata operations only: <=1000 features, bounded serialized callbacks and JSON/finite Array/concrete Image properties; maps may return homogeneous Features or Images, mixed types reject; merge requires explicit IDs; ordered missing/null comparisons use an unverified three-valued policy, null equality and complex comparisons reject; unsupported geometry processing, remote collections and vector execution reject",
            "Reducer.linearFit/linearRegression support unweighted inline FeatureCollection.reduceColumns only, <=1000 rows and <=32 selected columns with work budgets; insufficient/rank-deficient systems produce documented null outputs; image/raster regression and nonempty weightSelectors reject; static independent numerical controls, no native-engine/Google acceptance",
            "Number.format supports bounded finite static %s/%d/%f forms with limited sign/width/precision flags; half-up decimal rounding uses Python shortest decimal spelling, signed-64-bit exact %d only; scientific/hex/grouping and unverified string spellings reject, no Google rounding comparison",
            "static String cat and comparison check the shared 50000-step budget before allocation/work; String accepts finite numeric conversion only beyond strings; Python code-point Unicode and shortest numeric spelling are local policies without Google comparison",
            "unmask uses Float64 on bounded aligned local grids; global footprint extension and implicit time/grid broadcasting reject; cast explicitly toFloat before generic callback arithmetic",
            "collection reductions preserve individual scenes; compiled graphs limited to 500 nodes",
            "region boundary weighting is not verified against Earth Engine",
            "addBands binds finite constants/date milliseconds to each destination item's finite local grid and footprint with independent masks; standalone constant rasters, logical constant projection queries and unsupported parameters rejected",
        ],
    }
