"""Bounded static Earth Engine Kernel constructors and immutable values."""
from __future__ import annotations

from dataclasses import dataclass
import math
from fractions import Fraction

from .array_core import MAX_ARRAY_WORK
from .ir import fail


MAX_KERNEL_WIDTH = 33
MAX_KERNEL_HEIGHT = 33
MAX_KERNEL_CELLS = 1089
MAX_EXACT_INTEGER = 2**53

KERNEL_FUNCTIONS = {
    "Kernel.fixed", "Kernel.circle", "Kernel.square", "Kernel.rectangle",
    "Kernel.plus", "Kernel.cross", "Kernel.diamond", "Kernel.octagon",
}


@dataclass(frozen=True)
class KernelSpec:
    """Owned finite weights and zero-based focus, independent of raster lowering."""

    weights: tuple[tuple[float, ...], ...]
    x: int
    y: int

    @property
    def width(self) -> int:
        return len(self.weights[0])

    @property
    def height(self) -> int:
        return len(self.weights)


def _charge(translator, amount: int, label: str = "Kernel") -> None:
    if (type(amount) is not int or amount < 0 or amount > MAX_ARRAY_WORK
            or translator.steps + amount > MAX_ARRAY_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps += amount


def _number(value, label: str) -> float:
    if type(value) is int:
        if abs(value) > MAX_EXACT_INTEGER:
            fail(f"{label} integer is outside the exact Float64 domain")
        return float(value)
    if type(value) is not float or not math.isfinite(value):
        fail(f"{label} must be a finite real number")
    return value


def _integer(value, label: str) -> int:
    number = _number(value, label)
    if not number.is_integer():
        fail(f"{label} must be an integer")
    return int(number)


def _boolean(value, label: str) -> bool:
    if type(value) is not bool:
        fail(f"{label} must be a boolean")
    return value


def _finite_sum(values: list[float]) -> float:
    try:
        result = math.fsum(values)
    except OverflowError:
        try:
            result = float(sum((Fraction.from_float(v) for v in values), Fraction()))
        except OverflowError:
            fail("Kernel weight sum exceeds the finite Float64 domain")
    if not math.isfinite(result):
        fail("Kernel weight sum exceeds the finite Float64 domain")
    return result


def _finish(translator, values, x: int, y: int, normalize: bool,
            magnitude: float = 1.0) -> KernelSpec:
    """Precharge normalization and owned tuple materialization."""
    height, width = len(values), len(values[0])
    cells = height * width
    _charge(translator, 2 + 5 * cells)
    flat = [value for row in values for value in row]
    divisor = _finite_sum(flat) if normalize else 1.0
    if normalize and divisor == 0.0:
        fail("Kernel cannot normalize weights whose sum is zero")
    rows = []
    for row in values:
        output = tuple((value / divisor) * magnitude if normalize
                       else value * magnitude for value in row)
        if not all(math.isfinite(value) for value in output):
            fail("Kernel weights must remain finite after normalization and magnitude")
        rows.append(output)
    return KernelSpec(tuple(rows), x, y)


def _fixed(translator, arguments) -> KernelSpec:
    translator.allowed(arguments, {"width", "height", "weights", "x", "y", "normalize"})
    if "weights" not in arguments:
        fail("Kernel.fixed requires 2-D weights")
    weights = arguments["weights"]
    if type(weights) not in (list, tuple) or not weights:
        fail("Kernel.fixed weights must be a non-empty 2-D list")
    if len(weights) > MAX_KERNEL_HEIGHT:
        fail("Kernel.fixed height exceeds 33")
    _charge(translator, 1 + 2 * len(weights), "Kernel.fixed row scan")
    if any(type(row) not in (list, tuple) for row in weights):
        fail("Kernel.fixed weights must be a rectangular 2-D list")
    width = len(weights[0])
    height = len(weights)
    if not width or width > MAX_KERNEL_WIDTH or any(len(row) != width for row in weights):
        fail("Kernel.fixed weights must be non-empty, rectangular, and at most 33 by 33")
    cells = width * height
    if cells > MAX_KERNEL_CELLS:
        fail("Kernel.fixed weights exceed 1089 cells")
    _charge(translator, cells, "Kernel.fixed weight scan")

    declared_width = _integer(arguments.get("width", -1), "Kernel.fixed width")
    declared_height = _integer(arguments.get("height", -1), "Kernel.fixed height")
    if declared_width not in (-1, width) or declared_height not in (-1, height):
        fail("Kernel.fixed declared dimensions must be -1 or match the weights")
    if width > MAX_KERNEL_WIDTH or height > MAX_KERNEL_HEIGHT:
        fail("Kernel.fixed dimensions exceed 33")
    x = _integer(arguments.get("x", -1), "Kernel.fixed x focus")
    y = _integer(arguments.get("y", -1), "Kernel.fixed y focus")
    x = width // 2 if x == -1 else x
    y = height // 2 if y == -1 else y
    if not 0 <= x < width or not 0 <= y < height or x > 32 or y > 32:
        fail("Kernel.fixed focus must lie within the weights and each offset must be <= 32")
    normalize = _boolean(arguments.get("normalize", False), "Kernel.fixed normalize")
    values = [[_number(value, "Kernel.fixed weight") for value in row] for row in weights]
    return _finish(translator, values, x, y, normalize)


def validate_kernel(translator, kernel) -> KernelSpec:
    """Revalidate an exact KernelSpec and return a fresh immutable snapshot."""
    if type(kernel) is not KernelSpec:
        fail("Expected an exact frozen KernelSpec")
    weights = kernel.weights
    if type(weights) is not tuple or not weights or len(weights) > MAX_KERNEL_HEIGHT:
        fail("KernelSpec weights must be a non-empty tuple with height <= 33")
    _charge(translator, 2 * len(weights), "KernelSpec row scan")
    if any(type(row) is not tuple for row in weights):
        fail("KernelSpec rows must be exact tuples")
    width = len(weights[0])
    height = len(weights)
    if (width < 1 or width > MAX_KERNEL_WIDTH
            or width * height > MAX_KERNEL_CELLS
            or any(len(row) != width for row in weights)):
        fail("KernelSpec must be rectangular and contain at most 1089 cells")
    if type(kernel.x) is not int or type(kernel.y) is not int:
        fail("KernelSpec focus coordinates must be exact integers")
    if not (0 <= kernel.x < width and 0 <= kernel.y < height
            and kernel.x <= 32 and kernel.y <= 32):
        fail("KernelSpec focus must lie within the weights and each offset must be <= 32")
    _charge(translator, 5 * width * height, "KernelSpec validation")
    copied = []
    for row in weights:
        owned = []
        for value in row:
            if type(value) is not float or not math.isfinite(value):
                fail("KernelSpec weights must be finite floats")
            owned.append(value)
        copied.append(tuple(owned))
    return KernelSpec(tuple(copied), kernel.x, kernel.y)


def invoke_kernel(translator, name: str, arguments: dict) -> KernelSpec:
    """Construct one bounded finite pixel Kernel from the pinned EE API."""
    if name not in KERNEL_FUNCTIONS:
        fail(f"Unsupported Earth Engine Kernel constructor: {name}")
    _charge(translator, 1)
    if name == "Kernel.fixed":
        return _fixed(translator, arguments)
    from .kernel_shapes import invoke_kernel_shape

    return invoke_kernel_shape(translator, name, arguments)
