"""Image, geometry query and reducer operations over the compatibility IR."""
from __future__ import annotations

import math
from dataclasses import replace

from .ir import Image, Pixel, Reducer, Region, as_image, binary, const, fail, pairs, unary


_IMAGE_NAMES = {
    "Image.select", "Image.rename", "Image.bandNames", "Image.toFloat", "Image.toDouble",
    "Image.normalizedDifference", "Image.parseExpression", "Image.updateMask", "Image.mask",
    "Image.where", "Image.clamp", "Image.unitScale", "Image.reduce", "Image.date",
    "Image.geometry", "Feature.geometry", "Collection.geometry", "Image.addBands",
    "Image.clip", "Image.reduceRegion",
}
_IMAGE_BINARY = {
    "add": "add", "subtract": "subtract", "multiply": "multiply", "divide": "divide",
    "pow": "power", "mod": "mod", "eq": "eq", "neq": "neq", "gt": "gt",
    "gte": "gte", "lt": "lt", "lte": "lte", "and": "and", "or": "or",
    "min": "min2", "max": "max2",
}
_IMAGE_UNARY = {
    "abs": "absolute", "sqrt": "sqrt", "log": "log", "log10": "log10",
    "exp": "exp", "round": "round", "floor": "floor", "ceil": "ceil",
    "sin": "sin", "cos": "cos", "tan": "tan", "not": "not",
}
_METADATA_NAMES = {"Image.get", "Image.copyProperties"}


def handles_image(name):
    return (
        name in _IMAGE_NAMES
        or name.startswith("Reducer.")
        or name.startswith("Image.") and name not in _METADATA_NAMES
    )


def invoke_image(translator, name, arguments):
    a = arguments
    if name == "Image.select":
        translator.allowed(a, {"input", "bandSelectors", "newNames"})
        return translator.select(a["input"], a["bandSelectors"], a.get("newNames"))
    if name == "Image.rename":
        translator.allowed(a, {"input", "names"})
        image = a["input"]
        return translator.select(image, list(range(len(image.bands))), a["names"])
    if name == "Image.bandNames":
        return [band for band, _ in a["image"].bands]
    if name == "Image.toFloat":
        translator.allowed(a, {"value"})
        return unary(a["value"], "to_float")
    if name == "Image.toDouble":
        translator.allowed(a, {"value"})
        return unary(a["value"], "to_double")
    if name == "Image.normalizedDifference":
        translator.allowed(a, {"input", "bandNames"})
        image = as_image(a["input"])
        chosen = a.get("bandNames") or [name for name, _ in image.bands[:2]]
        if len(chosen) != 2:
            fail("normalizedDifference requires two bands")
        left, right = [pixel for _, pixel in translator.select(image, chosen).bands]
        negative = Pixel("or", (Pixel("lt", (left, const(0)), True), Pixel("lt", (right, const(0)), True)), True)
        denominator = Pixel("add", (left, right))
        valid = Pixel(
            "and",
            (Pixel("not", (negative,), True), Pixel("neq", (denominator, const(0)), True)),
            True,
        )
        ratio = Pixel("divide", (Pixel("subtract", (left, right)), denominator))
        return Image(
            [("nd", Pixel("if", (valid, ratio, const(None))))],
            {}, image.source, image.mapped, False,
            footprint=image.footprint, footprint_is_absolute=image.footprint_is_absolute,
        )
    if name == "Image.parseExpression":
        translator.allowed(a, {"expression", "argName", "vars"})
        from .ir import ParsedExpression

        return ParsedExpression(a["expression"], a["argName"], a["vars"])
    if name == "Image.updateMask":
        translator.allowed(a, {"image", "mask"})
        image_input, mask_input = as_image(a["image"]), as_image(a["mask"])
        if len(mask_input.bands) not in {1, len(image_input.bands)}:
            fail("updateMask needs one broadcast mask band or the same number of bands as the Image")
        image, _, matched = pairs(a["image"], a["mask"])
        for _, _, mask in matched:
            if not mask.boolean and not (mask.op == "constant" and mask.args[0] in (0, 1)):
                fail("updateMask currently supports binary masks only; fractional masks and opacity are unsupported")
        return replace(image, bands=[(name, Pixel("if", (mask, pixel, const(None)))) for name, pixel, mask in matched])
    if name == "Image.mask":
        translator.allowed(a, {"image", "mask"})
        if "mask" in a:
            fail("Image.mask setter is unsupported; use updateMask")
        return unary(unary(a["image"], "is_nodata"), "not")
    if name == "Image.where":
        translator.allowed(a, {"input", "test", "value"})
        image, test, value = as_image(a["input"]), as_image(a["test"]), as_image(a["value"])
        if len(test.bands) not in {1, len(image.bands)} or len(value.bands) not in {1, len(image.bands)}:
            fail("where test/value require one broadcast band or the input band count")
        bands = []
        for index, (name, pixel) in enumerate(image.bands):
            test_pixel = test.bands[0 if len(test.bands) == 1 else index][1]
            value_pixel = value.bands[0 if len(value.bands) == 1 else index][1]
            condition = Pixel(
                "if",
                (Pixel("is_nodata", (test_pixel,), True), const(False), Pixel("neq", (test_pixel, const(0)), True)),
                True,
            )
            condition = Pixel("if", (Pixel("is_nodata", (value_pixel,), True), const(False), condition), True)
            replacement = Pixel("if", (condition, value_pixel, pixel))
            bands.append((name, Pixel("preserve_mask", (replacement, pixel))))
        return replace(image, bands=bands)
    if name in {"Image.clamp", "Image.unitScale"}:
        translator.allowed(a, {"input", "low", "high"})
        low, high = a["low"], a["high"]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (low, high)) or high <= low:
            fail("clamp/unitScale requires finite low < high")
        image = as_image(a["input"])
        if name.endswith("unitScale"):
            return binary(binary(image, low, "subtract"), high - low, "divide")
        return binary(binary(image, low, "max2"), high, "min2")
    if name == "Image.reduce":
        translator.allowed(a, {"image", "reducer"})
        image, reducer = as_image(a["image"]), a["reducer"]
        if not isinstance(reducer, Reducer):
            fail("Image.reduce requires a supported single-output Reducer")
        output = "stdDev" if reducer.name == "sd" else reducer.name
        pixels = tuple(pixel for _, pixel in image.bands)
        return replace(image, bands=[(output, Pixel("reduce_bands", (pixels, reducer.name)))])
    if name == "Image.date":
        translator.allowed(a, {"image"})
        from .date_values import millis

        return millis(translator.invoke("Element.get", {"object": a["image"], "property": "system:time_start"}))
    if name in {"Image.geometry", "Feature.geometry", "Collection.geometry"}:
        translator.allowed(a, {"feature", "collection", "maxError", "proj", "geodesics"})
        if a.get("proj") not in (None, "EPSG:4326") or a.get("geodesics") is True:
            fail("Geometry extraction currently supports planar EPSG:4326 only")
        return translator.footprint(a.get("feature", a.get("collection")))
    if name == "Image.addBands":
        translator.allowed(a, {"dstImg", "srcImg", "names", "overwrite"})
        image, source = as_image(a["dstImg"]), as_image(a["srcImg"])
        if a.get("names") is not None:
            source = translator.select(source, a["names"])
        bands = list(image.bands)
        for band_name, pixel in source.bands:
            existing = [current for current, _ in bands]
            if band_name in existing and a.get("overwrite", False):
                bands[existing.index(band_name)] = (band_name, pixel)
            else:
                base, suffix = band_name, 1
                while band_name in existing:
                    band_name = f"{base}_{suffix}"
                    suffix += 1
                bands.append((band_name, pixel))
        return replace(image, bands=bands, source=image.source or source.source)
    if name == "Image.clip":
        translator.allowed(a, {"input", "geometry"})
        image, geometry = as_image(a["input"]), a["geometry"]
        if geometry.get("type") == "Feature":
            geometry = geometry["geometry"]
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            fail("clip supports Polygon/MultiPolygon only")
        from shapely.geometry import mapping, shape

        footprint = mapping(shape(image.footprint).intersection(shape(geometry))) if image.footprint else geometry
        return replace(image, bands=[(name, Pixel("clip", (pixel, geometry))) for name, pixel in image.bands], footprint=footprint)
    if name == "Image.reduceRegion":
        translator.allowed(a, {"image", "reducer", "geometry", "scale", "crs", "crsTransform", "bestEffort", "maxPixels", "tileScale"})
        if a.get("crsTransform") is not None or a.get("bestEffort") or a.get("tileScale", 1) != 1:
            fail("reduceRegion crsTransform, bestEffort and custom tileScale are unsupported")
        image = as_image(a["image"])
        geometry = a.get("geometry") or translator.options.get("region")
        if not geometry:
            fail("reduceRegion requires an explicit geometry")
        reducer = a["reducer"]
        if not isinstance(reducer, Reducer):
            fail("Expected a supported Reducer")
        options = {**translator.options, **{key: a[key] for key in ("scale", "crs", "maxPixels") if key in a}}
        translator.warn("Regional reduction uses local GeoTrellis rasterization; fractional boundary/mask weighting has not been verified against Earth Engine.")
        return Region(image, geometry, reducer, options)
    if name.startswith("Reducer."):
        operation = name.split(".", 1)[1]
        if operation == "unweighted":
            fail("Reducer.unweighted requires a verified rasterization policy and is not yet supported")
        if operation not in {"mean", "median", "min", "max", "sum", "count", "first", "last", "sampleStdDev"}:
            fail(f"Unsupported reducer: {name}; stdDev cannot be mapped to sample standard deviation")
        if a:
            fail(f"Unsupported parameters for {name}")
        return Reducer("sd" if operation == "sampleStdDev" else operation)
    if name.startswith("Image.") and name[6:] in _IMAGE_BINARY:
        translator.allowed(a, {"image1", "image2"})
        return binary(a["image1"], a["image2"], _IMAGE_BINARY[name[6:]])
    if name.startswith("Image.") and name[6:] in _IMAGE_UNARY:
        translator.allowed(a, {"value", "image"})
        return unary(a.get("value", a.get("image")), _IMAGE_UNARY[name[6:]])
    fail(f"Unsupported Earth Engine algorithm: {name}")
