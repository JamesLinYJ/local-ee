"""Independent WGS84 tangent-chord fixtures for the native terrain kernel."""
from __future__ import annotations

from decimal import Decimal, localcontext
import math

from pyproj import Transformer

from gee.terrain_spec import prepare_terrain_spec


_A = 6_378_137.0
_F = 1.0 / 298.257223563
_E2 = _F * (2.0 - _F)
_D_A = Decimal.from_float(_A)
_D_E2 = Decimal.from_float(_E2)
_TOLERANCE_DEGREES = 2.0e-7


def canonical_spec(operation: str, azimuth: float = 270.0,
                   elevation: float = 45.0) -> str:
    """Expose the shared Python wire builder under the native test helper API."""
    return prepare_terrain_spec(operation, azimuth, elevation)


def _ecef(lon_degrees: float, lat_degrees: float) -> tuple[float, float, float]:
    lon, lat = math.radians(lon_degrees), math.radians(lat_degrees)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    prime_vertical = _A / math.sqrt(1.0 - _E2 * sin_lat * sin_lat)
    return (prime_vertical * cos_lat * math.cos(lon),
            prime_vertical * cos_lat * math.sin(lon),
            prime_vertical * (1.0 - _E2) * sin_lat)


def _coordinates(case: dict) -> list[list[tuple[float, float, tuple[float, float, float]]]]:
    transform = Transformer.from_crs(case["crs"], "EPSG:4326", always_xy=True)
    result = []
    for row in range(case["height"]):
        current = []
        y = case["ymax"] - (row + 0.5) * case["cell_height"]
        for col in range(case["width"]):
            x = case["xmin"] + (col + 0.5) * case["cell_width"]
            lon, lat = transform.transform(x, y, errcheck=True)
            current.append((lon, lat, _ecef(lon, lat)))
        result.append(current)
    return result


def _decimal(value: float) -> Decimal:
    return Decimal.from_float(value)


def _difference_matrix(points, col: int, row: int):
    center = points[row][col]
    lon, lat = map(math.radians, center[:2])
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    east = tuple(map(_decimal, (-sin_lon, cos_lon, 0.0)))
    north = tuple(map(_decimal, (-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat)))
    origin = tuple(map(_decimal, center[2]))

    def projection(other, basis):
        delta = tuple(_decimal(value) - base for value, base in zip(other[2], origin))
        return sum((part * direction for part, direction in zip(delta, basis)), Decimal(0))

    west = projection(points[row][col - 1], east), projection(points[row][col - 1], north)
    eastward = projection(points[row][col + 1], east), projection(points[row][col + 1], north)
    northward = projection(points[row - 1][col], east), projection(points[row - 1][col], north)
    southward = projection(points[row + 1][col], east), projection(points[row + 1][col], north)
    return (eastward[0] - west[0], eastward[1] - west[1],
            southward[0] - northward[0], southward[1] - northward[1])


def _angles(case: dict, gx: Decimal, gy: Decimal) -> float:
    if gx == 0 and gy == 0 and case["operation"] in {"slope", "aspect"}:
        return 0.0
    if case["operation"] == "slope":
        with localcontext() as context:
            context.prec = 100
            magnitude = (gx * gx + gy * gy).sqrt()
            if magnitude.adjusted() < -250:
                return float(magnitude * _decimal(180.0 / math.pi))
        try:
            magnitude_float = math.hypot(float(gx), float(gy))
        except OverflowError:
            magnitude_float = math.inf
        return math.degrees(math.atan(magnitude_float))
    if case["operation"] == "aspect":
        try:
            east, north = float(gx), float(gy)
        except OverflowError:
            east = math.copysign(math.inf, gx)
            north = math.copysign(math.inf, gy)
        raw = math.degrees(math.atan2(-east, -north)) % 360.0
        return 0.0 if raw == 0.0 or raw >= 360.0 else raw

    with localcontext() as context:
        context.prec = 100
        norm = (gx * gx + gy * gy + Decimal(1)).sqrt()
        normal_east = float(-gx / norm)
        normal_north = float(-gy / norm)
        normal_up = float(Decimal(1) / norm)
    azimuth = math.radians(case["azimuth"])
    elevation = math.radians(case["elevation"])
    illumination = (normal_east * math.cos(elevation) * math.sin(azimuth)
                    + normal_north * math.cos(elevation) * math.cos(azimuth)
                    + normal_up * math.sin(elevation))
    return math.floor(max(0.0, min(1.0, illumination)) * 255.0 + 0.5)


def reference(case: dict) -> list[float | None]:
    """Decimal-backed 2x2 reference using pyproj and independently built ECEF points."""
    points = _coordinates(case)
    values = case["values"]
    available = {tuple(tile) for tile in case["existing_tiles"]}
    output: list[float | None] = [None] * (case["width"] * case["height"])
    with localcontext() as context:
        context.prec = 100
        for row in range(case["height"]):
            for col in range(case["width"]):
                tile_key = (col // case["tile_cols"], row // case["tile_rows"])
                index = row * case["width"] + col
                if tile_key not in available or col == 0 or row == 0 \
                        or col == case["width"] - 1 or row == case["height"] - 1:
                    continue
                support = (values[index], values[index - 1], values[index + 1],
                           values[index - case["width"]], values[index + case["width"]])
                if any(value is None for value in support):
                    continue
                support_cells = ((col, row), (col - 1, row), (col + 1, row),
                                 (col, row - 1), (col, row + 1))
                if any((x // case["tile_cols"], y // case["tile_rows"]) not in available
                       for x, y in support_cells):
                    continue
                ew_east, ew_north, sn_east, sn_north = _difference_matrix(points, col, row)
                determinant = ew_east * sn_north - ew_north * sn_east
                if determinant == 0:
                    raise ValueError(f"singular independent reference metric at {col},{row}")
                delta_ew = _decimal(values[index + 1]) - _decimal(values[index - 1])
                delta_sn = _decimal(values[index + case["width"]]) - _decimal(
                    values[index - case["width"]]
                )
                gx = (delta_ew * sn_north - ew_north * delta_sn) / determinant
                gy = (ew_east * delta_sn - delta_ew * sn_east) / determinant
                output[index] = _angles(case, gx, gy)
    return output


def _plane_case(name, crs, xmin, ymax, cell_width, cell_height,
                operation, gradient_east, gradient_north,
                *, azimuth=270.0, elevation=45.0, offset=0.0):
    case = {
        "name": name, "crs": crs, "xmin": xmin, "ymax": ymax,
        "cell_width": cell_width, "cell_height": cell_height,
        "width": 6, "height": 6, "tile_cols": 3, "tile_rows": 3,
        "existing_tiles": [[0, 0], [1, 0], [0, 1], [1, 1]],
        "operation": operation, "azimuth": azimuth, "elevation": elevation,
    }
    points = _coordinates(case)
    origin = points[2][2][2]
    lon0, lat0 = map(math.radians, points[2][2][:2])
    east_basis = (-math.sin(lon0), math.cos(lon0), 0.0)
    north_basis = (-math.sin(lat0) * math.cos(lon0),
                   -math.sin(lat0) * math.sin(lon0), math.cos(lat0))
    values = []
    for row in range(case["height"]):
        for col in range(case["width"]):
            point = points[row][col][2]
            displacement = tuple(value - base for value, base in zip(point, origin))
            east = sum(value * basis for value, basis in zip(displacement, east_basis))
            north = sum(value * basis for value, basis in zip(displacement, north_basis))
            values.append(offset + gradient_east * east + gradient_north * north)
    case["values"] = values
    case["expected"] = reference(case)
    return case


def make_fixture() -> dict:
    """Build geographic, projected-metre/foot, mask, seam, and range fixtures."""
    cases = [
        _plane_case("flat-geographic", "EPSG:4326", 19.97, 0.03, 0.01, 0.01,
                    "hillshade", 0.0, 0.0),
        _plane_case("equatorial-east-slope", "EPSG:4326", -0.03, 0.03, 0.01, 0.01,
                    "slope", 0.3, 0.0),
        _plane_case("equatorial-north-aspect", "EPSG:4326", -0.03, 0.03, 0.01, 0.01,
                    "aspect", 0.0, -0.3),
        _plane_case("latitude-60-custom-hillshade", "EPSG:4326", 10.97, 60.03,
                    0.01, 0.01, "hillshade", 0.2, -0.1, azimuth=45.0, elevation=30.0),
        _plane_case("projected-us-survey-feet", "EPSG:2263", 986_970.0, 214_030.0,
                    10.0, 10.0, "slope", 0.08, 0.06),
        _plane_case("utm-metre-aspect", "EPSG:32610", 499_970.0, 4_200_030.0,
                    10.0, 10.0, "aspect", -0.12, 0.16),
    ]

    mixed = _plane_case("large-common-offset", "EPSG:32610", 499_970.0, 4_200_030.0,
                        10.0, 10.0, "slope", 0.0, 0.0)
    # Neighbour differences are near the representable spacing at this common offset.
    mixed["values"] = [1.0e200 + (index % 6) * 1.0e185
                       + (index // 6) * 2.0e185 for index in range(36)]
    mixed["expected"] = reference(mixed)
    cases.append(mixed)

    center = _plane_case("valid-huge-center", "EPSG:32610", 499_970.0, 4_200_030.0,
                         10.0, 10.0, "slope", 0.05, 0.02)
    center["values"][3 * 6 + 3] = 1.0e308
    center["expected"] = reference(center)
    cases.append(center)

    opposite = _plane_case("opposing-extreme-elevations", "EPSG:32610",
                            499_970.0, 4_200_030.0, 10.0, 10.0,
                            "slope", 0.0, 0.0)
    target = 2 * 6 + 2
    maximum = float.fromhex("0x1.fffffffffffffp+1023")
    opposite["values"][target - 1] = -maximum
    opposite["values"][target + 1] = maximum
    opposite["values"][target - 6] = 0.0
    opposite["values"][target + 6] = 0.0
    opposite["values"][target] = 0.0
    opposite["expected"] = reference(opposite)
    cases.append(opposite)

    bright = _plane_case("flat-hillshade-255", "EPSG:4326", 19.97, 0.03,
                         0.01, 0.01, "hillshade", 0.0, 0.0, elevation=90.0)
    dark = _plane_case("flat-hillshade-zero", "EPSG:4326", 19.97, 0.03,
                       0.01, 0.01, "hillshade", 0.0, 0.0, elevation=270.0)
    assert bright["expected"][2 * 6 + 2] == 255.0
    assert dark["expected"][2 * 6 + 2] == 0.0
    cases.extend((bright, dark))

    tiny = {
        "name": "equal-huge-ew-and-subnormal-ns", "crs": "EPSG:4326",
        "xmin": -3.0e-9, "ymax": 3.0e-9, "cell_width": 1.0e-9,
        "cell_height": 1.0e-9, "width": 6, "height": 6,
        "tile_cols": 3, "tile_rows": 3,
        "existing_tiles": [[0, 0], [1, 0], [0, 1], [1, 1]],
        "operation": "slope", "azimuth": 270.0, "elevation": 45.0,
        "values": [0.0] * 36,
    }
    # At (2,2), E and W share a huge common value; only the orthogonal difference
    # is subnormal. Center validity must not set a common scale for both derivatives.
    tiny["values"][2 * 6 + 1] = 1.0e308
    tiny["values"][2 * 6 + 2] = 1.0e308
    tiny["values"][2 * 6 + 3] = 1.0e308
    tiny["values"][1 * 6 + 2] = 0.0
    tiny["values"][3 * 6 + 2] = math.ulp(0.0)
    tiny["expected"] = reference(tiny)
    assert tiny["expected"][2 * 6 + 2] > 0.0
    cases.append(tiny)

    near_north = {
        "name": "aspect-rounded-360-is-canonical-zero", "crs": "EPSG:4326",
        "xmin": -0.003, "ymax": 0.003, "cell_width": 0.001,
        "cell_height": 0.001, "width": 6, "height": 6,
        "tile_cols": 3, "tile_rows": 3,
        "existing_tiles": [[0, 0], [1, 0], [0, 1], [1, 1]],
        "operation": "aspect", "azimuth": 270.0, "elevation": 45.0,
        "values": [0.0] * 36,
    }
    target = 2 * 6 + 2
    near_north["values"][target + 1] = 1.0e-15
    near_north["values"][target + 6] = 20.0
    near_north["expected"] = reference(near_north)
    cases.append(near_north)

    masked = _plane_case("masked-neighbor-and-missing-tile", "EPSG:32610",
                         499_970.0, 4_200_030.0, 10.0, 10.0,
                         "hillshade", 0.1, 0.2)
    masked["values"][2 * 6 + 3] = None
    masked["existing_tiles"] = [[0, 0], [1, 0], [0, 1]]
    masked["expected"] = reference(masked)
    cases.append(masked)

    for case in cases:
        case["spec"] = canonical_spec(case["operation"], case["azimuth"], case["elevation"])
        case["tolerance_degrees"] = _TOLERANCE_DEGREES
    return {"cases": cases, "case_count": len(cases),
            "pixel_count": sum(len(case["expected"]) for case in cases)}
