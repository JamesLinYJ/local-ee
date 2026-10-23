"""Explicit terminal Float32 precision boundaries for pixel matrices."""
import json

import numpy as np
import pytest

from test_ee_double_array_solve import (
    _compile_raster, _first_image, ee, local, offline_only,
)


def test_float32_inverse_cast_can_overflow_after_finite_native_matrix_result(ee, local):
    smallest_positive_float32 = float(
        np.nextafter(np.float32(0), np.float32(1)),
    )
    local["arrays"][local["item_id"]]["y0"] = np.full(
        6, smallest_positive_float32, dtype=np.float64,
    )
    source = _first_image(ee).select(["y0"]).toFloat()
    matrix = source.toArray().toArray(axis=1)
    inverted = matrix.matrixInverse().toFloat().arrayFlatten(
        [["inverse"], ["rhs"]],
    )

    with pytest.warns(RuntimeWarning, match="overflow encountered in cast"):
        result, actual, names = _compile_raster(ee, inverted, local)

    assert names == ["inverse_rhs"]
    native = {
        node_id: node for node_id, node in result["process_graph"].items()
        if node["process_id"] == "local_ee_matrix_values"
    }
    assert len(native) == 1
    native_id = next(iter(native))
    spec = json.loads(native[native_id]["arguments"]["spec"])
    assert (spec["op"], spec["rows"], spec["cols"]) == ("inverse", 1, 1)

    def graph_references(value):
        if isinstance(value, dict):
            if set(value) == {"from_node"}:
                yield value["from_node"]
            else:
                for child in value.values():
                    yield from graph_references(child)
        elif isinstance(value, list):
            for child in value:
                yield from graph_references(child)

    def depends_on(node_id, target, visited=None):
        visited = set() if visited is None else visited
        if node_id == target:
            return True
        if node_id in visited:
            return False
        visited.add(node_id)
        node = result["process_graph"].get(node_id)
        return node is not None and any(
            depends_on(reference, target, visited)
            for reference in graph_references(node["arguments"])
        )

    terminal_float_casts = [
        node_id for node_id, node in result["process_graph"].items()
        if node["process_id"] == "local_ee_to_float"
        and depends_on(node_id, native_id)
    ]
    assert terminal_float_casts
    # The native 1x1 inverse is finite in Float64, but the explicit terminal
    # Float32 cast overflows. The kernel's finite-result policy precedes it.
    assert np.isinf(actual[0, :5]).all()
    assert np.isnan(actual[0, 5])
