"""Validated S2 measure records and unit-independent centroid decoding."""
from __future__ import annotations

from dataclasses import dataclass
import math

from .ir import fail


_VERSION = 1.0


@dataclass(frozen=True, slots=True)
class SphericalMeasureRecord:
    """Validated S2 op10 fields used for highest-dimension centroid decoding."""

    dimension: int
    area_steradians: float
    linear_length_radians: float
    polygon_perimeter_radians: float
    centroid_x: float
    centroid_y: float
    centroid_z: float

def _decode_fields(raw, label):
    if type(raw) not in (tuple, list) or len(raw) != 8:
        fail(f"{label} returned a malformed fixed record")
    if type(raw[0]) not in (float, int) or raw[0] != _VERSION:
        fail(f"{label} returned an unsupported record version")
    if type(raw[1]) not in (float, int):
        fail(f"{label} returned a malformed geometry dimension")
    try:
        dimension_value = float(raw[1])
    except (OverflowError, TypeError, ValueError):
        fail(f"{label} returned an invalid geometry dimension")
    if not math.isfinite(dimension_value) or dimension_value not in (-1.0, 0.0, 1.0, 2.0):
        fail(f"{label} returned a malformed geometry dimension")
    values = raw[2:]
    if any(type(value) not in (float, int) for value in values):
        fail(f"{label} returned a malformed numeric field")
    try:
        numbers = tuple(float(value) for value in values)
    except (OverflowError, TypeError, ValueError):
        fail(f"{label} returned an invalid numeric field")
    if any(not math.isfinite(value) for value in numbers):
        fail(f"{label} returned non-finite values")
    area, length, perimeter, x, y, z = numbers
    if area < 0 or length < 0 or perimeter < 0:
        fail(f"{label} returned a negative measure")
    dimension = int(dimension_value)
    if dimension == -1 and any(value != 0.0 for value in numbers):
        fail(f"{label} returned non-zero values for an empty geometry")
    if dimension < 2 and area != 0.0:
        fail(f"{label} returned polygon area below dimension two")
    if dimension < 1 and (length != 0.0 or perimeter != 0.0):
        fail(f"{label} returned edge length below dimension one")
    if dimension < 2 and perimeter != 0.0:
        fail(f"{label} returned polygon perimeter below dimension two")
    return dimension, numbers


def decode_measure_record(raw) -> SphericalMeasureRecord:
    """Validate the exact eight-double op10 record without rejecting cancellation."""
    dimension, (area, length, perimeter, x, y, z) = _decode_fields(raw, "S2 measures")
    return SphericalMeasureRecord(dimension, area, length, perimeter, x, y, z)


def centroid_lon_lat(record: SphericalMeasureRecord, *,
                     dimension_positions: int,
                     dimension_components: int) -> tuple[float, float]:
    """Project the highest-dimension centroid under a local resolution guard.

    The guard is a conservative floating-operation-count policy, not a formal
    error certificate for every S2 centroid algorithm. It retains the native
    vector unchanged and rejects directions whose magnitude is not resolved
    at binary64 precision for the selected components.
    """
    if record.dimension < 0:
        fail("Geometry.centroid has no highest-dimension component")
    if (type(dimension_positions) is not int or dimension_positions < 0
            or type(dimension_components) is not int or dimension_components < 0):
        fail("Spherical centroid component counts are malformed")
    if record.dimension == 2:
        weight = record.area_steradians
        scale = weight + record.polygon_perimeter_radians * record.polygon_perimeter_radians
    elif record.dimension == 1:
        weight = record.linear_length_radians
        scale = weight
    else:
        weight = float(dimension_positions)
        scale = weight
    norm = math.hypot(record.centroid_x, record.centroid_y, record.centroid_z)
    if not math.isfinite(norm) or not math.isfinite(scale) or weight <= 0:
        fail("Geometry.centroid has no stable highest-dimension centroid")
    if norm == 0.0:
        fail("Geometry.centroid is undefined because its weighted centroid cancels")
    unit_roundoff = 2.0 ** -53
    operation_count = 32 * (dimension_positions + dimension_components + 1)
    scaled_count = operation_count * unit_roundoff
    if scaled_count >= 1.0:
        fail("Geometry.centroid exceeds its numerical-resolution work bound")
    gamma = scaled_count / (1.0 - scaled_count)
    uncertainty = math.sqrt(3.0) * gamma * scale
    if norm <= uncertainty:
        fail("Geometry.centroid direction is numerically indeterminate at binary64 resolution")
    x = record.centroid_x / norm
    y = record.centroid_y / norm
    z = record.centroid_z / norm
    longitude = math.degrees(math.atan2(y, x))
    latitude = math.degrees(math.atan2(z, math.hypot(x, y)))
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        fail("Spherical centroid decoding produced a non-finite point")
    return longitude, latitude
