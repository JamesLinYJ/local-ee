"""Bounded Image integer casts and bitwise Pixel construction."""
from __future__ import annotations

import math
from dataclasses import replace

from gee.integer_values_spec import (
    constant_operand,
    evaluate_integer_values,
    prepare_integer_values_spec,
)
from gee.float64_values_contract import (
    FLOAT64_ARITIES,
    FLOAT64_BOOLEAN,
    evaluate_float64_values,
)

from .ir import Image, Pixel, as_image, clip_footprint_after_first_input, fail, pairs


_CASTS = {
    "byte": "uint8", "toByte": "uint8", "uint8": "uint8", "toUint8": "uint8",
    "int8": "int8", "toInt8": "int8", "short": "int16", "toShort": "int16",
    "int16": "int16", "toInt16": "int16", "int": "int32", "toInt": "int32",
    "int32": "int32", "toInt32": "int32", "uint16": "uint16", "toUint16": "uint16",
    "uint32": "uint32", "toUint32": "uint32", "long": "int64", "toLong": "int64",
    "int64": "int64", "toInt64": "int64",
}
_BITWISE = {
    "bitwiseAnd": "bit_and", "bitwise_and": "bit_and",
    "bitwiseOr": "bit_or", "bitwise_or": "bit_or",
    "bitwiseXor": "bit_xor", "bitwise_xor": "bit_xor",
    "bitwiseNot": "bit_not", "bitwise_not": "bit_not",
    "bitCount": "bit_count", "leftShift": "left_shift", "left_shift": "left_shift",
    "rightShift": "right_shift", "right_shift": "right_shift",
}
IMAGE_INTEGER_FUNCTIONS = frozenset(
    {"Image." + name for name in (*_CASTS, *_BITWISE)}
)
_COMPARISONS = frozenset({"eq", "neq", "lt", "lte", "gt", "gte"})
_MAX_BANDS = 10_000
_MAX_NAME_CHARS = 10_000
_MAX_WORK = 50_000


def _shape(value, label):
    if isinstance(value, Image):
        amount, scan = len(value.bands), 0
    elif type(value) is list:
        amount, scan = len(value), len(value)
    elif type(value) in (int, float, bool):
        amount, scan = 1, 0
    else:
        fail(f"{label} requires an Image or finite numeric operand")
    if not amount:
        fail(f"{label} requires at least one band per operand")
    if amount > _MAX_BANDS:
        fail(f"{label} operand exceeds {_MAX_BANDS} bands")
    return amount, scan


def _validate(value, label):
    if isinstance(value, Image):
        if type(value.bands) is not list:
            fail(f"{label} requires named scalar Image bands")
        for band in value.bands:
            if (type(band) is not tuple or len(band) != 2 or type(band[0]) is not str
                    or not band[0] or len(band[0]) > _MAX_NAME_CHARS
                    or not isinstance(band[1], Pixel)):
                fail(f"{label} requires named scalar Image bands")
        return
    values = value if type(value) is list else (value,)
    for item in values:
        if type(item) not in (int, float) or type(item) is bool:
            fail(f"{label} operands must be finite numeric values")
        if type(item) is float and not math.isfinite(item):
            fail(f"{label} operands must be finite numeric values")


def _literal(pixel):
    depth = 0
    while (isinstance(pixel, Pixel) and pixel.op == "to_double"
           and len(pixel.args) == 1 and depth < 96):
        pixel = pixel.args[0]
        depth += 1
    if (isinstance(pixel, Pixel) and pixel.op == "constant" and len(pixel.args) == 1
            and pixel.args[0] is not None):
        return True, pixel.args[0]
    return False, None


def _literal_value(pixel, *, allow_boolean=False):
    """Read a scalar, unwrapping only pure Double casts.

    Boolean literals are numeric 0/1 only when their Pixel carries the explicit
    Boolean marker. Raw Python booleans never enter the numeric wire by
    accidental coercion.
    """
    is_literal, value = _literal(pixel)
    if not is_literal or type(value) is not bool or not allow_boolean:
        return is_literal, value
    current = pixel
    depth = 0
    while (isinstance(current, Pixel) and current.op == "to_double"
           and len(current.args) == 1 and depth < 96):
        current = current.args[0]
        depth += 1
    if isinstance(current, Pixel) and current.boolean:
        return True, int(value)
    return True, value


def _pixel(translator, api_name, op, operands, dtype=None, *, precharged=False,
           known_boolean_literals=False):
    literal_flags = [
        _literal_value(operand, allow_boolean=known_boolean_literals)
        for operand in operands
    ]
    if all(is_literal for is_literal, _value in literal_flags):
        try:
            result = evaluate_integer_values(
                op, [value for _is_literal, value in literal_flags], dtype=dtype,
            )
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            from .ir import UnsupportedEEError

            if isinstance(error, UnsupportedEEError):
                raise
            fail(f"{api_name} has unsupported integer values: {error}")
        constant = (Pixel("constant", (bool(result),), True) if op in _COMPARISONS
                    else Pixel("constant", (result,)))
        # Preserve the native numeric boundary after static folding so a
        # source-bound constant never drifts through a Float32 callback.
        return constant if op in _COMPARISONS else Pixel("to_double", (constant,))

    if not precharged:
        reserve = 160 + 32 * len(operands)
        if type(translator.steps) is not int or translator.steps + reserve > _MAX_WORK:
            fail(f"{api_name} exceeds the shared 50000-step compilation work budget")
        translator.steps += reserve
    dynamic, indexes = [], {}
    descriptors = []
    try:
        for operand in operands:
            is_literal, value = _literal_value(
                operand, allow_boolean=known_boolean_literals,
            )
            if is_literal:
                descriptors.append(constant_operand(value))
                continue
            identity = id(operand)
            index = indexes.get(identity)
            if index is None:
                index = len(dynamic)
                indexes[identity] = index
                dynamic.append(operand)
            descriptors.append({"band": index})
        # The descriptor slots are at most two short dictionaries; the
        # reservation above covers their copies and canonical JSON encoding.
        spec = prepare_integer_values_spec(op, descriptors, dtype=dtype)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        from .ir import UnsupportedEEError

        if isinstance(error, UnsupportedEEError):
            raise
        fail(f"{api_name} has unsupported integer values: {error}")
    return Pixel("integer_values", (tuple(dynamic), spec), op in _COMPARISONS)


def _float64_pixel(translator, api_name, op, operands):
    """Build a typed Double/logical Pixel using the closed Float64 contract."""
    if op not in FLOAT64_ARITIES or len(operands) != FLOAT64_ARITIES[op]:
        fail(f"{api_name} has an invalid Float64 operand count")
    literals = [_literal_value(value, allow_boolean=True) for value in operands]
    boolean = op in FLOAT64_BOOLEAN
    if all(is_literal for is_literal, _value in literals):
        try:
            result = evaluate_float64_values(
                op, [value for _is_literal, value in literals],
            )
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            fail(f"{api_name} has unsupported Float64 values: {error}")
        if result is None:
            return Pixel("constant", (None,), boolean)
        if boolean:
            return Pixel("constant", (bool(result),), True)
        constant = Pixel("constant", (result,))
        # Retain the Double type even for integral results such as round/floor.
        return Pixel("to_double", (constant,))

    reserve = 160 + 32 * len(operands)
    if type(translator.steps) is not int or translator.steps + reserve > _MAX_WORK:
        fail(f"{api_name} exceeds the shared 50000-step compilation work budget")
    translator.steps += reserve
    dynamic, indexes = [], {}
    descriptors = []
    try:
        for operand in operands:
            is_literal, value = _literal_value(operand, allow_boolean=True)
            if is_literal:
                descriptors.append(constant_operand(value))
                continue
            identity = id(operand)
            index = indexes.get(identity)
            if index is None:
                index = len(dynamic)
                indexes[identity] = index
                dynamic.append(operand)
            descriptors.append({"band": index})
        spec = prepare_integer_values_spec(op, descriptors, dtype=None)
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        fail(f"{api_name} has unsupported Float64 values: {error}")
    return Pixel("integer_values", (tuple(dynamic), spec), boolean)


def invoke_image_integer(translator, name, arguments):
    """Lower pinned Image integer methods while preserving SDK pair order."""
    short_name = name.removeprefix("Image.")
    cast = short_name in _CASTS
    op = "cast" if cast else _BITWISE[short_name]
    dtype = _CASTS.get(short_name)
    arity = 1 if cast or op in {"bit_not", "bit_count"} else 2
    parameters = ("value",) if arity == 1 else ("image1", "image2")
    translator.allowed(arguments, set(parameters))
    missing = [parameter for parameter in parameters if parameter not in arguments]
    if missing:
        fail(f"{name} requires {', '.join(missing)}")

    values = [arguments[parameter] for parameter in parameters]
    shapes = [_shape(value, name) for value in values]
    counts = [amount for amount, _scan in shapes]
    if arity == 2 and counts[0] != 1 and counts[1] != 1 and counts[0] != counts[1]:
        fail("Image operands need equal band counts or a single broadcast band")
    output_count = max(counts)
    # Precharge both operand/list scans and the pair/output copies before
    # as_image(), pairs(), or a per-band Pixel/spec is allocated.
    property_work = 0
    for value in values:
        if isinstance(value, Image):
            if type(value.props) is not dict:
                fail(f"{name} requires finite Image metadata")
            property_work += len(value.props)
    # The band-count term pays for validating names/Pixel objects and the
    # subsequent per-band literal/dynamic scan. Do not scan the band list to
    # estimate name costs before charging this reservation.
    work = 2 * sum(scan for _amount, scan in shapes) + 2 * sum(counts)
    work += property_work + 5 * output_count
    if type(translator.steps) is not int or translator.steps + work > _MAX_WORK:
        fail(f"{name} exceeds the shared 50000-step compilation work budget")
    translator.steps += work
    for value, parameter in zip(values, parameters):
        _validate(value, f"{name} {parameter}")

    def band_pixel(value, index):
        if isinstance(value, Image):
            return value.bands[index if len(value.bands) > 1 else 0][1]
        return None

    if arity == 1:
        dynamic_outputs = sum(not _literal(pixel)[0]
                              for pixel in (band_pixel(values[0], i)
                                            for i in range(counts[0]))) if isinstance(values[0], Image) else 0
    else:
        dynamic_outputs = 0
        for index in range(output_count):
            left_pixel, right_pixel = band_pixel(values[0], index), band_pixel(values[1], index)
            left_literal = left_pixel is None or _literal(left_pixel)[0]
            right_literal = right_pixel is None or _literal(right_pixel)[0]
            if not (left_literal and right_literal):
                dynamic_outputs += 1
    encoding_work = 160 * dynamic_outputs
    if translator.steps + encoding_work > _MAX_WORK:
        fail(f"{name} exceeds the shared 50000-step compilation work budget")
    translator.steps += encoding_work

    try:
        if arity == 1:
            image = as_image(values[0])
            bands = [
                (band_name, _pixel(
                    translator, name, op, (pixel,), dtype, precharged=True,
                ))
                for band_name, pixel in image.bands
            ]
            return replace(image, bands=bands)
        left, right, matched = pairs(values[0], values[1])
        bands = [
            (band_name, _pixel(
                translator, name, op, (x, y), dtype, precharged=True,
            ))
            for band_name, x, y in matched
        ]
        return Image(
            bands, dict(left.props), left.source or right.source,
            left.mapped or right.mapped, left.inherit_props, left.copied_props,
            left.footprint, left.footprint_is_absolute,
            clip_footprint_after_first_input(
                left.clip_footprint, right.clip_footprint,
            ),
        )
    except OverflowError:
        fail(f"{name} operands must be finite numeric values")
