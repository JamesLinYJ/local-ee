"""Pure bounded wire contracts for trusted Smile random-forest training."""
from __future__ import annotations

import math
import sys

from .sampling_spec import _names, _parse, encode_spec


IMPLEMENTATION = "smile-1.5.3"
MAX_ROWS = 1000
MAX_TREES = 256
MAX_CLASSES = 64
MAX_TRAINING_WORK = 1_000_000_000
MAX_SPEC_BYTES = 16_384
MAX_TRAINING_MAGNITUDE = sys.float_info.max / 2
PARAMETER_KEYS = frozenset({
    "number_of_trees", "variables_per_split", "min_leaf_population",
    "bag_fraction", "max_nodes", "seed",
})
SPEC_KEYS = PARAMETER_KEYS | {"version", "implementation", "schema", "class_property"}


def _integer(value, lower, upper, label, *, coerce=False):
    if coerce and type(value) is float and math.isfinite(value) and value.is_integer():
        value = int(value)
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"Random forest {label} must be an integer in {lower}..{upper}")
    return value


def _parameters(value, *, coerce=False):
    if type(value) is not dict or set(value) != PARAMETER_KEYS:
        raise ValueError("Random forest requires exactly six supported parameters")
    result = dict(value)
    for key, lower, upper in (
        ("number_of_trees", 1, MAX_TREES),
        ("min_leaf_population", 1, MAX_ROWS),
        ("seed", -(2**31), 2**31 - 1),
    ):
        result[key] = _integer(result[key], lower, upper, key, coerce=coerce)
    for key, lower, upper in (("variables_per_split", 1, 8), ("max_nodes", 2, MAX_ROWS)):
        if result[key] is not None:
            result[key] = _integer(result[key], lower, upper, key, coerce=coerce)
    fraction = result["bag_fraction"]
    try:
        valid_fraction = (type(fraction) in (int, float) and math.isfinite(fraction)
                          and 0 < fraction <= 1)
    except OverflowError:
        valid_fraction = False
    if not valid_fraction:
        raise ValueError("Random forest bag_fraction must be finite and in (0,1]")
    return result


def prepare_rf_parameters(
    number_of_trees, variables_per_split=None, min_leaf_population=1,
    bag_fraction=0.5, max_nodes=None, seed=0,
):
    """Normalize SDK numeric integers before constructing an immutable IR."""
    return _parameters({
        "number_of_trees": number_of_trees,
        "variables_per_split": variables_per_split,
        "min_leaf_population": min_leaf_population,
        "bag_fraction": bag_fraction,
        "max_nodes": max_nodes,
        "seed": seed,
    }, coerce=True)


def _check_spec(spec):
    if (type(spec) is not dict or set(spec) != SPEC_KEYS
            or type(spec["version"]) is not int or spec["version"] != 1
            or spec["implementation"] != IMPLEMENTATION):
        raise ValueError("Random forest requires the exact version1 Smile1.5.3 specification")
    _names(spec["schema"], 1, 8, "Random forest schema")
    _names([spec["class_property"]], 1, 1, "Random forest class_property")
    if {spec["class_property"], *spec["schema"]} & {"system:index", ".geo"}:
        raise ValueError("Random forest training requires numeric property columns")
    parameters = _parameters({key: spec[key] for key in PARAMETER_KEYS})
    if parameters["variables_per_split"] is not None and parameters["variables_per_split"] > len(spec["schema"]):
        raise ValueError("Random forest variables_per_split exceeds the input dimension")
    return spec


def prepare_rf_spec(parameters, schema, class_property):
    value = _check_spec({
        **parameters, "version": 1, "implementation": IMPLEMENTATION,
        "schema": list(schema), "class_property": class_property,
    })
    text = encode_spec(value)
    if len(text.encode("utf-8")) > MAX_SPEC_BYTES:
        raise ValueError("Random forest specification exceeds16384 UTF-8 bytes")
    return text


def decode_rf_spec(text):
    if type(text) is not str or len(text.encode("utf-8")) > MAX_SPEC_BYTES:
        raise ValueError("Random forest specification exceeds16384 UTF-8 bytes")
    return _check_spec(_parse(text))


def training_work_bound(spec, row_count):
    """Conservative tree/row/feature/leaf bound, separate from wire work."""
    _integer(row_count, 2, MAX_ROWS, "training row count")
    leaves = min(row_count, spec["max_nodes"] or row_count)
    work = row_count * spec["number_of_trees"] * len(spec["schema"]) * leaves
    if work > MAX_TRAINING_WORK:
        raise ValueError("Random forest exceeds the1000000000 training-work budget")
    return work


def _check_rows(value, spec):
    if (type(value) is not dict or set(value) != {"version", "rows"}
            or type(value["version"]) is not int or value["version"] != 1
            or type(value["rows"]) is not list):
        raise ValueError("Random forest rows require exactly version1 and a rows list")
    rows = value["rows"]
    training_work_bound(spec, len(rows))
    labels = set()
    for row in rows:
        if (type(row) is not list or len(row) != 2 or type(row[1]) is not list
                or len(row[1]) != len(spec["schema"])):
            raise ValueError("Random forest rows must contain a label and schema-ordered vector")
        labels.add(_integer(row[0], 0, MAX_CLASSES - 1, "class label"))
        for number in row[1]:
            try:
                valid = (type(number) in (int, float) and math.isfinite(number)
                         and abs(number) <= MAX_TRAINING_MAGNITUDE
                         and (type(number) is not int or abs(number) <= 2**53))
            except OverflowError:
                valid = False
            if not valid:
                raise ValueError("Random forest inputs must be finite exact-domain Float64 numbers with magnitude <=Double.MAX_VALUE/2")
    if not 2 <= len(labels) <= MAX_CLASSES or labels != set(range(len(labels))):
        raise ValueError("Random forest requires2..64 contiguous class labels starting at0")
    return value


def prepare_rf_rows(rows, spec):
    return encode_spec(_check_rows({"version": 1, "rows": rows}, spec))


def decode_rf_rows(text, spec):
    return _check_rows(_parse(text), spec)
