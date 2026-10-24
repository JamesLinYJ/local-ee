"""Bounded CSV rendering for inline GeoJSON FeatureCollections.

This is a local serialization policy, not a claim of complete Google Earth
Engine equivalence: scalar strings are emitted verbatim, null and missing
cells are empty, booleans are lowercase, and arrays/objects use compact JSON.
All CSV quoting is delegated to Python's standard :mod:`csv` writer.
The input byte bound is measured on the in-memory object serialized as compact
UTF-8 JSON, since the original source whitespace is unavailable here.
"""

from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

from gee.table_geometry import (
    Bounds,
    TableGeometryError,
    union_bounds,
    validate_bbox,
    validate_crs,
    validate_geometry,
    validate_geometry_with_models,
)
from gee.table_spherical_geometry import (
    even_odd_model,
    needs_model_aware_validation,
    public_geometry_mapping,
    reserve_spherical_table_work,
    spherical_model,
    validate_spherical_component,
)


MAX_ROWS = 1_000
MAX_COLUMNS = 256
MAX_CELLS = 50_000
MAX_JSON_BYTES = 1_000_000
MAX_CSV_BYTES = 1_000_000
MAX_DEPTH = 32
MAX_ATTRIBUTE_NAME_LENGTH = 256
_JSON_SEPARATORS = (",", ":")


class TableValueError(ValueError):
    """Raised when an inline table is malformed or exceeds its local bounds."""


def _fail(message: str) -> None:
    raise TableValueError(message)


def _validate_json(value: Any, *, depth: int = 1) -> None:
    """Accept only finite, built-in JSON values and cap nested metadata depth."""
    kind = type(value)
    from gee.compat.earthengine.spherical_wire import FullSphere

    if kind is FullSphere:
        _fail("S2 FullSphere has no supported public GeoJSON CSV encoding")
    from gee.compat.earthengine.geometry_values import GeometryValue

    if kind is GeometryValue:
        # GeometryValue's public JSON is exactly its mapping. Its private
        # constructor options still need validation before this boundary drops
        # the sidecar from compact JSON output.
        metadata = value.geometry_metadata
        if (type(metadata) is not dict or len(metadata) > 3
                or any(type(key) is not str
                       or key not in {"crs", "geodesic", "evenOdd"}
                       for key in metadata)):
            _fail("Geometry constructor metadata is malformed")
        from gee.compat.earthengine.geometry_values import _geometry_metadata
        from gee.compat.earthengine.ir import UnsupportedEEError

        try:
            _geometry_metadata(value)
        except UnsupportedEEError as exc:
            _fail(str(exc))
        kind = dict
    if value is None or kind in (str, bool, int):
        return
    if kind is float:
        if not math.isfinite(value):
            _fail("JSON numbers must be finite")
        return
    if kind in (list, dict):
        if depth > MAX_DEPTH:
            _fail(f"JSON metadata exceeds maximum depth {MAX_DEPTH}")
        if kind is list:
            for item in value:
                _validate_json(item, depth=depth + 1)
        else:
            for key, item in value.items():
                if type(key) is not str:
                    _fail("JSON object keys must be strings")
                _validate_json(item, depth=depth + 1)
        return
    _fail(f"Unsupported non-JSON value: {kind.__name__}")


def _geometry_json_mapping(value: Any) -> Any:
    """Keep typed geometry sidecars available through topology selection."""
    return value


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=_JSON_SEPARATORS,
        )
    except (TypeError, ValueError, OverflowError, UnicodeEncodeError) as exc:
        raise TableValueError("Value cannot be represented as UTF-8 JSON") from exc


def _validate_input_size(data: dict[str, Any]) -> None:
    try:
        size = len(_compact_json(data).encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise TableValueError("JSON input must be valid UTF-8") from exc
    if size > MAX_JSON_BYTES:
        _fail(f"JSON input exceeds {MAX_JSON_BYTES} UTF-8 bytes")


def _feature_properties(
    feature: dict[str, Any],
    spherical_calls: list[tuple[Any, bool]] | None = None,
) -> tuple[dict[str, Any], Bounds | None]:
    if feature.get("type") != "Feature":
        _fail("FeatureCollection entries must have type 'Feature'")
    if "geometry" not in feature or "properties" not in feature:
        _fail("Each Feature requires geometry and properties members")
    properties = feature["properties"]
    if properties is None:
        properties = {}
    if type(properties) is not dict:
        _fail("Feature properties must be an object or null")
    for name in properties:
        if len(name) > MAX_ATTRIBUTE_NAME_LENGTH or "\x00" in name:
            _fail("Attribute names must be at most 256 characters and contain no NUL")
    if ".geo" in properties:
        _fail("Property '.geo' conflicts with the reserved geometry column")
    if "id" in feature:
        value = feature["id"]
        if type(value) not in (str, int, float) or (
            type(value) is float and not math.isfinite(value)
        ):
            _fail("GeoJSON Feature id must be a string or finite number")
    validate_crs(feature)
    geometry = _geometry_json_mapping(feature["geometry"])
    if needs_model_aware_validation(geometry):
        def collect_spherical(component: dict[str, Any], even_odd: bool) -> None:
            if spherical_calls is None:
                validate_spherical_component(component, even_odd)
            else:
                spherical_calls.append((component, even_odd))

        bounds = validate_geometry_with_models(
            geometry,
            spherical_model=spherical_model,
            even_odd_model=even_odd_model,
            spherical_validator=collect_spherical,
        )
    else:
        # Unflagged standalone GeoJSON retains its previous planar validation
        # policy. Typed EE values and any explicit EE flags take the bounded
        # spherical-aware route above.
        bounds = validate_geometry(geometry)
    validate_bbox(feature, bounds)
    return properties, bounds


def _inspect(data: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if type(data) is not dict or data.get("type") != "FeatureCollection":
        _fail("Expected an inline GeoJSON FeatureCollection object")
    features = data.get("features")
    if type(features) is not list:
        _fail("FeatureCollection features must be an array")
    if len(features) > MAX_ROWS:
        _fail(f"FeatureCollection exceeds {MAX_ROWS} inline features")
    _validate_json(data)
    _validate_input_size(data)
    properties_by_row: list[dict[str, Any]] = []
    spherical_calls: list[tuple[Any, bool]] = []
    names: dict[str, None] = {}
    bounds: Bounds | None = None
    try:
        validate_crs(data)
        for feature in features:
            if type(feature) is not dict:
                _fail("FeatureCollection entries must be objects")
            properties, feature_bounds = _feature_properties(feature, spherical_calls)
            properties_by_row.append(properties)
            bounds = union_bounds(bounds, feature_bounds)
            for name in properties:
                if name != "system:index":
                    names.setdefault(name, None)
        validate_bbox(data, bounds)
    except TableGeometryError as exc:
        raise TableValueError(str(exc)) from exc

    headers = ["system:index", *names, ".geo"]
    if len(headers) > MAX_COLUMNS:
        _fail(f"FeatureCollection exceeds {MAX_COLUMNS} columns including reserved columns")
    if len(features) * len(headers) > MAX_CELLS:
        _fail(f"FeatureCollection exceeds {MAX_CELLS} row-by-default-column cells")
    try:
        reserve_spherical_table_work(spherical_calls)
        for geometry, even_odd in spherical_calls:
            validate_spherical_component(geometry, even_odd)
    except TableGeometryError as exc:
        raise TableValueError(str(exc)) from exc
    return features, properties_by_row, headers


def columns(data: Any) -> list[str]:
    """Validate a bounded inline FeatureCollection and return its default columns."""
    return _inspect(data)[2]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if type(value) is str:
        return value
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in (int, float, list, dict):
        return _compact_json(value)
    _fail("Unsupported table cell value")


def render_csv(data: Any, selectors: list[str] | None = None) -> str:
    """Validate and render a bounded FeatureCollection using the local CSV policy."""
    features, properties_by_row, default_headers = _inspect(data)
    if selectors is None:
        selected = default_headers
    else:
        if type(selectors) is not list or not selectors:
            _fail("CSV selectors must be a non-empty list of column names")
        if any(type(name) is not str for name in selectors):
            _fail("CSV selectors must contain only column names")
        if len(set(selectors)) != len(selectors):
            _fail("CSV selectors must be unique")
        known = set(default_headers)
        unknown = [name for name in selectors if name not in known]
        if unknown:
            _fail(f"Unknown CSV selector: {unknown[0]}")
        selected = selectors.copy()

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(selected)
    for feature, properties in zip(features, properties_by_row):
        row: list[str] = []
        for name in selected:
            if name == "system:index":
                value = (
                    properties["system:index"]
                    if "system:index" in properties
                    else feature.get("id")
                )
            elif name == ".geo":
                geometry = feature["geometry"]
                value = (
                    "" if geometry is None
                    else _compact_json(public_geometry_mapping(geometry))
                )
            else:
                value = properties.get(name)
            row.append(_cell(value))
        writer.writerow(row)
    result = output.getvalue()
    if len(result.encode("utf-8")) > MAX_CSV_BYTES:
        _fail(f"CSV output exceeds {MAX_CSV_BYTES} UTF-8 bytes")
    return result
