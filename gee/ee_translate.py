"""Compile the explicitly supported Earth Engine value graph to local openEO.

This module evaluates *serialized descriptions*, never Python/JavaScript code.
Collection membership and order remain explicit until the local STAC snapshot is
materialized. Unsupported semantics fail before a batch job is created.
"""
from __future__ import annotations

import copy
import calendar
import datetime as dt
import json
import math
import re
from dataclasses import dataclass, replace
from typing import Any


class UnsupportedEEError(ValueError):
    """The serialized program uses a semantic this local adapter cannot honor."""


# Handler inventory, not a claim that every overload or parameter is supported,
# nor that Google-service numerical equivalence has been established.
SUPPORTED_FUNCTIONS = frozenset({
    "ImageCollection.load", "Image.load", "Image.constant", "Image", "ImageCollection",
    "Collection.filter", "Collection.map", "Collection.limit", "Collection.sort", "Collection.size", "Collection.first",
    "ImageCollection.mosaic", "Image.select", "Image.rename", "Image.bandNames", "Image.toFloat",
    "Image.normalizedDifference", "Image.parseExpression", "Image.updateMask", "Image.mask", "Image.addBands", "Image.clip", "Image.reduceRegion",
    "Image.where", "Image.clamp", "Image.unitScale", "Image.reduce", "Image.date", "Image.geometry", "Collection.geometry", "Feature.geometry",
    "Collection.toList", "AggregateFeatureCollection.array", "ImageCollection.reduce", "ImageCollection.toBands", "ImageCollection.fromImages", "ImageCollection.merge", "If", "List.map", "List.iterate",
    "Element.get", "Image.get", "Element.propertyNames", "Element.set", "Element.setMulti", "Element.copyProperties", "Image.copyProperties",
    "Date", "DateRange", "Date.millis", "Date.advance", "Date.fromYMD", "Date.get", "Date.format", "Projection", "Projection.crs", "Feature", "Collection", "FeatureCollection",
    "Number", "String", "List", "Dictionary",
    *("Filter."+n for n in ("and", "or", "not", "dateRangeContains", "intersects", "equals", "lessThan", "greaterThan", "stringContains", "inList", "listContains", "calendarRange")),
    *("reduce."+n for n in ("median", "mean", "min", "max", "sum", "count")),
    *("Reducer."+n for n in ("mean", "median", "min", "max", "sum", "count", "first", "last", "sampleStdDev")),
    *("Image."+n for n in ("add", "subtract", "multiply", "divide", "pow", "mod", "eq", "neq", "gt", "gte", "lt", "lte", "and", "or", "min", "max", "abs", "sqrt", "log", "log10", "exp", "round", "floor", "ceil", "sin", "cos", "tan", "not")),
    *("GeometryConstructors."+n for n in ("Rectangle", "Point", "Polygon", "MultiPolygon", "LineString", "MultiPoint")),
    *("Number."+n for n in ("add", "subtract", "multiply", "divide", "pow", "mod", "eq", "neq", "gt", "gte", "lt", "lte", "abs", "round", "floor", "ceil", "sqrt", "toInt", "int")),
    *("String."+n for n in ("cat", "length", "compareTo")),
    *("List."+n for n in ("get", "length", "size", "contains", "add", "cat", "sequence", "slice", "distinct", "sort")),
    *("Dictionary."+n for n in ("get", "keys", "values", "contains", "set")),
}) - {"Collection.sort", "FeatureCollection", "Image", "Image.get", "ImageCollection", "List", "Number"}


def get_capabilities():
    return {"compiler_functions": sorted(SUPPORTED_FUNCTIONS), "level": "C",
            "numerical_equivalence_to_google_verified": False,
            "restrictions": ["local Sentinel-2 only; limited pre-cloud-masked DN alias",
                             "native collection map supports pure pixels; fromImages/toList allows finite per-frame metadata evaluation",
                             "binary updateMask only; planar EPSG:4326 input geometries",
                             "collection reductions preserve individual scenes; compiled graphs limited to 500 nodes",
                             "region boundary weighting is not verified against Earth Engine",
                             "standalone constant rasters and unsupported parameters rejected"]}


@dataclass(frozen=True)
class Source:
    cid: str
    ids: tuple[str, ...]
    names: tuple[str, ...]
    alias: bool = False


@dataclass(frozen=True)
class Pixel:
    op: str
    args: tuple
    boolean: bool = False


@dataclass
class Image:
    bands: list[tuple[str, Pixel]]
    props: dict
    source: Source | None = None
    mapped: bool = False
    inherit_props: bool = True
    copied_props: tuple = ()
    footprint: dict | None = None
    footprint_is_absolute: bool = False


@dataclass
class Collection:
    source: Source
    image: Image


@dataclass
class ImageSequence:
    """Finite explicitly ordered Images, including per-period composites."""
    images: list[Image]


@dataclass
class Function:
    names: list
    body: Any
    env: dict


@dataclass
class ParsedExpression:
    text: str
    default: str
    variables: list


@dataclass
class Filter:
    name: str
    args: dict


@dataclass
class Reducer:
    name: str
    unweighted: bool = False


@dataclass
class Region:
    image: Image
    geometry: dict
    reducer: Reducer
    options: dict


def fail(message):
    raise UnsupportedEEError(message)


def const(value):
    if isinstance(value, bool):
        return Pixel("constant", (value,), True)
    if value is None or isinstance(value, (int, float)) and math.isfinite(value):
        return Pixel("constant", (value,))
    fail("Image.constant only supports finite numeric values")


def millis(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value): fail("Date milliseconds must be finite")
        return float(value)
    if isinstance(value, dt.datetime):
        date = value
    elif isinstance(value, str):
        try:
            if re.fullmatch(r"\d{4}", value): value += "-01-01"
            elif re.fullmatch(r"\d{4}-\d{2}", value): value += "-01"
            date = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            fail(f"Unsupported date: {value}")
    else:
        fail("Date requires a string or UTC milliseconds")
    if date.tzinfo is None:
        date = date.replace(tzinfo=dt.timezone.utc)
    difference = date.astimezone(dt.timezone.utc) - dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    return (difference.days * 86400 + difference.seconds) * 1000 + difference.microseconds / 1000


def time_of(item):
    p = item.get("properties", {})
    return millis(p.get("system:time_start", p.get("datetime")))


def utc_date(value):
    return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(milliseconds=millis(value))


def integer(value, label, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value:
        fail(f"{label} must be an integer")
    if minimum is not None and value < minimum: fail(f"{label} must be >= {minimum}")
    return int(value)


def static_truth(value):
    # EE If treats empty arrays/dictionaries/strings, zero, NaN and null as
    # false. Do not accidentally use truthiness of internal IR dataclasses.
    if isinstance(value, (Image, Collection, ImageSequence, Pixel, Region, Function, Filter, Reducer)):
        fail("Algorithms.If currently requires a static scalar/list/dictionary condition")
    if isinstance(value, (int, float)) and not math.isfinite(value): return False
    return bool(value)


def format_date(date, pattern):
    """Explicit small Joda-format subset; never treat unknown tokens as literals."""
    tokens = {"yyyy": f"{date.year:04}", "YYYY": f"{date.year:04}", "yy": f"{date.year % 100:02}",
              "MM": f"{date.month:02}", "M": str(date.month), "dd": f"{date.day:02}", "d": str(date.day),
              "HH": f"{date.hour:02}", "H": str(date.hour), "mm": f"{date.minute:02}", "m": str(date.minute),
              "ss": f"{date.second:02}", "s": str(date.second), "SSS": f"{date.microsecond // 1000:03}",
              "DDD": f"{date.timetuple().tm_yday:03}", "D": str(date.timetuple().tm_yday), "Z": "+0000", "ZZ": "+00:00", "ZZZ": "UTC"}
    if not isinstance(pattern, str) or len(pattern) > 200: fail("Date.format requires a pattern of at most 200 characters")
    out = []; i = 0; literal = False
    while i < len(pattern):
        char = pattern[i]
        if char == "'":
            if i+1 < len(pattern) and pattern[i+1] == "'": out.append("'"); i += 2; continue
            literal = not literal; i += 1; continue
        if literal or not char.isalpha(): out.append(char); i += 1; continue
        end = i+1
        while end < len(pattern) and pattern[end] == char: end += 1
        token = pattern[i:end]
        if token not in tokens: fail(f"Unsupported Date.format token: {token}")
        out.append(tokens[token]); i = end
    if literal: fail("Unclosed Date.format literal")
    return "".join(out)


def _substitute(value, old, new):
    if isinstance(value, Source):
        return new if value == old else value
    if isinstance(value, Pixel):
        return replace(value, args=tuple(_substitute(a, old, new) for a in value.args))
    if isinstance(value, tuple):
        return tuple(_substitute(a, old, new) for a in value)
    return value


def rebind(collection, ids):
    source = replace(collection.source, ids=tuple(ids))
    image = replace(collection.image, source=source, bands=[
        (n, _substitute(p, collection.source, source)) for n, p in collection.image.bands])
    return Collection(source, image)


def as_image(value):
    if isinstance(value, Image):
        return value
    if isinstance(value, (int, float, bool)):
        return Image([("constant", const(value))], {})
    if isinstance(value, list) and all(isinstance(v, (int, float, bool)) for v in value):
        return Image([("constant" + ("_" + str(i) if i else ""), const(v)) for i, v in enumerate(value)], {})
    fail("Expected an Image or finite number")


def pairs(a, b):
    a, b = as_image(a), as_image(b)
    if len(a.bands) == 1 and len(b.bands) > 1:
        return a, b, [(n, a.bands[0][1], p) for n, p in b.bands]
    if len(b.bands) == 1:
        return a, b, [(n, p, b.bands[0][1]) for n, p in a.bands]
    if len(a.bands) != len(b.bands):
        fail("Image operands need equal band counts or a single broadcast band")
    return a, b, [(n, p, q) for (n, p), (_, q) in zip(a.bands, b.bands)]


def binary(a, b, op):
    a, b, matched = pairs(a, b)
    boolean = op in {"eq", "neq", "gt", "gte", "lt", "lte", "and", "or"}
    return Image([(n, Pixel(op, (p, q), boolean)) for n, p, q in matched],
                 dict(a.props), a.source or b.source, a.mapped or b.mapped,
                 a.inherit_props, a.copied_props, a.footprint, a.footprint_is_absolute)


def unary(image, op):
    image = as_image(image)
    return replace(image, bands=[(n, Pixel(op, (p,), op in {"not", "is_nodata"})) for n, p in image.bands])


class Translator:
    def __init__(self, catalog, items, options):
        self.catalog = {x["id"]: x for x in catalog}
        self.items = items
        self.options = dict(options or {})
        unknown = set(self.options) - {"region", "scale", "crs"}
        if unknown:
            fail(f"Unsupported compilation options: {sorted(unknown)}")
        self.scope = {}
        self.warnings = []
        self.steps = 0

    def warn(self, value):
        if value not in self.warnings:
            self.warnings.append(value)

    def load(self, cid, image=False):
        alias = cid in {"COPERNICUS/S2_SR_HARMONIZED", "COPERNICUS/S2_SR"}
        original = cid
        if alias:
            cid = "sentinel-2-l2a"
            self.warn("Sentinel-2 alias uses only locally ingested, pre-cloud-masked reflectance converted to a DN view (x10000); limited coverage and bands B2/B3/B4/B8/SCL do not equal the full official Earth Engine dataset.")
        if cid not in self.catalog:
            fail(f"Collection is not locally ingested or verified: {original}")
        if cid != "sentinel-2-l2a":
            fail(f"Collection has not passed Earth Engine compatibility acceptance: {cid}")
        metadata = self.catalog[cid]
        names = metadata.get("cube:dimensions", {}).get("bands", {}).get("values", [])
        if not names:
            fail("Local collection has no declared bands")
        selected = self.items.get(cid, [])
        source = Source(cid, tuple(i["id"] for i in selected), tuple(names), alias)
        mapping = {"blue": "B2", "green": "B3", "red": "B4", "nir": "B8", "SCL": "SCL"}
        bands = []
        for name in names:
            if alias and name not in mapping:
                continue
            p = Pixel("band", (source, name))
            if alias and name != "SCL":
                p = Pixel("multiply", (p, const(10000)))
            bands.append((mapping[name] if alias else name, p))
        result = Image(bands, {}, source)
        if image:
            if len(selected) != 1:
                fail("Image.load requires an unambiguous local image id; use ImageCollection.first()")
            result.props = dict(selected[0].get("properties", {}))
            result.bands = [(n, Pixel("reduce_t", (p, "first"))) for n, p in result.bands]
            return result
        return Collection(source, result)

    def member(self, source, iid):
        return next(i for i in self.items[source.cid] if i["id"] == iid)

    def properties(self, collection, iid):
        original = self.member(collection.source, iid).get("properties", {})
        image = collection.image
        props = dict(original) if image.inherit_props else {k: original[k] for k in image.copied_props if k in original}
        return {**props, **image.props}

    def collection_items(self, collection):
        items = [{**self.member(collection.source, iid), "properties": self.properties(collection, iid)} for iid in collection.source.ids]
        if collection.image.footprint:
            from shapely.geometry import shape, mapping
            clip = shape(collection.image.footprint)
            items = [{**item, "geometry": mapping(shape(item["geometry"]).intersection(clip))} for item in items]
        return items

    def footprint(self, value):
        from shapely.geometry import shape, mapping
        from shapely.ops import unary_union
        if isinstance(value, ImageSequence):
            geometries = [self.footprint(image) for image in value.images]
        elif isinstance(value, Collection):
            geometries = [item["geometry"] for item in self.collection_items(value)]
        elif isinstance(value, Image):
            if value.footprint is not None and value.footprint_is_absolute: return value.footprint
            if value.source is None: fail("Image geometry requires a source footprint")
            geometries = [self.member(value.source, i)["geometry"] for i in value.source.ids]
            base = unary_union([shape(g) for g in geometries])
            return mapping(base.intersection(shape(value.footprint)) if value.footprint else base)
        elif isinstance(value, dict) and value.get("type") == "Feature": return value["geometry"]
        elif isinstance(value, dict) and value.get("type") == "FeatureCollection":
            geometries = [f["geometry"] for f in value["features"] if f.get("geometry")]
        else: fail("Geometry requires an Image, Collection or Feature")
        if not geometries: fail("An empty collection has no footprint")
        return mapping(unary_union([shape(g) for g in geometries]))

    def select(self, image, selectors, names=None):
        if isinstance(image, ImageSequence):
            return ImageSequence([self.select(im,selectors,names) for im in image.images])
        if isinstance(image, Collection):
            return replace(image, image=self.select(image.image, selectors, names))
        image = as_image(image)
        selectors = selectors if isinstance(selectors, list) else [selectors]
        out = []
        for s in selectors:
            if isinstance(s, int) and not isinstance(s, bool):
                if s < 0 or s >= len(image.bands):
                    fail(f"Band index out of range: {s}")
                out.append(image.bands[s])
            elif isinstance(s, str):
                # Exact names take precedence; regexes use full match like EE.
                matched = [b for b in image.bands if b[0] == s]
                if not matched:
                    try:
                        pattern = re.compile(s)
                    except re.error:
                        fail(f"Invalid band selector: {s}")
                    matched = [b for b in image.bands if pattern.fullmatch(b[0])]
                if not matched:
                    fail(f"Band selector {s!r} did not match; available: {[n for n, _ in image.bands]}")
                out.extend(matched)
            else:
                fail("Band selectors must be strings or zero-based integer indices")
        if len({n for n, _ in out}) != len(out):
            fail("Repeated selected bands are not supported")
        if names is not None:
            if not isinstance(names, list) or len(names) != len(out) or not all(isinstance(n, str) for n in names) or len(set(names)) != len(names):
                fail("New band names must be distinct strings matching the band count")
            out = [(n, p) for n, (_, p) in zip(names, out)]
        if not out:
            fail("Zero-band images are not supported")
        return replace(image, bands=out)

    def matches(self, filt, item):
        a, name = filt.args, filt.name
        if name in {"and", "or"}:
            values = [self.matches(f, item) for f in a["filters"]]
            return all(values) if name == "and" else any(values)
        if name == "not":
            return not self.matches(a["filter"], item)
        props = item.get("properties", {})
        if name == "dateRangeContains":
            if a.get("rightField") != "system:time_start" or "leftValue" not in a:
                fail("Only system:time_start date filtering is supported")
            start, end = a["leftValue"]
            if "system:time_start" not in props: fail("Item metadata property is unavailable: system:time_start")
            return start <= millis(props["system:time_start"]) < end
        if name == "calendarRange":
            if "system:time_start" not in props: fail("Item metadata property is unavailable: system:time_start")
            date = utc_date(props["system:time_start"])
            fields = {"year": date.year, "month": date.month, "day_of_year": date.timetuple().tm_yday,
                      "day_of_month": date.day, "day_of_week": date.isoweekday(), "hour": date.hour, "minute": date.minute}
            field = a.get("field", "day_of_year")
            if field not in fields: fail(f"Unsupported calendar field: {field}")
            start = integer(a["start"], "Calendar start"); end = integer(a.get("end", start), "Calendar end")
            value = fields[field]
            return start <= value <= end if start <= end else value >= start or value <= end
        if name == "intersects":
            if a.get("leftField") != ".all" or "rightValue" not in a:
                fail("Only collection footprint intersection filtering is supported")
            geom = a["rightValue"]
            if geom.get("type") == "Feature":
                geom = geom["geometry"]
            from shapely.geometry import shape
            try:
                return shape(item["geometry"]).intersects(shape(geom))
            except (ValueError, KeyError, TypeError) as exc:
                fail(f"Invalid footprint filter geometry: {exc}")
        def operand(side):
            if side + "Field" in a:
                field = a[side + "Field"]
                if field not in props:
                    fail(f"Item metadata property is unavailable: {field}")
                return props[field]
            if side + "Value" in a:
                return a[side + "Value"]
            fail("Filter operand is missing")
        left, right = operand("left"), operand("right")
        try:
            if name == "equals": return left == right
            if name == "lessThan": return left < right
            if name == "greaterThan": return left > right
            if name == "stringContains": return right in left
            if name in {"inList", "listContains"}:
                if name == "inList": left, right = right, left
                if not isinstance(left, list): fail("Filter.inList requires a list operand")
                return right in left
        except TypeError:
            fail("Metadata filter operands have incompatible types")
        fail(f"Unsupported metadata filter: Filter.{name}")

    def evaluate(self, value, env=None, depth=0):
        self.steps += 1
        if depth > 96 or self.steps > 50000:
            fail("Earth Engine graph exceeds compilation limits")
        env = {} if env is None else env
        if isinstance(value, list):
            if len(value) > 10000: fail("Inline list exceeds 10000 values")
            return [self.evaluate(v, env, depth+1) for v in value]
        if not isinstance(value, dict):
            return value
        typ = value.get("type")
        if typ == "CompoundValue":
            for key, val in value.get("scope", []):
                if key in self.scope:
                    fail("Duplicate serialized scope reference")
                self.scope[key] = val
            return self.evaluate(value["value"], env, depth+1)
        if typ == "ValueRef":
            key = value.get("value")
            if key not in self.scope:
                fail("Unknown serialized value reference")
            return self.evaluate(self.scope[key], env, depth+1)
        if typ == "ArgumentRef":
            if value["value"] not in env:
                fail("Unbound mapped-function argument")
            return env[value["value"]]
        if typ == "Function":
            return Function(value["argumentNames"], value["body"], dict(env))
        if typ == "Invocation":
            if value.get("functionName") == "If":
                raw = value.get("arguments", {})
                self.allowed(raw, {"condition", "trueCase", "falseCase"})
                condition = self.evaluate(raw.get("condition"), env, depth+1)
                return self.evaluate(raw.get("trueCase" if static_truth(condition) else "falseCase"), env, depth+1)
            args = {k: self.evaluate(v, env, depth+1) for k, v in value.get("arguments", {}).items()}
            if "functionName" in value:
                return self.invoke(value["functionName"], args)
            fun = self.evaluate(value.get("function"), env, depth+1)
            if isinstance(fun, ParsedExpression):
                from .ee_expression import parse_expression
                return parse_expression(fun.text, args, fun.default, self)
            if isinstance(fun, Function):
                if set(args) != set(fun.names):
                    fail("Function argument names do not match")
                return self.evaluate(fun.body, {**fun.env, **args}, depth+1)
            fail("Unsupported computed function invocation")
        if typ == "Dictionary":
            return {k: self.evaluate(v, env, depth+1) for k, v in value.get("value", {}).items()}
        if typ in {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon", "GeometryCollection"}:
            if value.get("geodesic") is True:
                fail("Geodesic geometries require spherical geometry support")
            crs = value.get("crs")
            if crs and crs not in {"EPSG:4326"}:
                fail("Only EPSG:4326 input GeoJSON geometries are supported")
            out = {k: copy.deepcopy(v) for k, v in value.items() if k in {"type", "coordinates", "geometries"}}
            if typ == "Polygon":
                for ring in out["coordinates"]:
                    if ring and ring[0] != ring[-1]: ring.append(ring[0])
            return out
        if typ:
            fail(f"Unsupported serialized value type: {typ}")
        return {k: self.evaluate(v, env, depth+1) for k, v in value.items()}

    def invoke(self, name, a):
        # Inputs are resolved values, so there is no executable user code here.
        if name in {"ImageCollection.fromImages", "ImageCollection.merge"} or isinstance(a.get("collection"), ImageSequence):
            from .ee_collections import invoke_sequence
            return invoke_sequence(self,name,a)
        if name in {"Image.constant", "Image.bandNames", "Date.millis", "Collection.size", "Collection.first"}:
            self.allowed(a, {"Image.constant": {"value"}, "Image.bandNames": {"image"}, "Date.millis": {"date"},
                             "Collection.size": {"collection"}, "Collection.first": {"collection"}}[name])
        if name in {"Element.get", "Image.get", "Element.propertyNames", "Element.set", "Element.setMulti"}:
            self.allowed(a, {"Element.get": {"object", "property"}, "Image.get": {"object", "image", "property"},
                             "Element.propertyNames": {"element"}, "Element.set": {"object", "key", "value"},
                             "Element.setMulti": {"object", "properties"}}[name])
        if name == "ImageCollection.load":
            self.allowed(a, {"id", "version"})
            if a.get("version") is not None: fail("Versioned collection loads are unsupported")
            return self.load(a["id"])
        if name == "Image.load":
            self.allowed(a, {"id", "version"})
            if a.get("version", -1) != -1: fail("Versioned image loads are unsupported")
            iid = a["id"]
            for cid, values in self.items.items():
                found = [i for i in values if i["id"] == iid]
                if found:
                    result = self.load(cid)
                    result = rebind(result, [iid])
                    return self.first(result)
            fail(f"Image is not locally available: {iid}")
        if name == "Image.constant": return as_image(a["value"])
        if name in {"Image", "ImageCollection"}:
            value = next(iter(a.values()))
            return as_image(value) if name == "Image" else value
        if name == "Collection.filter":
            self.allowed(a, {"collection", "filter"})
            c, f = a["collection"], a["filter"]
            if not isinstance(c, Collection) or not isinstance(f, Filter): fail("Expected a collection and filter")
            return rebind(c, [i["id"] for i in self.collection_items(c) if self.matches(f, i)])
        if name.startswith("Filter."):
            operation = name.split(".", 1)[1]
            if operation not in {"and", "or", "not", "dateRangeContains", "intersects", "equals", "lessThan", "greaterThan", "stringContains", "inList", "listContains", "calendarRange"}:
                fail(f"Unsupported filter: {name}")
            if operation in {"and", "or"}: self.allowed(a, {"filters"})
            elif operation == "not": self.allowed(a, {"filter"})
            elif operation == "calendarRange": self.allowed(a, {"start", "end", "field"})
            else: self.allowed(a, {"leftField", "leftValue", "rightField", "rightValue", "maxError"} if operation == "intersects" else {"leftField", "leftValue", "rightField", "rightValue"})
            for side in ("left", "right"):
                if side+"Field" in a and side+"Value" in a: fail("Filter operands cannot specify both field and value")
            return Filter(operation, a)
        if name == "Collection.map":
            self.allowed(a, {"collection", "baseAlgorithm", "dropNulls"})
            if a.get("dropNulls"): fail("map(dropNulls=true) is unsupported")
            c, f = a["collection"], a["baseAlgorithm"]
            if not isinstance(c, Collection) or not isinstance(f, Function) or len(f.names) != 1:
                fail("Collection.map needs a one-argument serialized function")
            image = self.evaluate(f.body, {**f.env, f.names[0]: replace(c.image, mapped=True)})
            if not isinstance(image, Image): fail("Collection.map must return an Image")
            return replace(c, image=replace(image, mapped=False, source=c.source))
        if name in {"Collection.limit", "Collection.sort"}:
            self.allowed(a, {"collection", "limit", "key", "ascending"})
            c = a["collection"]; ids = list(c.source.ids)
            key = a.get("key")
            if key is not None:
                def sortkey(i):
                    props = self.properties(c, i)
                    if key not in props: fail(f"Sort property is unavailable: {key}")
                    return props[key]
                ids.sort(key=sortkey, reverse=not a.get("ascending", True))
            if a.get("limit") is not None:
                limit = a["limit"]
                if isinstance(limit, bool) or not isinstance(limit, (int, float)) or limit < 0 or int(limit) != limit:
                    fail("Collection limit must be a nonnegative integer")
                ids = ids[:int(limit)]
            return rebind(c, ids)
        if name == "Collection.size": return len(a["collection"].source.ids)
        if name == "Collection.first": return self.first(a["collection"])
        if name == "Collection.toList":
            self.allowed(a, {"collection", "count", "offset"})
            c = a["collection"]; count = integer(a["count"], "Collection count", 0); offset = integer(a.get("offset", 0), "Collection offset", 0)
            if count > 1000: fail("Collection.toList supports at most 1000 images")
            return [self.first(rebind(c, [i])) for i in c.source.ids[offset:offset+count]]
        if name == "AggregateFeatureCollection.array":
            self.allowed(a, {"collection", "property"})
            c, key = a["collection"], a["property"]
            if not isinstance(c, Collection): fail("aggregate_array currently requires an ImageCollection")
            result = []
            for i in c.source.ids:
                props = self.properties(c, i)
                if key not in props: fail(f"Item metadata property is unavailable: {key}")
                result.append(props[key])
            return result
        if name == "ImageCollection.toBands":
            self.allowed(a, {"collection"})
            c = a["collection"]; bands = []
            if len(c.source.ids)*len(c.image.bands) > 100: fail("Local toBands is limited to 100 output bands")
            for iid in c.source.ids:
                im = self.first(rebind(c, [iid]))
                prefix = im.props.get("system:index")
                if not isinstance(prefix, str): fail("toBands requires system:index on each image")
                bands.extend((prefix+"_"+n, p) for n, p in im.bands)
            if len({n for n, _ in bands}) != len(bands): fail("toBands produced duplicate band names")
            return Image(bands, {}, c.source, inherit_props=False, footprint=c.image.footprint)
        if name == "ImageCollection.reduce":
            self.allowed(a, {"collection", "reducer", "parallelScale"})
            parallel = a.get("parallelScale", 1)
            if isinstance(parallel, bool) or not isinstance(parallel, (int, float)) or not math.isfinite(parallel) or parallel < 1:
                fail("parallelScale must be finite and >= 1")
            c, reducer = a["collection"], a["reducer"]
            if not isinstance(reducer, Reducer): fail("Collection.reduce requires a supported single-output reducer")
            suffix = "stdDev" if reducer.name == "sd" else reducer.name
            return Image([(n+"_"+suffix, Pixel("reduce_t", (p, reducer.name))) for n, p in c.image.bands], {}, c.source, inherit_props=False, footprint=c.image.footprint)
        if name.startswith("reduce."):
            self.allowed(a, {"collection"})
            reducer = name.split(".", 1)[1]
            if reducer not in {"median", "mean", "min", "max", "sum", "count"}: fail(f"Unsupported collection reducer: {reducer}")
            c = a["collection"]
            return Image([(n, Pixel("reduce_t", (p, reducer))) for n, p in c.image.bands], {}, c.source, inherit_props=False, footprint=c.image.footprint)
        if name == "ImageCollection.mosaic":
            self.allowed(a, {"collection"})
            c = a["collection"]
            return Image([(n, Pixel("reduce_t", (p, "last", "collection_order"))) for n, p in c.image.bands], {}, c.source, inherit_props=False, footprint=c.image.footprint)
        if name == "Image.select":
            self.allowed(a, {"input", "bandSelectors", "newNames"})
            return self.select(a["input"], a["bandSelectors"], a.get("newNames"))
        if name == "Image.rename":
            self.allowed(a, {"input", "names"})
            im = a["input"]
            return self.select(im, list(range(len(im.bands))), a["names"])
        if name == "Image.bandNames": return [n for n, _ in a["image"].bands]
        if name == "Image.toFloat":
            self.allowed(a, {"value"})
            return as_image(a["value"])
        if name == "Image.normalizedDifference":
            self.allowed(a, {"input", "bandNames"})
            im = as_image(a["input"])
            chosen = a.get("bandNames") or [n for n, _ in im.bands[:2]]
            if len(chosen) != 2: fail("normalizedDifference requires two bands")
            p, q = [v for _, v in self.select(im, chosen).bands]
            negative = Pixel("or", (Pixel("lt", (p, const(0)), True), Pixel("lt", (q, const(0)), True)), True)
            denominator = Pixel("add", (p, q))
            valid = Pixel("and", (Pixel("not", (negative,), True), Pixel("neq", (denominator, const(0)), True)), True)
            ratio = Pixel("divide", (Pixel("subtract", (p, q)), denominator))
            return Image([("nd", Pixel("if", (valid, ratio, const(None))))], {}, im.source, im.mapped, False, footprint=im.footprint, footprint_is_absolute=im.footprint_is_absolute)
        if name == "Image.parseExpression":
            self.allowed(a, {"expression", "argName", "vars"})
            return ParsedExpression(a["expression"], a["argName"], a["vars"])
        if name == "Image.updateMask":
            self.allowed(a, {"image", "mask"})
            image_input, mask_input = as_image(a["image"]), as_image(a["mask"])
            if len(mask_input.bands) not in {1, len(image_input.bands)}:
                fail("updateMask needs one broadcast mask band or the same number of bands as the Image")
            im, mask, matched = pairs(a["image"], a["mask"])
            for _, _, m in matched:
                if not m.boolean and not (m.op == "constant" and m.args[0] in (0, 1)):
                    fail("updateMask currently supports binary masks only; fractional masks and opacity are unsupported")
            return replace(im, bands=[(n, Pixel("if", (m, p, const(None)))) for n, p, m in matched])
        if name == "Image.mask":
            self.allowed(a, {"image", "mask"})
            if "mask" in a: fail("Image.mask setter is unsupported; use updateMask")
            return unary(unary(a["image"], "is_nodata"), "not")
        if name == "Image.where":
            self.allowed(a, {"input", "test", "value"})
            im, test, value = as_image(a["input"]), as_image(a["test"]), as_image(a["value"])
            if len(test.bands) not in {1, len(im.bands)} or len(value.bands) not in {1, len(im.bands)}:
                fail("where test/value require one broadcast band or the input band count")
            bands = []
            for i, (n, p) in enumerate(im.bands):
                t = test.bands[0 if len(test.bands) == 1 else i][1]
                v = value.bands[0 if len(value.bands) == 1 else i][1]
                condition = Pixel("if", (Pixel("is_nodata", (t,), True), const(False), Pixel("neq", (t, const(0)), True)), True)
                condition = Pixel("if", (Pixel("is_nodata", (v,), True), const(False), condition), True)
                replacement = Pixel("if", (condition, v, p))
                bands.append((n, Pixel("preserve_mask", (replacement, p))))
            return replace(im, bands=bands)
        if name in {"Image.clamp", "Image.unitScale"}:
            self.allowed(a, {"input", "low", "high"})
            low, high = a["low"], a["high"]
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (low, high)) or high <= low:
                fail("clamp/unitScale requires finite low < high")
            im = as_image(a["input"])
            if name.endswith("unitScale"): return binary(binary(im, low, "subtract"), high-low, "divide")
            return binary(binary(im, low, "max2"), high, "min2")
        if name == "Image.reduce":
            self.allowed(a, {"image", "reducer"})
            im, reducer = as_image(a["image"]), a["reducer"]
            if not isinstance(reducer, Reducer): fail("Image.reduce requires a supported single-output Reducer")
            output = "stdDev" if reducer.name == "sd" else reducer.name
            return replace(im, bands=[(output, Pixel("reduce_bands", (tuple(p for _, p in im.bands), reducer.name)))])
        if name == "Image.date":
            self.allowed(a, {"image"})
            return millis(self.invoke("Element.get", {"object": a["image"], "property": "system:time_start"}))
        if name in {"Image.geometry", "Feature.geometry", "Collection.geometry"}:
            self.allowed(a, {"feature", "collection", "maxError", "proj", "geodesics"})
            if a.get("proj") not in (None, "EPSG:4326") or a.get("geodesics") is True:
                fail("Geometry extraction currently supports planar EPSG:4326 only")
            return self.footprint(a.get("feature", a.get("collection")))
        if name == "Image.addBands":
            self.allowed(a, {"dstImg", "srcImg", "names", "overwrite"})
            im, src = as_image(a["dstImg"]), as_image(a["srcImg"])
            if a.get("names") is not None: src = self.select(src, a["names"])
            bands = list(im.bands)
            for n, p in src.bands:
                existing = [x for x, _ in bands]
                if n in existing and a.get("overwrite", False): bands[existing.index(n)] = (n, p)
                else:
                    base = n; suffix = 1
                    while n in existing:
                        n = f"{base}_{suffix}"; suffix += 1
                    bands.append((n, p))
            return replace(im, bands=bands, source=im.source or src.source)
        if name == "Image.clip":
            self.allowed(a, {"input", "geometry"})
            im = as_image(a["input"]); geom = a["geometry"]
            if geom.get("type") == "Feature": geom = geom["geometry"]
            if geom.get("type") not in {"Polygon", "MultiPolygon"}: fail("clip supports Polygon/MultiPolygon only")
            from shapely.geometry import shape, mapping
            footprint = mapping(shape(im.footprint).intersection(shape(geom))) if im.footprint else geom
            return replace(im, bands=[(n, Pixel("clip", (p, geom))) for n, p in im.bands], footprint=footprint)
        if name == "Image.reduceRegion":
            self.allowed(a, {"image", "reducer", "geometry", "scale", "crs", "crsTransform", "bestEffort", "maxPixels", "tileScale"})
            if a.get("crsTransform") is not None or a.get("bestEffort") or a.get("tileScale", 1) != 1:
                fail("reduceRegion crsTransform, bestEffort and custom tileScale are unsupported")
            im = as_image(a["image"])
            geometry = a.get("geometry") or self.options.get("region")
            if not geometry: fail("reduceRegion requires an explicit geometry")
            reducer = a["reducer"]
            if not isinstance(reducer, Reducer): fail("Expected a supported Reducer")
            opts = {**self.options, **{k: a[k] for k in ("scale", "crs", "maxPixels") if k in a}}
            self.warn("Regional reduction uses local GeoTrellis rasterization; fractional boundary/mask weighting has not been verified against Earth Engine.")
            return Region(im, geometry, reducer, opts)
        if name.startswith("Reducer."):
            operation = name.split(".", 1)[1]
            if operation == "unweighted":
                fail("Reducer.unweighted requires a verified rasterization policy and is not yet supported")
            if operation not in {"mean", "median", "min", "max", "sum", "count", "first", "last", "sampleStdDev"}:
                fail(f"Unsupported reducer: {name}; stdDev cannot be mapped to sample standard deviation")
            if a: fail(f"Unsupported parameters for {name}")
            return Reducer("sd" if operation == "sampleStdDev" else operation)
        if name in {"Element.get", "Element.propertyNames", "Image.get"}:
            obj = a.get("object", a.get("image", a.get("element")))
            if name.endswith("propertyNames"):
                if obj.mapped: fail("propertyNames inside map depends on per-item metadata")
                return list(obj.props)
            key = a["property"]
            if key not in obj.props and obj.mapped: fail(f"Dynamic item metadata inside map is unsupported: {key}")
            return obj.props.get(key)
        if name in {"Element.set", "Element.setMulti"}:
            obj = a["object"]
            props = dict(obj.props)
            if name.endswith("setMulti"): props.update(a["properties"])
            else: props[a["key"]] = a["value"]
            if not all(isinstance(k, str) for k in props): fail("Metadata property names must be strings")
            try: json.dumps(props, allow_nan=False)
            except (TypeError, ValueError): fail("Only static JSON values may be stored in image metadata")
            return replace(obj, props=props)
        if name in {"Image.copyProperties", "Element.copyProperties"}:
            self.allowed(a, {"destination", "source", "properties", "exclude"})
            dst, src = a["destination"], a["source"]
            names = a.get("properties")
            if names is not None and a.get("exclude"): fail("copyProperties cannot use properties and exclude together")
            if src.mapped:
                # Carry-through is representable, individual property reads aren't.
                if dst.source != src.source: fail("Mapped copyProperties must use the same source image")
                if names is None:
                    fail("copyProperties inside map currently requires an explicit property-name list")
            names = names if names is not None else [k for k in src.props if not k.startswith("system:")]
            props = dict(dst.props)
            for k in names:
                if k not in a.get("exclude", []) and k in src.props: props[k] = src.props[k]
            return replace(dst, props=props, copied_props=tuple(dict.fromkeys((*dst.copied_props, *names))))
        binary_ops = {"add": "add", "subtract": "subtract", "multiply": "multiply", "divide": "divide", "pow": "power", "mod": "mod", "eq": "eq", "neq": "neq", "gt": "gt", "gte": "gte", "lt": "lt", "lte": "lte", "and": "and", "or": "or", "min": "min2", "max": "max2"}
        if name.startswith("Image.") and name[6:] in binary_ops:
            self.allowed(a, {"image1", "image2"})
            return binary(a["image1"], a["image2"], binary_ops[name[6:]])
        unary_ops = {"abs": "absolute", "sqrt": "sqrt", "log": "log", "log10": "log10", "exp": "exp", "round": "round", "floor": "floor", "ceil": "ceil", "sin": "sin", "cos": "cos", "tan": "tan", "not": "not"}
        if name.startswith("Image.") and name[6:] in unary_ops:
            self.allowed(a, {"value", "image"})
            return unary(a.get("value", a.get("image")), unary_ops[name[6:]])
        if name == "Date":
            self.allowed(a, {"value", "timeZone"})
            if a.get("timeZone") not in (None, "UTC"): fail("Only UTC Date is supported")
            return millis(a["value"])
        if name == "Projection":
            self.allowed(a, {"crs", "transform", "transformWkt"})
            if a.get("transform") is not None or a.get("transformWkt") is not None:
                fail("Projection transforms are unsupported")
            crs = a["crs"]
            if not isinstance(crs, str) or not re.fullmatch(r"EPSG:\d+", crs): fail("Projection requires an EPSG code")
            return crs
        if name == "Projection.crs":
            self.allowed(a, {"projection"})
            return a["projection"]
        if name == "DateRange":
            self.allowed(a, {"start", "end", "timeZone"})
            if a.get("timeZone") not in (None, "UTC"): fail("Only UTC DateRange is supported")
            start = millis(a["start"])
            return (start, millis(a["end"]) if a.get("end") is not None else start + 1)
        if name == "Date.millis": return a["date"]
        if name == "Date.advance":
            self.allowed(a, {"date", "delta", "unit", "timeZone"})
            if a.get("timeZone") not in (None, "UTC"): fail("Only UTC dates are supported")
            factors = {"millisecond": 1, "second": 1000, "minute": 60000, "hour": 3600000, "day": 86400000, "week": 604800000}
            unit = a["unit"].removesuffix("s")
            if unit in {"month", "year"}:
                delta = integer(a["delta"], "Calendar Date.advance delta")
                date = utc_date(a["date"])
                month_index = date.year*12+date.month-1+delta*(12 if unit == "year" else 1)
                year, month = divmod(month_index, 12); month += 1
                if not 1 <= year <= 9999: fail("Date.advance year is outside 1..9999")
                return millis(date.replace(year=year, month=month, day=min(date.day, calendar.monthrange(year, month)[1])))
            if unit not in factors: fail("Unsupported Date.advance unit")
            return a["date"] + a["delta"] * factors[unit]
        if name in {"Date.fromYMD", "Date.get", "Date.format"}:
            self.allowed(a, {"year", "month", "day", "timeZone"} if name.endswith("fromYMD") else {"date", "unit", "timeZone"} if name.endswith("get") else {"date", "format", "timeZone"})
            if a.get("timeZone") not in (None, "UTC"): fail("Only UTC dates are supported")
            if name.endswith("fromYMD"):
                return millis(dt.datetime(*(integer(a[k], "Date "+k) for k in ("year", "month", "day")), tzinfo=dt.timezone.utc))
            date = utc_date(a["date"])
            if name.endswith("get"):
                fields = {"year": date.year, "month": date.month, "day": date.day, "hour": date.hour,
                          "minute": date.minute, "second": date.second}
                if a["unit"] not in fields: fail("Unsupported Date.get unit")
                return fields[a["unit"]]
            return format_date(date, a.get("format") or "yyyy-MM-dd'T'HH:mm:ss.SSSZZ")
        if name == "Feature":
            self.allowed(a, {"geometry", "metadata"})
            if isinstance(a.get("metadata"), Region):
                if a.get("geometry") is not None:
                    fail("A reduceRegion Feature export wrapper currently requires null geometry")
                return a["metadata"]
            return {"type": "Feature", "geometry": a.get("geometry"), "properties": a.get("metadata", {})}
        if name in {"Collection", "FeatureCollection"}:
            self.allowed(a, {"features"})
            features = a.get("features")
            if not isinstance(features, list): fail("FeatureCollection requires an inline feature list")
            if len(features) == 1 and isinstance(features[0], Region): return features[0]
            if not all(isinstance(f, dict) and f.get("type") == "Feature" for f in features):
                fail("Only static Features or one reduceRegion Feature can be exported as a FeatureCollection")
            return {"type": "FeatureCollection", "features": features}
        if name.startswith("GeometryConstructors."):
            operation = name.split(".")[1]
            self.allowed(a, {"coordinates", "crs", "geodesic", "evenOdd", "maxError"})
            if a.get("crs") not in (None, "EPSG:4326") or a.get("geodesic") is True: fail("Only planar EPSG:4326 geometries are supported")
            coords = a["coordinates"]
            if operation == "Rectangle":
                if len(coords) == 4 and isinstance(coords[0], (int, float)): w, s, e, n = coords
                else: (w, s), (e, n) = coords
                return {"type": "Polygon", "coordinates": [[[w,s],[e,s],[e,n],[w,n],[w,s]]]}
            if operation not in {"Point", "Polygon", "MultiPolygon", "LineString", "MultiPoint"}: fail(f"Unsupported geometry constructor: {operation}")
            return self.evaluate({"type": operation, "coordinates": coords})
        if name in {"Number", "String", "List", "Dictionary"}:
            self.allowed(a, {"input", "value", "values", "dictionary"})
            if len(a) != 1: fail(f"{name} requires exactly one static constructor value")
            return a.get("input", a.get("value", a.get("values", a.get("dictionary"))))
        if name.startswith(("Number.", "String.", "List.", "Dictionary.")):
            return self.static(name, a)
        fail(f"Unsupported Earth Engine algorithm: {name}")

    @staticmethod
    def allowed(args, names):
        unknown = set(args) - names
        if unknown: fail(f"Unsupported algorithm arguments: {sorted(unknown)}")

    def first(self, collection):
        if not collection.source.ids: fail("Cannot take first image of an empty collection")
        c = rebind(collection, collection.source.ids[:1])
        props = self.properties(c, c.source.ids[0])
        return replace(c.image, props=props,
                       bands=[(n, Pixel("reduce_t", (p, "first"))) for n, p in c.image.bands])

    def static(self, name, a):
        kind, op = name.split(".", 1)
        argument_names = {
            "String.cat": {"string1", "string2"}, "String.length": {"string"}, "String.compareTo": {"string1", "string2"},
            "List.get": {"list", "index"}, "List.length": {"list"}, "List.size": {"list"}, "List.contains": {"list", "element"},
            "List.add": {"list", "element"}, "List.cat": {"list1", "list2"}, "List.sequence": {"start", "end", "step", "count"},
            "List.slice": {"list", "start", "end", "step"}, "List.distinct": {"list"}, "List.sort": {"list", "keys"},
            "List.map": {"list", "baseAlgorithm", "dropNulls"}, "List.iterate": {"list", "function", "first"},
            "Dictionary.get": {"dictionary", "key", "defaultValue"}, "Dictionary.keys": {"dictionary"}, "Dictionary.values": {"dictionary", "keys"},
            "Dictionary.contains": {"dictionary", "key"}, "Dictionary.set": {"dictionary", "key", "value"}}
        if kind == "Number":
            self.allowed(a, {"left", "right"} if op in {"add", "subtract", "multiply", "divide", "pow", "mod", "eq", "neq", "gt", "gte", "lt", "lte"} else {"input"})
        elif name in argument_names: self.allowed(a, argument_names[name])
        vals = list(a.values())
        value = a.get("input", a.get(kind.lower(), a.get("left", vals[0] if vals else None)))
        if kind == "Number":
            if any(isinstance(x, (Image, Collection)) for x in vals): fail("Expected a static Number")
            right = a.get("right")
            funcs = {"add": lambda: value+right, "subtract": lambda: value-right, "multiply": lambda: value*right,
                     "divide": lambda: value/right if right else 0, "pow": lambda: value**right, "mod": lambda: value%right,
                     "eq": lambda: value==right, "neq": lambda: value!=right, "gt": lambda: value>right,
                     "gte": lambda: value>=right, "lt": lambda: value<right, "lte": lambda: value<=right,
                     "abs": lambda: abs(value), "round": lambda: math.floor(value+.5), "floor": lambda: math.floor(value),
                     "ceil": lambda: math.ceil(value), "sqrt": lambda: math.sqrt(value), "toInt": lambda: int(value), "int": lambda: int(value)}
            if op in funcs:
                try: return funcs[op]()
                except (ArithmeticError, TypeError, ValueError): fail(f"Invalid static Number.{op} operands")
        if kind == "String":
            if op == "cat": return str(a["string1"])+str(a["string2"])
            if op == "length": return len(value)
            if op == "compareTo": return (value>a["string2"])-(value<a["string2"])
        if kind == "List":
            value = a.get("list", value)
            if op == "get":
                try: return value[integer(a["index"], "List index")]
                except (IndexError, TypeError): fail("List index out of range")
            if op in {"length", "size"}: return len(value)
            if op == "contains": return a["element"] in value
            if op == "add":
                if len(value) >= 10000: fail("Computed list exceeds 10000 values")
                return value+[a["element"]]
            if op == "cat":
                if len(a["list1"])+len(a["list2"]) > 10000: fail("Computed list exceeds 10000 values")
                return a["list1"]+a["list2"]
            if op in {"map", "iterate"}:
                if not isinstance(value, list) or len(value) > 1000: fail("List.map/iterate supports at most 1000 inline values")
                fun = a["baseAlgorithm" if op == "map" else "function"]
                if not isinstance(fun, Function) or len(fun.names) != (1 if op == "map" else 2): fail("Invalid serialized list callback")
                result = [] if op == "map" else a.get("first")
                for item in value:
                    args = [item] if op == "map" else [item, result]
                    mapped = self.evaluate(fun.body, {**fun.env, **dict(zip(fun.names, args))})
                    if op == "iterate": result = mapped
                    elif mapped is not None: result.append(mapped)
                    elif not a.get("dropNulls", False): fail("List.map returned null; set dropNulls=true")
                return result
            if op == "slice":
                step = integer(a.get("step", 1), "List slice step", 1)
                return value[integer(a.get("start", 0), "List slice start"):None if a.get("end") is None else integer(a["end"], "List slice end"):step]
            if op == "distinct":
                result = []
                for item in value:
                    if item not in result: result.append(item)
                return result
            if op == "sort":
                keys = a.get("keys", value)
                if len(keys) != len(value): fail("List.sort keys must match list length")
                return [v for _, v in sorted(zip(keys, value), key=lambda x: x[0])]
            if op == "sequence":
                if a.get("count") is not None: fail("List.sequence count parameter is unsupported")
                start, end, step = a.get("start", 0), a["end"], a.get("step", 1)
                if not step or abs((end-start)/step) > 10000: fail("List.sequence limit exceeded")
                length = max(0, int(math.floor((end-start)/step))+1)
                return [start+i*step for i in range(length)]
        if kind == "Dictionary":
            value = a.get("dictionary", value)
            if op == "get": return value.get(a["key"], a.get("defaultValue"))
            if op == "keys": return sorted(value)
            if op == "values": return [value[k] for k in (a.get("keys") or sorted(value))]
            if op == "contains": return a["key"] in value
            if op == "set": return {**value, a["key"]: a["value"]}
        fail(f"Unsupported static operation: {name}")


class Graph:
    def __init__(self, translator):
        self.t = translator
        self.graph = {}
        self.cache = {}
        self.sources = {}
        self.required_bands = {}

    def node(self, process_id, **args):
        key = json.dumps([process_id, args], sort_keys=True)
        if key not in self.cache:
            nid = "n"+str(len(self.graph))
            self.graph[nid] = {"process_id": process_id, "arguments": args}
            self.cache[key] = {"from_node": nid}
        return self.cache[key]

    def callback(self, process, args):
        return {"process_graph": {"p": {"process_id": process, "arguments": args, "result": True}}}

    def source(self, source):
        if source not in self.sources:
            if not source.ids: fail("Collection filter has no locally available images")
            extent = self.t.options.get("region")
            if extent:
                from shapely.geometry import shape
                w, s, e, n = shape(extent).bounds
            else:
                bounds = [self.t.member(source, i).get("bbox") for i in source.ids]
                if any(b is None for b in bounds): fail("Local items need bbox metadata")
                w, s, e, n = min(b[0] for b in bounds), min(b[1] for b in bounds), max(b[2] for b in bounds), max(b[3] for b in bounds)
            self.sources[source] = self.node("load_collection", id=source.cid,
                spatial_extent={"west": w, "south": s, "east": e, "north": n},
                _gee_item_ids=list(source.ids), bands=[n for n in source.names if n in self.required_bands.get(source, source.names)])
        return self.sources[source]

    def scalar_args(self, op, x, y=None):
        if op in {"min2", "max2"}: return ("min" if op == "min2" else "max"), {"data": [x, y], "ignore_nodata": False}
        if op == "power": return op, {"base": x, "p": y}
        if op == "mod": return op, {"x": x, "y": y}
        if op == "exp": return op, {"p": x}
        if op in {"log", "log10"}: return "log", {"x": x, "base": math.e if op == "log" else 10}
        if op == "if": fail("Internal conditional argument mismatch")
        return op, {"x": x, **({"y": y} if y is not None else {})}

    def expression(self, p):
        if p.op == "constant":
            # GeoTrellis's scalar callback builder represents logical pixels as
            # 0/1; a Boolean false literal is not a numeric accept value there.
            value = p.args[0]
            return int(value) if isinstance(value, bool) else value, None, True
        if p.op == "band":
            source, name = p.args
            ref = self.node("filter_bands", data=self.source(source), bands=[name])
            return self.node("rename_labels", data=ref, dimension="bands", target=["v"]), "v", True
        if p.op == "clip":
            ref, label, timed = self.expression(p.args[0])
            if label is None: fail("Clipping an unbound constant image is unsupported")
            return self.node("mask_polygon", data=ref, mask=p.args[1]), label, timed
        if p.op == "preserve_mask":
            ref, label, timed = self.expression(p.args[0])
            mask, _, mask_time = self.expression(Pixel("is_nodata", (p.args[1],), True))
            if timed != mask_time: fail("Mask dimensions do not match")
            return self.node("mask", data=ref, mask=mask), label, timed
        if p.op == "reduce_t":
            sources = set()
            def find_sources(value):
                if isinstance(value, Pixel):
                    if value.op == "band": sources.add(value.args[0])
                    else:
                        for operand in value.args: find_sources(operand)
                elif isinstance(value, tuple):
                    for operand in value: find_sources(operand)
            find_sources(p.args[0])
            if len(sources) > 1: fail("Temporal reduction across distinct collection sources requires explicit alignment")
            if sources:
                source = next(iter(sources))
                if len(source.ids) > 1:
                    # Upstream STAC loading truncates scene timestamps to UTC
                    # days. Load each immutable item separately, then reduce an
                    # explicit ordered band axis. No invented dates or lost
                    # same-day observations; all runs still share one batch.
                    ids = source.ids
                    scenes = []
                    for iid in ids:
                        singleton = replace(source,ids=(iid,))
                        self.required_bands.setdefault(singleton,set()).update(self.required_bands.get(source,source.names))
                        scenes.append(Pixel("reduce_t", (_substitute(p.args[0],source,singleton), "first")))
                    scenes = tuple(scenes)
                    return self.expression(Pixel("reduce_bands", (scenes,p.args[1])))
            ref, label, timed = self.expression(p.args[0])
            if label is None: fail("Reducing an unbound constant image is unsupported")
            if not timed: fail("Image has no collection time dimension")
            reducer = self.callback(p.args[1], {"data": {"from_parameter": "data"}, **({} if p.args[1] == "count" else {"ignore_nodata": True})})
            ref = self.node("reduce_dimension", data=ref, dimension="t", reducer=reducer)
            if p.args[1] == "count":
                ref = self.node("apply", data=ref, process={"process_graph": {
                    "valid": {"process_id": "gt", "arguments": {"x": {"from_parameter": "x"}, "y": 0}},
                    "result": {"process_id": "if", "arguments": {"value": {"from_node": "valid"}, "accept": {"from_parameter": "x"}, "reject": None}, "result": True}}})
            return ref, label, False
        operands = p.args[0] if p.op == "reduce_bands" else p.args
        results = [self.expression(x) for x in operands]
        rasters = [(i, r) for i, r in enumerate(results) if r[1] is not None]
        if not rasters:
            # Only constant operations are computed here; arbitrary expressions
            # never pass through eval() or an interpreter supplied by the user.
            values = [r[0] for r in results]
            if p.op == "if": return values[1] if values[0] else values[2], None, True
            funcs = {"add": lambda: values[0]+values[1], "subtract": lambda: values[0]-values[1], "multiply": lambda: values[0]*values[1], "divide": lambda: values[0]/values[1], "power": lambda: values[0]**values[1], "eq": lambda: values[0]==values[1], "neq": lambda: values[0]!=values[1], "lt": lambda: values[0]<values[1], "lte": lambda: values[0]<=values[1], "gt": lambda: values[0]>values[1], "gte": lambda: values[0]>=values[1], "and": lambda: bool(values[0] and values[1]), "or": lambda: bool(values[0] or values[1]), "not": lambda: not values[0], "absolute": lambda: abs(values[0]),
                     "is_nodata": lambda: values[0] is None or not math.isfinite(values[0]),
                     "min2": lambda: min(values), "max2": lambda: max(values), "mod": lambda: math.fmod(*values),
                     "sqrt": lambda: math.sqrt(values[0]), "log": lambda: math.log(values[0]), "log10": lambda: math.log10(values[0]),
                     "exp": lambda: math.exp(values[0]), "round": lambda: math.floor(values[0]+.5),
                     "floor": lambda: math.floor(values[0]), "ceil": lambda: math.ceil(values[0]),
                     "sin": lambda: math.sin(values[0]), "cos": lambda: math.cos(values[0]), "tan": lambda: math.tan(values[0])}
            if p.op == "divide" and values[1] == 0: return 0, None, True
            if p.op not in funcs: fail("Unsupported unbound constant image expression")
            try:
                value = funcs[p.op]()
                return int(value) if isinstance(value, bool) else value, None, True
            except (ArithmeticError, TypeError, ValueError): return None, None, True
        # Give every operand a distinct internal band. The callback then pairs
        # by explicit index; labels never implicitly decide band arithmetic.
        data = None
        callback = {}
        args = [r[0] for r in results]
        timed = rasters[0][1][2]
        for index, (position, (ref, _, has_time)) in enumerate(rasters):
            if has_time != timed: fail("Combining a temporal collection with a spatial image needs unsupported time broadcasting")
            ref = self.node("rename_labels", data=ref, dimension="bands", target=[f"a{index}"])
            data = ref if data is None else self.node("merge_cubes", cube1=data, cube2=ref)
            key = "a"+str(index)
            callback[key] = {"process_id": "array_element", "arguments": {"data": {"from_parameter": "data"}, "index": index}}
            args[position] = {"from_node": key}
        if p.op == "divide":
            # Official Image.divide / Number.divide explicitly return zero for
            # division by zero. Multiplying the numerator by zero preserves its
            # NoData mask instead of manufacturing a new valid pixel.
            callback["zero_denominator"] = {"process_id": "eq", "arguments": {"x": args[1], "y": 0}}
            callback["zero"] = {"process_id": "multiply", "arguments": {"x": args[0], "y": 0}}
            callback["quotient"] = {"process_id": "divide", "arguments": {"x": args[0], "y": args[1]}}
            process, op_args = "if", {"value": {"from_node": "zero_denominator"}, "accept": {"from_node": "zero"}, "reject": {"from_node": "quotient"}}
        elif p.op == "reduce_bands":
            reducer = p.args[1]
            # Some JVM aggregators reuse their first input tile as an
            # accumulator. A conditional may evaluate a callback reference
            # twice, so hand each aggregator fresh pixel tiles each time.
            safe_args = []
            for index, argument in enumerate(args):
                key = "copy"+str(index)
                callback[key] = {"process_id": "multiply", "arguments": {"x": argument, "y": 1}}
                safe_args.append({"from_node": key})
            process, op_args = reducer, {"data": safe_args, **({} if reducer == "count" else {"ignore_nodata": True})}
        elif p.op == "if":
            # The JVM callback requires a non-null accept operand. Invert a
            # null-accept conditional, preserving the same NoData branch.
            if args[1] is None:
                callback["inverted"] = {"process_id": "not", "arguments": {"x": args[0]}}
                process, op_args = "if", {"value": {"from_node": "inverted"}, "accept": args[2], "reject": None}
            else: process, op_args = "if", dict(zip(("value", "accept", "reject"), args))
        else: process, op_args = self.scalar_args(p.op, args[0], args[1] if len(args)>1 else None)
        if p.op == "reduce_bands" and p.args[1] in {"count", "sum"}:
            callback["reduced"] = {"process_id": process, "arguments": op_args}
            callback["valid_count"] = {"process_id": "count", "arguments": {"data": safe_args}}
            callback["has_values"] = {"process_id": "gt", "arguments": {"x": {"from_node": "valid_count"}, "y": 0}}
            process, op_args = "if", {"value": {"from_node": "has_values"}, "accept": {"from_node": "reduced"}, "reject": None}
        callback["result"] = {"process_id": process, "arguments": op_args, "result": True}
        result = self.node("reduce_dimension", data=data, dimension="bands", reducer={"process_graph": callback})
        return self.node("add_dimension", data=result, name="bands", label="v", type="bands"), "v", timed

    def image(self, image):
        def collect(value):
            if isinstance(value, Pixel):
                if value.op == "band": self.required_bands.setdefault(value.args[0], set()).add(value.args[1])
                else:
                    for operand in value.args: collect(operand)
            elif isinstance(value, tuple):
                for operand in value: collect(operand)
        for _, pixel in image.bands: collect(pixel)
        out = None; time_state = None
        for name, pixel in image.bands:
            ref, label, timed = self.expression(pixel)
            if label is None:
                fail("A standalone constant image needs a raster grid and unmasked constant raster support")
            if time_state is not None and timed != time_state: fail("Image bands have incompatible time dimensions")
            time_state = timed
            ref = self.node("rename_labels", data=ref, dimension="bands", target=[name])
            out = ref if out is None else self.node("merge_cubes", cube1=out, cube2=ref)
        scale = self.t.options.get("scale")
        crs = self.t.options.get("crs")
        if scale is not None or crs is not None:
            if scale is None or not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0: fail("A positive scale in meters is required when setting output scale/CRS")
            if crs is not None and not re.fullmatch(r"EPSG:\d+", crs): fail("CRS must be an EPSG code")
            if crs == "EPSG:4326": fail("Meter-scale output in geographic EPSG:4326 needs projection-aware grid support")
            out = self.node("resample_spatial", data=out, resolution=scale, method="near", **({"projection": int(crs[5:])} if crs else {}))
        if self.t.options.get("region") is not None:
            # A nonrectangular export region must mask pixels, not merely limit
            # the source query to the region's bounding box.
            out = self.node("mask_polygon", data=out, mask=self.t.options["region"])
        return out, time_state

    def finish(self, ref):
        self.graph[ref["from_node"]]["result"] = True
        if len(self.graph) > 500: fail("Compiled process graph exceeds 500 nodes; reduce the script scope")
        return self.graph


def compile_expression(expression, catalog, items, options=None):
    """Compile one legacy ee.Serializer.encode value; no network or execution.

    Internal load_collection._gee_item_ids must be validated and materialized
    only by the trusted backend; this function does not resolve file paths.
    """
    if isinstance(expression, str):
        try: expression = json.loads(expression)
        except json.JSONDecodeError as exc: raise UnsupportedEEError("Expected serialized Earth Engine JSON") from exc
    if len(json.dumps(expression)) > 1000000: fail("Serialized Earth Engine expression exceeds 1 MB")
    translator = Translator(catalog, items, options)
    try:
        value = translator.evaluate(expression)
        if isinstance(value, ImageSequence):
            return {"kind":"collection", "bands":[n for n,_ in value.images[0].bands] if value.images else [],
                    "source_item_ids":[im.props.get("system:index",str(i)) for i,im in enumerate(value.images)],
                    "features":[{"type":"Image","id":im.props.get("system:index",str(i)),"properties":im.props,
                                 "bands":[{"id":n} for n,_ in im.bands]} for i,im in enumerate(value.images)],
                    "has_time_dimension":True,"warnings":translator.warnings,"properties":{}}
        if isinstance(value, (Image, Collection)):
            graph = Graph(translator)
            image = value.image if isinstance(value, Collection) else value
            ref, timed = graph.image(image)
            return {"kind": "collection" if isinstance(value, Collection) else "image",
                    "process_graph": graph.finish(ref), "bands": [n for n, _ in image.bands],
                    "properties": image.props, "warnings": translator.warnings,
                    "has_time_dimension": timed, "source_item_ids": list(dict.fromkeys(i for source in graph.sources for i in source.ids))}
        if isinstance(value, Region):
            opts = {k: v for k, v in value.options.items() if k in {"region", "scale", "crs"}}
            translator.options = opts
            graph = Graph(translator)
            ref, timed = graph.image(value.image)
            if timed: fail("reduceRegion requires a single Image, not a time-dependent collection")
            reducer = graph.callback(value.reducer.name, {"data": {"from_parameter": "data"}, **({} if value.reducer.name == "count" else {"ignore_nodata": True})})
            ref = graph.node("aggregate_spatial", data=ref, geometries=value.geometry, reducer=reducer)
            return {"kind": "region", "process_graph": graph.finish(ref), "bands": [n for n, _ in value.image.bands], "warnings": translator.warnings, "reducer": value.reducer.name,
                    "geometry": value.geometry, "grid_options": value.options}
        if isinstance(value, (Function, ParsedExpression, Filter, Reducer)):
            fail("A function/filter/reducer is not a computable output value")
        # Ensure no internal class or non-finite number crosses the API boundary.
        encoded = json.dumps(value, allow_nan=False)
        if len(encoded) > 1000000: fail("Computed value exceeds 1 MB")
        return {"kind": "value", "value": json.loads(encoded), "warnings": translator.warnings}
    except UnsupportedEEError:
        raise
    except (KeyError, IndexError, TypeError, AttributeError, ValueError, RecursionError, OverflowError) as exc:
        raise UnsupportedEEError(f"Malformed or unsupported Earth Engine expression: {exc}") from exc
