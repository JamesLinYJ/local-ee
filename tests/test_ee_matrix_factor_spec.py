"""Factor layouts extend the bounded matrix wire without changing old layouts."""
import json

import pytest

from gee.matrix_values_spec import (
    decode_matrix_values_spec, matrix_input_bands, matrix_output_cells,
    matrix_output_layout, matrix_output_shape, prepare_matrix_values_spec,
)


def _wire(op, n):
    return prepare_matrix_values_spec(op, n, n, 0, [{"band": i} for i in range(n * n)])


@pytest.mark.parametrize("op,n,names", [
    ("cholesky", 1, ("L",)), ("cholesky", 8, ("L",)),
    ("lu", 1, ("L", "U", "P")), ("lu", 4, ("L", "U", "P")),
])
def test_factor_layout_and_exact_scalar_band_count(op, n, names):
    encoded = _wire(op, n)
    decoded = decode_matrix_values_spec(encoded)
    assert set(decoded) == {"v", "op", "rows", "cols", "rhs_cols", "operands"}
    assert decoded["rhs_cols"] == 0
    assert matrix_output_layout(decoded) == tuple((name, (n, n)) for name in names)
    assert matrix_output_cells(decoded) == len(names) * n * n
    assert matrix_input_bands(decoded) == n * n
    assert encoded == json.dumps(decoded, sort_keys=True, separators=(",", ":"))
    if op == "lu":
        with pytest.raises(ValueError, match="multiple factor shapes"):
            matrix_output_shape(decoded)
    else:
        assert matrix_output_shape(decoded) == (n, n)


def test_old_single_matrix_wire_and_layout_are_byte_compatible():
    encoded = prepare_matrix_values_spec("pinverse", 1, 2, 0, [{"band": 0}, {"band": 1}])
    assert encoded == ('{"cols":2,"op":"pinverse","operands":[{"band":0},{"band":1}],'
                       '"rhs_cols":0,"rows":1,"v":1}')
    decoded = decode_matrix_values_spec(encoded)
    assert matrix_output_shape(decoded) == (2, 1)
    assert matrix_output_layout(decoded) == (("v", (2, 1)),)
    assert matrix_output_cells(decoded) == 2


@pytest.mark.parametrize("op,rows,cols,rhs", [
    ("lu", 5, 5, 0), ("lu", 8, 8, 0),
    ("lu", 2, 3, 0), ("cholesky", 2, 3, 0),
    ("lu", 2, 2, 1), ("cholesky", 2, 2, 1),
])
def test_factor_shape_rhs_and_combined_output_bounds(op, rows, cols, rhs):
    with pytest.raises(ValueError):
        prepare_matrix_values_spec(op, rows, cols, rhs, [{"band": 0}] * (rows * cols))


@pytest.mark.parametrize("op", ["cholesky", "lu"])
def test_factor_wire_does_not_admit_all_constants_or_foreign_fields(op):
    value = json.loads(_wire(op, 2))
    value["operands"] = [{"constant": "3ff0000000000000"}] * 4
    with pytest.raises(ValueError, match="nonempty and contiguous"):
        decode_matrix_values_spec(json.dumps(value, sort_keys=True, separators=(",", ":")))
    value = json.loads(_wire(op, 2))
    value["factors"] = ["L"]
    with pytest.raises(ValueError):
        decode_matrix_values_spec(json.dumps(value, sort_keys=True, separators=(",", ":")))


@pytest.mark.parametrize("op,count", [("cholesky", 4), ("lu", 12)])
def test_pinned_evaluator_preserves_factor_output_schema_and_origin(monkeypatch, op, count):
    from test_ee_integer_values_bridge import _collection, _evaluator_env

    evaluate, env, tracer = _evaluator_env(monkeypatch, [_collection("synthetic-factor")])
    graph = {
        "load": {"process_id": "load_collection", "arguments": {"id": "synthetic-factor"}},
        "factor": {"process_id": "local_ee_matrix_values", "result": True,
                   "arguments": {"data": {"from_node": "load"}, "spec": _wire(op, 2)}},
    }
    result = evaluate(graph, env=env, do_dry_run=False)
    assert result.metadata.band_names == [f"matrix{i}" for i in range(count)]
    assert len(result._traces) == 1
    assert tracer.get_source_constraints()[0][0].arguments[0] == "synthetic-factor"
