"""Bounded weighted Image.reduceNeighborhood compilation."""
from __future__ import annotations

from dataclasses import replace

from .ir import Image, Pixel, Reducer, fail


_MAX_WORK = 50_000
_MAX_BANDS = 10_000
_MAX_NAME_CHARS = 10_000
_UNIT_WEIGHT = frozenset({
    "sampleVariance", "sampleStdDev", "product", "median", "mode",
})


def _charge(translator, amount: int, label: str) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or type(amount) is not int or amount < 0
            or steps + amount > _MAX_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _kernel_coefficients(translator, kernel, input_weight, force_unit):
    from .kernel_values import KernelSpec, validate_kernel

    if type(kernel) is not KernelSpec:
        fail("reduceNeighborhood requires a validated fixed pixel Kernel")
    kernel = validate_kernel(translator, kernel)
    cells = kernel.width * kernel.height
    _charge(translator, 2 + cells, "Neighborhood kernel scan")
    coefficients = []
    for row_index, row in enumerate(kernel.weights):
        for column_index, weight in enumerate(row):
            if type(weight) is not float:
                fail("Neighborhood kernel weights must be finite Float64 values")
            if weight < 0:
                fail("Neighborhood kernel weights must be nonnegative")
            if weight == 0:
                continue
            dx, dy = column_index - kernel.x, row_index - kernel.y
            if abs(dx) > 32 or abs(dy) > 32:
                fail("Neighborhood kernel offsets must be within 32 pixels")
            if force_unit or input_weight == "mask":
                effective = 1.0
            elif input_weight == "min":
                effective = min(1.0, weight)
            else:
                effective = weight
            if not (effective > 0.0):
                fail("Neighborhood kernel must contain positive support")
            coefficients.append((dx, dy, effective))
    if not coefficients or len(coefficients) > 1089:
        fail("Neighborhood kernel must contain 1 to 1089 positive support cells")
    coefficients.sort(key=lambda item: (item[1], item[0]))
    return tuple(coefficients)


def _unit_coefficients(coefficients):
    return tuple((dx, dy, 1.0) for dx, dy, _ in coefficients)


def _coefficients_for_operation(coefficients, operation):
    if operation not in _UNIT_WEIGHT:
        return coefficients
    first = coefficients[0][2]
    if any(weight != first for _, _, weight in coefficients[1:]):
        fail(f"reduceNeighborhood {operation} supports only uniform effective weights")
    # These paths consume support, not a common positive scale. Keep this
    # conversion local to the one operation so weighted siblings retain the
    # kernel's actual magnitudes.
    return _unit_coefficients(coefficients)


def _is_simple_legacy_reducer(reducer, operation):
    if operation not in {"mean", "min", "max", "median", "mode"}:
        return False
    if type(reducer) is Reducer:
        return not reducer.unweighted
    # The opaque Reducer.unweighted wrapper is neighborhood-only. A single
    # legacy reducer can still use the established focal graph because its
    # neighborhood support is already represented by unit coefficients.
    from .neighborhood_reducer_plan import NeighborhoodUnweighted

    if type(reducer) is NeighborhoodUnweighted:
        return len(reducer.plan) == 1 and reducer.plan[0][1] == operation
    from .composed_reducer_spec import ReducerSpec, ScalarReducerLeaf
    from .quantile_reducer_spec import QuantileReducerLeaf

    if type(reducer) is ReducerSpec and reducer.kind == "leaf":
        if type(reducer.leaf) is ScalarReducerLeaf:
            return reducer.leaf.name == operation
        if type(reducer.leaf) is QuantileReducerLeaf:
            return (operation == "mode" and reducer.leaf.name == "Reducer.mode"
                    and reducer.leaf.max_raw is None)
    return False


def _prepare_spec(translator, operation, coefficients, skip_masked):
    from ...neighborhood_spec import prepare_neighborhood_spec

    _charge(translator, 128 + 28 * len(coefficients) + len(operation),
            "Neighborhood specification encoding")
    try:
        return prepare_neighborhood_spec(operation, coefficients, skip_masked)
    except ValueError as error:
        fail(f"Invalid reduceNeighborhood specification: {error}")


def _focal_spec(translator, operation, coefficients, skip_masked):
    from ...focal_spec import prepare_focal_spec

    offsets = tuple((dx, dy) for dx, dy, _ in coefficients)
    _charge(translator, 128 + 12 * len(offsets), "Legacy neighborhood specification")
    try:
        return prepare_focal_spec(operation, offsets, iterations=1,
                                  skip_masked=skip_masked)
    except ValueError as error:
        fail(f"Invalid legacy neighborhood specification: {error}")


def _measure_image(translator, image):
    if not isinstance(image, Image) or type(image.bands) is not list:
        fail("Image.reduceNeighborhood requires an Image with scalar bands")
    if not 1 <= len(image.bands) <= _MAX_BANDS:
        fail("Image.reduceNeighborhood requires 1..10000 scalar bands")
    names = []
    pixels = []
    seen = set()
    for band in image.bands:
        if type(band) is not tuple or len(band) != 2:
            fail("Image.reduceNeighborhood contains an invalid band descriptor")
        name, pixel = band
        if (type(name) is not str or not name or len(name) > _MAX_NAME_CHARS
                or not isinstance(pixel, Pixel)):
            fail("Image.reduceNeighborhood requires bounded scalar image bands")
        _charge(translator, 1 + len(name), "Neighborhood image band scan")
        if name in seen:
            fail("Image.reduceNeighborhood requires unique input band names")
        seen.add(name)
        names.append(name)
        pixels.append(pixel)
    return tuple(names), tuple(pixels)


def _output_names(translator, input_names, plan):
    count = len(input_names) * len(plan)
    if not 1 <= count <= _MAX_BANDS:
        fail("Image.reduceNeighborhood output exceeds 10000 bands")
    # Reserve the Cartesian scan before reading every input/output name pair.
    _charge(translator, count, "Neighborhood output-name scan")
    chars = 0
    for input_name in input_names:
        for output_name, _ in plan:
            length = len(input_name) + 1 + len(output_name)
            if length > _MAX_NAME_CHARS:
                fail("Image.reduceNeighborhood output band name exceeds the bounded length")
            chars += length
    # Reserve string construction and the uniqueness pass before allocating
    # the Cartesian output-name tuple and its set.
    _charge(translator, count + chars, "Neighborhood output plan")
    names = tuple(input_name + "_" + output_name
                  for input_name in input_names for output_name, _ in plan)
    _charge(translator, count, "Neighborhood output-name uniqueness scan")
    if len(set(names)) != len(names):
        fail("Image.reduceNeighborhood output band names must be unique")
    return names


def _validate_unweighted_wrapper(reducer):
    from .neighborhood_reducer_plan import NeighborhoodUnweighted

    return type(reducer) is NeighborhoodUnweighted


def invoke_image_neighborhood(translator, arguments):
    """Lower one scalar Image.reduceNeighborhood call to bounded Pixel IR."""
    translator.allowed(arguments, {
        "image", "reducer", "kernel", "inputWeight", "skipMasked", "optimization",
    })
    for required in ("image", "reducer", "kernel"):
        if required not in arguments:
            fail(f"Image.reduceNeighborhood requires {required}")
    if arguments.get("optimization") is not None:
        fail("Image.reduceNeighborhood optimization strategies are unsupported")
    input_weight = arguments.get("inputWeight", "kernel")
    if type(input_weight) is not str or input_weight not in {"kernel", "mask", "min"}:
        fail("Image.reduceNeighborhood inputWeight must be kernel, mask or min")
    skip_masked = arguments.get("skipMasked", True)
    if type(skip_masked) is not bool:
        fail("Image.reduceNeighborhood skipMasked must be boolean")

    reducer = arguments["reducer"]
    wrapper_unweighted = _validate_unweighted_wrapper(reducer)
    from .neighborhood_reducer_plan import resolve_neighborhood_reducer

    plan, direct_unweighted = resolve_neighborhood_reducer(translator, reducer)
    force_unit = wrapper_unweighted or direct_unweighted
    coefficients = _kernel_coefficients(
        translator, arguments["kernel"], input_weight, force_unit,
    )

    # Deduplicate operation specs before the coefficient walks. Each distinct
    # operation gets an independent effective-weight view so a unit-only
    # sibling can never normalize a weighted sum/mean/dispersion operation.
    _charge(translator, len(plan), "Neighborhood operation coefficient plan")
    distinct_operations = []
    seen_operations = set()
    for _, operation in plan:
        if operation not in seen_operations:
            seen_operations.add(operation)
            distinct_operations.append(operation)
    operation_coefficients = {}
    for operation in distinct_operations:
        # This covers the uniform-weight scan and a worst-case unit tuple copy
        # before _coefficients_for_operation inspects the bounded coefficients.
        _charge(translator, 1 + 2 * len(coefficients),
                "Neighborhood operation coefficient scan")
        operation_coefficients[operation] = _coefficients_for_operation(
            coefficients, operation,
        )

    image = arguments["image"]
    names, pixels = _measure_image(translator, image)
    output_names = _output_names(translator, names, plan)

    simple_legacy = (
        len(plan) == 1
        and _is_simple_legacy_reducer(reducer, plan[0][1])
        and all(weight == operation_coefficients[plan[0][1]][0][2]
                for _, _, weight in operation_coefficients[plan[0][1]])
        and plan[0][1] in {"mean", "min", "max", "median", "mode"}
    )
    if simple_legacy:
        spec = _focal_spec(
            translator, plan[0][1], operation_coefficients[plan[0][1]], skip_masked,
        )
        bands = [(output_names[index], Pixel("focal", (pixel, spec)))
                 for index, pixel in enumerate(pixels)]
        return replace(image, bands=bands)

    specs = {}
    bands = []
    for input_index, (band_name, pixel) in enumerate(zip(names, pixels)):
        for output_index, (output_name, operation) in enumerate(plan):
            spec = specs.get(operation)
            if spec is None:
                spec = _prepare_spec(
                    translator, operation, operation_coefficients[operation], skip_masked,
                )
                specs[operation] = spec
            output_index_global = input_index * len(plan) + output_index
            bands.append((output_names[output_index_global],
                          Pixel("neighborhood", (pixel, spec))))
    return replace(image, bands=bands)
