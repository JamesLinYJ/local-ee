"""Run pointwise science operations on explicit fractional-mask carriers.

This offline example states the local Wave66 policy: one direct fractional
carrier passed through an operation with an unmasked scalar keeps its weight;
invalid math results become NoData. It does not claim Google parity for that
mask policy or define the unresolved two-fractional-input case.
"""
from __future__ import annotations


SYNTHETIC_VERSION = "local-ee-mask-math-wave66/v1"
FIXTURE_PATH = "tests/fixtures/ee-mask-math-wave66-v1.json"


def _append(images, name, image):
    images.append(image.rename(name))


def _masked_source(ee, source, band):
    return source.select(band).toDouble().updateMask(source.select(f"{band}_weight"))


def _result_images(ee, source, fixture):
    operations = fixture["operations"]
    result = []
    masked = {band: _masked_source(ee, source, band) for band in fixture["bands"]}

    for band, image in masked.items():
        for name in operations["unary"]:
            _append(result, f"{band}_{name.lower()}", getattr(image, name)())

    band = "wide"
    image = masked[band]
    constant = ee.Image.constant(operations["binary_constant"])
    for name in operations["binary"]:
        method = getattr(image, name)
        _append(result, f"{band}_{name.lower()}_right", method(constant))
        _append(result, f"{band}_{name.lower()}_left", getattr(constant, name)(image))

    red = masked["red"]
    zero = ee.Image.constant(operations["logic_zero"])
    for name in ("And", "Or"):
        _append(result, f"red_{name.lower()}_zero", getattr(red, name)(zero))
        _append(result, f"red_zero_{name.lower()}", getattr(zero, name)(red))

    low, high = operations["clamp"]
    _append(result, "red_clamp", red.clamp(low, high))
    low, high = operations["unit_scale"]
    _append(result, "red_unit_scale", red.unitScale(low, high))

    wide_float = masked["wide"].toFloat()
    for name in operations["pixel_math_unary"]:
        _append(result, f"wide_pixel_{name.lower()}", getattr(wide_float, name)())
    atan2_constant = ee.Image.constant(operations["atan2_constant"]).toFloat()
    for name in operations["pixel_math_binary"]:
        _append(result, f"wide_pixel_{name.lower()}_right",
                getattr(wide_float, name)(atan2_constant))
        _append(result, f"wide_pixel_{name.lower()}_left",
                getattr(atan2_constant, name)(wide_float))

    _append(result, f"{operations['float32_band']}_to_float", wide_float)
    _append(result, f"{operations['float32_band']}_float32_{operations['float32_function'].lower()}",
            getattr(wide_float, operations["float32_function"])())
    return result


def build_operation_images(ee, image, fixture):
    source = ee.Image(image)
    results = _result_images(ee, source, fixture)
    names = _result_names(fixture)
    if len(results) != len(names) or len(set(names)) != len(names):
        raise ValueError("operation result names must match the generated images exactly")
    return dict(zip(names, results))


def build_workflow(ee, image, fixture):
    result_map = build_operation_images(ee, image, fixture)
    selected = set(fixture["sample_outputs"])
    sampled = [(name, result_map[name]) for name in fixture["sample_outputs"]]
    if len(sampled) != len(selected):
        raise ValueError("sample_outputs must name distinct generated result bands")
    values = ee.Image.cat(*[result for _name, result in sampled])
    weights = ee.Image.cat(*[result.mask().rename(f"mask_{name}")
                             for name, result in sampled])
    region = ee.Geometry(fixture["sample_region"])
    return {
        "values": values,
        "weights": weights,
        "values_sample": values.sample(region=region, dropNulls=False, geometries=True),
        "weights_sample": weights.sample(region=region, dropNulls=False, geometries=True),
    }


def _result_names(fixture):
    names = []
    for band in fixture["bands"]:
        names.extend(f"{band}_{op.lower()}" for op in fixture["operations"]["unary"])
    names.extend(
        f"wide_{op.lower()}_{side}"
        for op in fixture["operations"]["binary"]
        for side in ("right", "left")
    )
    names.extend(("red_and_zero", "red_zero_and", "red_or_zero", "red_zero_or",
                  "red_clamp", "red_unit_scale"))
    names.extend(f"wide_pixel_{op.lower()}" for op in fixture["operations"]["pixel_math_unary"])
    names.extend(
        f"wide_pixel_{op.lower()}_{side}"
        for op in fixture["operations"]["pixel_math_binary"]
        for side in ("right", "left")
    )
    names.extend(("wide_to_float",
                  "wide_float32_asin"))
    return names


def synthetic_metadata(fixture):
    bands = [*fixture["bands"], *fixture["weight_bands"]]
    collection = {"id": fixture["source_id"], "cube:dimensions": {
        "bands": {"values": bands},
    }}
    grid = fixture["grid"]
    item = {
        "id": "wave66-synthetic-source",
        "bbox": [grid["xmin"], grid["ymin"], grid["xmax"], grid["ymax"]],
        "geometry": {"type": "Polygon", "coordinates": [[
            [grid["xmin"], grid["ymin"]], [grid["xmax"], grid["ymin"]],
            [grid["xmax"], grid["ymax"]], [grid["xmin"], grid["ymax"]],
            [grid["xmin"], grid["ymin"]],
        ]]},
        "properties": {
            "system:index": "wave66-synthetic-source", "system:time_start": 1,
            "proj:code": "EPSG:4326", "proj:transform": [1, 0, 0, 0, -1, 2],
        },
        "assets": {
            band: {"proj:shape": [2, 4], "proj:epsg": 4326,
                   "proj:transform": [1, 0, 0, 0, -1, 2]}
            for band in bands
        },
    }
    return [{"id": collection["id"], **collection}], {collection["id"]: [item]}
