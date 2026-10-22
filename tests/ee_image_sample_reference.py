"""Independent global-grid, SplitMix64, mask, and class-frequency references."""
import numpy as np
from shapely.geometry import Point, shape


MASK64 = (1 << 64) - 1
GOLDEN_COLUMN = 0x9E3779B97F4A7C15
GOLDEN_ROW = 0xD1B54A32D192ED03


def _mix64(value):
    value &= MASK64
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & MASK64
    return (value ^ (value >> 31)) & MASK64


def independent_grid_uniform(seed, row, col):
    """Apply the fixed local hash to global grid indices."""
    mixed = _mix64(
        (seed & MASK64)
        ^ _mix64((col + GOLDEN_COLUMN) & MASK64)
        ^ _mix64((row + GOLDEN_ROW) & MASK64)
    )
    return (mixed >> 11) * (2.0 ** -53)


def cell_center(data, row, col):
    west, south, east, north = data["extent"]
    rows, cols = data["grid"]["shape_rows_columns"]
    return west + (col + 0.5) * (east - west) / cols, \
        north - (row + 0.5) * (north - south) / rows


def grid_centers(data):
    rows, cols = data["grid"]["shape_rows_columns"]
    return [cell_center(data, row, col) for row in range(rows) for col in range(cols)]


def _mode_controls(data, mode):
    """Independent fixture policy; intentionally does not call example helpers."""
    if mode in {"all", "nullable"}:
        return data["items"][0]["geometry"], None, None, mode != "nullable"
    if mode == "factor":
        return data["explicit_region"], 0.5, None, False
    if mode == "num_pixels":
        return data["explicit_region"], None, 8, False
    raise AssertionError(mode)


def reference_sample_rows(data, mode):
    """Enumerate raw grid centers, hash subsamples, then apply null handling."""
    region, factor, num_pixels, drop_nulls = _mode_controls(data, mode)
    source = data["items"][0]["pixel_values"]
    rows, cols = data["grid"]["shape_rows_columns"]
    region_shape = shape(region)
    candidates = []
    for row in range(rows):
        for col in range(cols):
            x, y = cell_center(data, row, col)
            if region_shape.covers(Point(x, y)):
                candidates.append((row, col, x, y))
    probability = 1.0
    if factor is not None:
        probability = factor
    elif num_pixels is not None and candidates:
        probability = min(1.0, num_pixels / len(candidates))
    selected = [cell for cell in candidates
                if independent_grid_uniform(data["sample_seed"], cell[0], cell[1]) < probability]

    output = []
    for row, col, x, y in selected:
        pixel = row * cols + col
        values = {band: source[band][pixel] for band in data["sample_bands"]}
        if drop_nulls and any(value is None for value in values.values()):
            continue
        output.append({
            "type": "Feature",
            "id": f"f0_r{row}_c{col}",
            "geometry": {"type": "Point", "coordinates": [x, y]},
            "properties": values,
        })
    return output


def reference_training_rows(data, mode):
    rows = reference_sample_rows(data, mode)
    complete = [feature for feature in rows if all(
        feature["properties"].get(name) is not None
        for name in [data["class_property"], *data["input_properties"]]
    )]
    eligible = [feature for feature in complete
                if feature["properties"]["nir"] > -1]
    return eligible[:data["training_limit"]]


def class_frequencies(features, property_name):
    counts = {}
    for feature in features:
        value = feature["properties"].get(property_name)
        if value is not None:
            counts[str(value)] = counts.get(str(value), 0) + 1
    return counts
