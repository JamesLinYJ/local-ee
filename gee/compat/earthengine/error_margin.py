"""Typed, bounded support for the pinned Earth Engine ErrorMargin value."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from .ir import fail


ERROR_MARGIN_ARGUMENTS = {
    "ErrorMargin": (frozenset(), frozenset({"value", "unit"})),
}

_UNITS = frozenset({"meters", "projected", "infinite"})
# These boundaries mirror the pinned official 1.7.49 ErrorMargin docstring.
_INFINITE_THRESHOLD = 20_000_000
_MIN_METER_MARGIN = 0.001
_MAX_TRANSLATOR_WORK = 50_000


@dataclass(frozen=True, slots=True)
class ErrorMarginValue:
    """Normalized ErrorMargin IR; infinite margins have no numeric magnitude."""

    magnitude: float | None
    unit: Literal["meters", "projected", "infinite"]

    def __post_init__(self) -> None:
        if type(self.unit) is not str or self.unit not in _UNITS:
            raise ValueError("ErrorMarginValue has an unknown unit")
        if self.unit == "infinite":
            if self.magnitude is not None:
                raise ValueError("Infinite ErrorMarginValue cannot have a magnitude")
            return
        if (type(self.magnitude) is not float or not math.isfinite(self.magnitude)
                or self.magnitude < 0 or self.magnitude >= _INFINITE_THRESHOLD):
            raise ValueError("ErrorMarginValue magnitude is not normalized")
        if self.unit == "meters" and 0 < self.magnitude < _MIN_METER_MARGIN:
            raise ValueError("Meter ErrorMarginValue is below the supported precision")


def _charge_work(translator, amount: int, label: str) -> None:
    steps = getattr(translator, "steps", None)
    if (type(steps) is not int or not 0 <= steps <= _MAX_TRANSLATOR_WORK
            or type(amount) is not int or amount < 0
            or steps + amount > _MAX_TRANSLATOR_WORK):
        fail(f"{label} exceeds the shared 50000-step compilation work budget")
    translator.steps = steps + amount


def _finite_magnitude(value, label: str) -> float:
    if type(value) is int:
        # Compare before conversion so oversized JSON integers cannot allocate
        # a float or lose precision when they normalize to an infinite margin.
        if value >= _INFINITE_THRESHOLD or value <= -_INFINITE_THRESHOLD:
            return float(_INFINITE_THRESHOLD)
        return float(abs(value))
    if type(value) is not float or not math.isfinite(value):
        fail(f"{label} must be a finite number")
    return abs(value)


def _normalized_margin(magnitude: float, unit: str, label: str):
    if unit == "infinite" or magnitude >= _INFINITE_THRESHOLD:
        return ErrorMarginValue(None, "infinite")
    if unit == "meters" and 0 < magnitude < _MIN_METER_MARGIN:
        fail(f"{label} meter values must be zero or at least 0.001")
    return ErrorMarginValue(float(magnitude), unit)


def construct_error_margin(translator, args) -> ErrorMarginValue:
    """Construct a normalized ErrorMargin from pinned API arguments."""
    label = "ErrorMargin"
    if type(args) is not dict or len(args) > 2:
        fail(f"{label} arguments must be a bounded dictionary")
    if any(type(key) is not str or key not in {"value", "unit"} for key in args):
        fail(f"{label} has unsupported arguments")

    raw_unit = args.get("unit")
    unit = "meters" if raw_unit is None else raw_unit
    if type(unit) is not str or len(unit) > 9 or unit not in _UNITS:
        fail(f"{label} unit must be meters, projected, or infinite")

    raw_value = args.get("value")
    has_value = "value" in args and raw_value is not None
    if not has_value and unit != "infinite":
        fail(f"{label} requires a value unless unit is infinite")

    _charge_work(translator, 1 + len(args) + len(unit), label)
    if unit == "infinite":
        if has_value:
            _finite_magnitude(raw_value, label)
        return ErrorMarginValue(None, "infinite")

    magnitude = _finite_magnitude(raw_value, label)
    return _normalized_margin(magnitude, unit, label)


def validate_no_reprojection_margin(translator, value, label):
    """Validate a margin for a caller-proven same-CRS, same-edge-model path.

    Callers must establish that the operation performs no coordinate
    transformation before using this helper. It validates only the margin
    representation and never authorizes or performs a reprojection.
    """
    if value is None:
        return None
    if type(value) is ErrorMarginValue:
        _charge_work(translator, 1, label)
        # Recheck the invariant in case a caller deliberately bypassed the
        # frozen dataclass using object.__setattr__.
        try:
            ErrorMarginValue(value.magnitude, value.unit)
        except (TypeError, ValueError):
            fail(f"{label} requires a normalized ErrorMargin")
        return value
    # The pinned Python SDK declares raw floats as accepted ErrorMargin inputs;
    # the JS API likewise serializes primitive numeric arguments directly.
    if type(value) in (int, float):
        return construct_error_margin(translator, {"value": value})
    fail(f"{label} requires a static ErrorMargin value")

