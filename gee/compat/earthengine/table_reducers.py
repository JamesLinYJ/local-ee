"""Bounded static table regression reducers for inline FeatureCollections."""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from .array_values import StaticArray
from .ir import fail, integer


MAX_TABLE_ROWS = 1_000
MAX_TABLE_INPUTS = 32
MAX_TABLE_WORK = 50_000


@dataclass(frozen=True)
class TableReducer:
    """A reducer whose rows and outputs are static metadata values."""

    name: str
    num_x: int
    num_y: int

    @property
    def input_count(self):
        return self.num_x + self.num_y


def handles_table_reducer(name):
    return name in {"Reducer.linearFit", "Reducer.linearRegression"}


def invoke_table_reducer(translator, name, arguments):
    """Construct only pinned, explicitly supported table regression reducers."""
    a = arguments
    if name == "Reducer.linearFit":
        translator.allowed(a, set())
        return TableReducer("linearFit", 1, 1)
    if name == "Reducer.linearRegression":
        translator.allowed(a, {"numX", "numY"})
        if "numX" not in a:
            fail("Reducer.linearRegression requires numX")
        num_x = integer(a["numX"], "linearRegression numX", 1)
        num_y = integer(a.get("numY", 1), "linearRegression numY", 1)
        if num_x + num_y > MAX_TABLE_INPUTS:
            fail("Table regression supports at most 32 input columns")
        return TableReducer("linearRegression", num_x, num_y)
    fail(f"Unsupported table reducer: {name}")


def _selectors(translator, value, reducer):
    if not isinstance(value, list) or len(value) != reducer.input_count:
        fail(f"{reducer.name} requires exactly {reducer.input_count} selectors")
    _charge(translator, len(value))
    if any(not isinstance(key, str) or not key for key in value):
        fail("reduceColumns selectors must be non-empty property names")
    if any("." in key for key in value):
        fail("reduceColumns currently supports flat property selectors only")
    return value


def _rows(translator, collection, selectors):
    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        fail("Table regression requires an inline FeatureCollection")
    features = collection.get("features")
    if not isinstance(features, list):
        fail("FeatureCollection requires an inline feature list")
    if len(features) > MAX_TABLE_ROWS:
        fail("Table regression supports at most 1000 inline features")
    rows = []
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            fail("Table regression requires static Features")
        properties = feature.get("properties", {})
        if not isinstance(properties, dict):
            fail("Feature properties must be a string-keyed dictionary")
        _charge(translator, 1 + len(properties) + len(selectors))
        if any(not isinstance(k, str) for k in properties):
            fail("Feature properties must be a string-keyed dictionary")
        row = [properties.get(key) for key in selectors]
        if any(value is None for value in row):
            continue
        if any(type(value) not in (int, float) for value in row):
            fail("Table regression inputs must be finite numeric properties or null")
        try:
            if any(not math.isfinite(value) for value in row):
                fail("Table regression inputs must be finite")
        except OverflowError:
            fail("Table regression inputs must be finite")
        rows.append(row)
    return rows


def _charge(translator, work):
    if work > MAX_TABLE_WORK or translator.steps + work > 50_000:
        fail("Table regression exceeds the compilation work budget")
    translator.steps += work


def _static_array(value):
    data = np.asarray(value, dtype=np.float64)
    if data.size > 10_000 or data.ndim > 8 or not np.isfinite(data).all():
        fail("Table regression result exceeds the finite static Array limits")
    data = data.copy()
    data.flags.writeable = False
    return StaticArray(data)


def _linear_fit(rows):
    if len(rows) < 2:
        return {"scale": None, "offset": None}
    values = np.asarray(rows, dtype=np.float64)
    design = np.column_stack((values[:, 0], np.ones(len(values))))
    try:
        coefficients, _, rank, _ = np.linalg.lstsq(design, values[:, 1], rcond=None)
    except np.linalg.LinAlgError:
        fail("Reducer.linearFit failed to converge")
    if rank < 2:
        return {"scale": None, "offset": None}
    if not np.isfinite(coefficients).all():
        fail("Reducer.linearFit produced a non-finite result")
    return {"scale": float(coefficients[0]), "offset": float(coefficients[1])}


def _linear_regression(rows, reducer):
    n = len(rows)
    if n <= reducer.num_x:
        return {"coefficients": None, "residuals": None}
    values = np.asarray(rows, dtype=np.float64)
    design, response = values[:, :reducer.num_x], values[:, reducer.num_x:]
    try:
        coefficients, _, rank, _ = np.linalg.lstsq(design, response, rcond=None)
    except np.linalg.LinAlgError:
        fail("Reducer.linearRegression failed to converge")
    # A rank-deficient design does not identify all requested coefficients.
    if rank < reducer.num_x:
        return {"coefficients": None, "residuals": None}
    with np.errstate(over="ignore", invalid="ignore"):
        residual = response - design @ coefficients
        rms = np.sqrt(np.mean(np.square(residual), axis=0))
    if not np.isfinite(coefficients).all() or not np.isfinite(rms).all():
        fail("Reducer.linearRegression produced a non-finite result")
    return {
        "coefficients": _static_array(coefficients),
        "residuals": _static_array(rms),
    }


def invoke_reduce_columns(translator, name, arguments):
    """Evaluate Collection.reduceColumns for the supported static table reducers."""
    if name != "Collection.reduceColumns":
        fail(f"Unsupported table operation: {name}")
    a = arguments
    translator.allowed(a, {"collection", "reducer", "selectors", "weightSelectors"})
    reducer = a.get("reducer")
    if not isinstance(reducer, TableReducer):
        fail("reduceColumns requires a supported table regression Reducer")
    selectors = _selectors(translator, a.get("selectors"), reducer)
    weights = a.get("weightSelectors")
    if weights is not None:
        if not isinstance(weights, list) or any(not isinstance(key, str) for key in weights):
            fail("weightSelectors must be a list of property names or null")
        if weights:
            fail("Weighted table regression via weightSelectors is unsupported")
    rows = _rows(translator, a.get("collection"), selectors)
    # Charge a conservative dense least-squares estimate before constructing
    # the matrices passed to NumPy. linearFit has slope and intercept columns.
    p = 2 if reducer.name == "linearFit" else reducer.num_x
    q, n = reducer.num_y, len(rows)
    work = n * (p * p + p * q + q) + p**3 + n * q * (p + 1)
    _charge(translator, work)
    if reducer.name == "linearFit":
        return _linear_fit(rows)
    return _linear_regression(rows, reducer)
