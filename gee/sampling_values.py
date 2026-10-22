"""Recheck real sampled rows and serialize bounded local feature results."""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import stat

from .sampling_spec import MAX_BYTES, MAX_CELLS, MAX_ROWS, sampling_columns
from .table_values import _cell, columns as table_columns, render_csv


_IDENTIFIER = re.compile(r"f(0|[1-9][0-9]*)_r(0|[1-9][0-9]*)_c(0|[1-9][0-9]*)\Z")
_ROW_KEYS = {"feature", "row", "col", "x", "y", "values"}


def _integer(value, maximum, label):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"Invalid sampled {label}")
    return value


def _number(value):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("Sample values must be finite numbers")
    return value


def assemble_sample_features(spec, rows):
    """Build features from actual ordered native rows, never from input metadata."""
    if type(rows) is not list or len(rows) > MAX_ROWS:
        raise ValueError("Sampling exceeds 1000 result rows")
    headers = sampling_columns(spec)
    if len(rows) * len(headers) > MAX_CELLS:
        raise ValueError("Sampling exceeds 50000 result cells")
    source = spec["regions"]["features"]
    features = []
    previous = None
    for row in rows:
        if type(row) is not dict or set(row) != _ROW_KEYS:
            raise ValueError("Unexpected native sample row fields")
        index = _integer(row["feature"], len(source) - 1, "feature index")
        y_index = _integer(row["row"], 2**53, "grid row")
        x_index = _integer(row["col"], 2**53, "grid column")
        key = index, y_index, x_index
        if previous is not None and key <= previous:
            raise ValueError("Sample rows must be unique and ordered by feature, row and column")
        previous = key
        x, y = _number(row["x"]), _number(row["y"])
        if not -180 <= x <= 180 or not -90 <= y <= 90:
            raise ValueError("Sample centers exceed WGS84 bounds")
        values = row["values"]
        if type(values) is not list or len(values) != len(spec["bands"]):
            raise ValueError("Sample row values do not match the declared bands")
        properties = {**source[index]["properties"],
                      **{name: _number(value) for name, value in zip(spec["bands"], values)}}
        identifier = f"f{index}_r{y_index}_c{x_index}"
        geometry = {"type": "Point", "coordinates": [x, y]} if spec["geometries"] else None
        features.append({"type": "Feature", "id": identifier,
                         "geometry": geometry, "properties": properties})
    data = {"type": "FeatureCollection", "features": features}
    table_columns(data)
    render_sample_csv(data, headers)  # response/CSV budget before publishing or training
    return data


def render_sample_csv(data, columns):
    """Use the established CSV policy, including real empty header-only results."""
    known = table_columns(data)
    if (type(columns) is not list or not 2 <= len(columns) <= 256
            or any(type(x) is not str or len(x) > 256 for x in columns)
            or len(set(columns)) != len(columns)
            or columns[0] != "system:index" or columns[-1] != ".geo"):
        raise ValueError("Invalid sampled result columns")
    if data["features"]:
        if set(columns) != set(known):
            raise ValueError("Sample result columns differ from its feature properties")
        return render_csv(data, columns)
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator="\r\n").writerow(columns)
    text = output.getvalue()
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Sample CSV exceeds 1 MB")
    return text


def read_sample_csv(path, spec):
    """Read one owned task result into a FeatureCollection with original value types.

    Copied properties are validated against the immutable input specification;
    band values come only from the real CSV, never from the specification.
    The caller must resolve ``path`` with the shared owning-job artifact boundary.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError("Sample CSV must be a bounded regular result file")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Sample CSV exceeds 1 MB")
    expected = sampling_columns(spec)
    limit = csv.field_size_limit(MAX_BYTES)
    features = []
    previous = None
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""), strict=True)
        if reader.fieldnames != expected:
            raise ValueError("Sample CSV columns do not match the declared schema")
        for row in reader:
            if len(features) >= MAX_ROWS or None in row or any(value is None for value in row.values()):
                raise ValueError("Sample CSV exceeds its row or shape limits")
            match = _IDENTIFIER.fullmatch(row["system:index"])
            if match is None:
                raise ValueError("Invalid sample result identifier")
            key = tuple(int(x) for x in match.groups())
            index, y_index, x_index = key
            _integer(index, len(spec["regions"]["features"]) - 1, "feature index")
            _integer(y_index, 2**53, "grid row")
            _integer(x_index, 2**53, "grid column")
            if previous is not None and key <= previous:
                raise ValueError("Sample CSV rows must have unique ordered identifiers")
            previous = key
            properties = dict(spec["regions"]["features"][index]["properties"])
            if any(row[name] != _cell(properties[name]) for name in spec["properties"]):
                raise ValueError("Sample CSV copied properties differ from its immutable input")
            for name in spec["bands"]:
                properties[name] = _number(float(row[name]))
            geometry = json.loads(row[".geo"]) if row[".geo"] else None
            if spec["geometries"]:
                if (type(geometry) is not dict or set(geometry) != {"type", "coordinates"}
                        or geometry["type"] != "Point"):
                    raise ValueError("Sample CSV must contain center-point geometries")
            elif geometry is not None:
                raise ValueError("Sample CSV unexpectedly includes geometries")
            features.append({"type": "Feature", "id": row["system:index"],
                             "geometry": geometry, "properties": properties})
    except (csv.Error, UnicodeError, OverflowError) as exc:
        raise ValueError("Invalid bounded UTF-8 sample CSV") from exc
    finally:
        csv.field_size_limit(limit)
    data = {"type": "FeatureCollection", "features": features}
    render_sample_csv(data, expected)
    return data
