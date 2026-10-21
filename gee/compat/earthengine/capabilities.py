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
    "Element.get", "Image.get", "Element.propertyNames", "Element.set", "Element.setMulti", "Element.copyProperties", "Image.copyProperties",
    "Date", "DateRange", "Date.millis", "Date.advance", "Date.fromYMD", "Date.get", "Date.format", "Projection", "Projection.crs", "Feature", "Collection", "FeatureCollection",
    "Number", "String", "List", "Dictionary",
    *("Filter." + n for n in ("and", "or", "not", "dateRangeContains", "intersects", "equals", "lessThan", "greaterThan", "stringContains", "inList", "listContains", "calendarRange")),
    *("reduce." + n for n in ("median", "mean", "min", "max", "sum", "count")),
    *("Reducer." + n for n in ("mean", "median", "min", "max", "sum", "count", "first", "last", "sampleStdDev")),
    *("Image." + n for n in ("add", "subtract", "multiply", "divide", "pow", "mod", "eq", "neq", "gt", "gte", "lt", "lte", "and", "or", "min", "max", "abs", "sqrt", "log", "log10", "exp", "round", "floor", "ceil", "sin", "cos", "tan", "not")),
    *("GeometryConstructors." + n for n in ("Rectangle", "Point", "Polygon", "MultiPolygon", "LineString", "MultiPoint")),
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
            "toDouble/toFloat convert physical cells; Float64 pixel callbacks and temporal reductions reject until precision is preserved",
            "binary updateMask only; planar EPSG:4326 input geometries",
            "unmask uses Float64 on bounded aligned local grids; global footprint extension and implicit time/grid broadcasting reject; cast explicitly toFloat before callback arithmetic or temporal reduction",
            "collection reductions preserve individual scenes; compiled graphs limited to 500 nodes",
            "region boundary weighting is not verified against Earth Engine",
            "standalone constant rasters and unsupported parameters rejected",
        ],
    }
