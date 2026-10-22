"""Bounded test-only evaluators for the compiled remap and table-op nodes."""
import json

import numpy as np

from ee_sampling_workflow_helpers import graph_process_handlers as _sampling_graph_handlers


REMAP_PROCESS = "local_ee_remap"
SAMPLE_PROCESS = "local_ee_sample_regions"
SAMPLE_OP_PROCESS = "local_ee_sample_table_op"
TRAIN_PROCESS = "local_ee_train_minimum_distance"
CLASSIFY_PROCESS = "local_ee_minimum_distance"
MAX_ORACLE_ROWS = 1000
MAX_ORACLE_PREDICATE_NODES = 64
MAX_ORACLE_PREDICATE_DEPTH = 16


def _remap_graph_process(arguments, values):
    """Test-only graph oracle for one remapped scalar band."""
    data, names, timed = values[arguments["data"]["from_node"]]
    spec = json.loads(arguments["spec"])
    if len(names) != 1 or np.asarray(data).shape[-2] != 1:
        raise AssertionError("Remap graph oracle expects one selected scalar band")
    source = np.asarray(data, dtype=np.float64)
    if np.isinf(source).any():
        raise ValueError("Fixture remap source must not contain infinity")
    output = np.full(source.shape, np.nan, dtype=np.float64)
    mapping = dict(zip(spec["from"], spec["to"]))
    valid = ~np.isnan(source)
    for source_value, target_value in mapping.items():
        output[valid & (source == float(source_value))] = float(target_value)
    if spec["default"] is not None:
        unmatched = valid & np.isnan(output)
        output[unmatched] = float(spec["default"])
    return output, ["remapped"], timed


def _predicate_matches(predicate, properties):
    name, arguments = predicate["name"], predicate["arguments"]
    if name in {"and", "or"}:
        matches = [_predicate_matches(child, properties)
                   for child in arguments.get("filters", [])]
        return all(matches) if name == "and" else any(matches)
    if name == "not":
        return not _predicate_matches(arguments["filter"], properties)
    if name == "notNull":
        return all(key in properties and properties[key] is not None
                   for key in arguments["properties"])
    left = properties.get(arguments["leftField"]) if "leftField" in arguments else arguments.get("leftValue")
    right = properties.get(arguments["rightField"]) if "rightField" in arguments else arguments.get("rightValue")
    if left is None or right is None:
        return False
    if name == "equals":
        return type(left) is type(right) and left == right
    if name in {"lessThan", "greaterThan"}:
        numeric = type(left) in (int, float) and type(right) in (int, float)
        same_type = type(left) is type(right)
        if not numeric and not same_type:
            return False
        return left < right if name == "lessThan" else left > right
    if name == "stringContains":
        return type(left) is str and type(right) is str and right in left
    raise AssertionError(f"Unexpected fixture filter predicate: {name}")


def _sample_table_op_process(arguments, values):
    """Bounded test-only evaluator for the filter/limit wire operations."""
    table = values[arguments["data"]["from_node"]]
    spec = json.loads(arguments["spec"])
    features = table["features"]
    if type(features) is not list or len(features) > MAX_ORACLE_ROWS:
        raise AssertionError("Sample-operation oracle input exceeds its 1000-row bound")
    if spec["operation"] == "filter":
        pending = [(spec["predicate"], 1)]
        visited = 0
        while pending:
            predicate, depth = pending.pop()
            visited += 1
            if visited > MAX_ORACLE_PREDICATE_NODES or depth > MAX_ORACLE_PREDICATE_DEPTH:
                raise AssertionError("Sample-operation oracle predicate exceeds its bound")
            arguments = predicate["arguments"]
            if predicate["name"] in {"and", "or"}:
                pending.extend((child, depth + 1) for child in arguments.get("filters", []))
            elif predicate["name"] == "not":
                pending.append((arguments["filter"], depth + 1))
        features = [feature for feature in features if _predicate_matches(
            spec["predicate"], feature["properties"],
        )]
    elif spec["operation"] == "limit":
        count = spec["count"]
        if count is not None and (type(count) is not int or not 0 <= count <= MAX_ORACLE_ROWS):
            raise AssertionError("Sample-operation oracle limit is outside 0..1000")
        if count is not None:
            features = features[:count]
    elif spec["operation"] != "limit":
        raise AssertionError(f"Unexpected table operation: {spec['operation']}")
    return {"type": "FeatureCollection", "features": features}


def graph_process_handlers(data):
    handlers = _sampling_graph_handlers(data)
    handlers[REMAP_PROCESS] = _remap_graph_process
    handlers[SAMPLE_OP_PROCESS] = _sample_table_op_process
    return handlers
