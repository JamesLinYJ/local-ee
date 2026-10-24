"""Preserve Float32 callback masks and normalize numeric logical truth."""
from __future__ import annotations

from gee.integer_values_contract import BOOLEAN_OPERATIONS
from .numeric_reducer_grid import _charge


def preserve_callback_masks(graph, operation, callback, arguments, rasters, process, values):
    if operation == "if":
        _charge(graph.work_owner, 10)
        callback["conditional_value"] = {"process_id": process, "arguments": values}
        callback["conditional_missing"] = {
            "process_id": "is_nodata", "arguments": {"x": arguments[0]},
        }
        callback["conditional_present"] = {
            "process_id": "eq", "arguments": {"x": {"from_node": "conditional_missing"}, "y": 0},
        }
        return "if", {"value": {"from_node": "conditional_present"},
                      "accept": {"from_node": "conditional_value"}, "reject": None}
    if operation not in BOOLEAN_OPERATIONS:
        return process, values
    # GeoTrellis comparisons turn NoData into false. Explicit validity must
    # survive both comparisons and logical composition; valid false stays0.
    _charge(graph.work_owner, 8 + 6 * len(rasters) + 3 * len(values))
    if operation == "not":
        process, values = "eq", {"x": values["x"], "y": 0}
    elif operation in {"and", "or"}:
        normalized = {}
        for index, (name, value) in enumerate(values.items()):
            key = f"boolean_truth_{index}"
            callback[key] = {"process_id": "neq", "arguments": {"x": value, "y": 0}}
            normalized[name] = {"from_node": key}
        values = normalized
    callback["boolean_value"] = {"process_id": process, "arguments": values}
    valid = None
    for index, (position, _result) in enumerate(rasters):
        missing, present = f"boolean_missing_{index}", f"boolean_present_{index}"
        callback[missing] = {
            "process_id": "is_nodata", "arguments": {"x": arguments[position]},
        }
        callback[present] = {
            "process_id": "eq", "arguments": {"x": {"from_node": missing}, "y": 0},
        }
        current = {"from_node": present}
        if valid is not None:
            key = f"boolean_valid_{index}"
            callback[key] = {"process_id": "and", "arguments": {"x": valid, "y": current}}
            current = {"from_node": key}
        valid = current
    return "if", {"value": valid, "accept": {"from_node": "boolean_value"}, "reject": None}
