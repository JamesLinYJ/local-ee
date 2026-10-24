"""Independent NumPy reference for the closed mask projections in graphs."""
from __future__ import annotations

import json
import numpy as np


def mask_weights_handler(arguments, values):
    data, _names, timed = values[arguments["data"]["from_node"]]
    data = np.asarray(data, dtype=np.float64)
    axis = 1 if timed else 0
    inputs = [np.take(data, index, axis=axis) for index in range(data.shape[axis])]
    spec = json.loads(arguments["spec"])
    if set(spec) != {"op", "v"} or spec["v"] != 1:
        raise AssertionError("Mask reference requires a canonical v1 specification")

    def weight(value):
        if not np.isfinite(value).all() or (value < 0).any() or (value > 1).any():
            raise ValueError("Mask reference weights must be finite in [0,1]")
        return value

    operation = spec["op"]
    if operation == "result_value":
        assert len(inputs) == 1
        result = np.where(np.isfinite(inputs[0]), inputs[0], np.nan)
    elif operation == "validity":
        assert len(inputs) == 1
        if np.isinf(inputs[0]).any():
            raise ValueError("Source Infinity rejected before mask validity")
        result = np.where(np.isnan(inputs[0]), 0.0, 1.0)
    elif operation == "update":
        assert len(inputs) == 2
        old = weight(inputs[0])
        new = weight(np.where(np.isnan(inputs[1]), 0.0, inputs[1]))
        result = np.where(old == 0, 0.0, new)
    elif operation == "apply":
        assert len(inputs) == 2
        if np.isinf(inputs[0]).any():
            raise ValueError("Source Infinity rejected before mask application")
        result = np.where(weight(inputs[1]) > 0, inputs[0], np.nan)
    else:
        raise AssertionError("Unknown mask reference operation: " + str(operation))
    return np.expand_dims(result, axis=axis), ["v"], bool(timed)
