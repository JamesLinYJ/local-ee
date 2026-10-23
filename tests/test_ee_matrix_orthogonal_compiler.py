"""SDK and owned-IR contracts for per-pixel reduced QR and SVD factors."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Pixel, Source, UnsupportedEEError
from gee.compat.earthengine.raster_array_bands import RasterArrayBands
from gee.compat.earthengine.raster_matrix_decomposition import (
    invoke_raster_matrix_decomposition,
)
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_matrix_solve import (
    compile_value,
    encode,
    first_image,
    local,
)
from ee_matrix_factor_compiler_helpers import array as _array


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    from gee.ee_python_client import configure_local_ee

    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def _dynamic_matrix(ee, rows=3, cols=2, *, nested_float32=False):
    image = first_image(ee)
    source_names = ("y0", "y1", "y2")
    columns = []
    for column in range(cols):
        names = [source_names[(row + column) % len(source_names)]
                 for row in range(rows)]
        columns.append(
            image.select(names).toFloat().toArray().toArray(axis=1)
        )
    matrix = columns[0]
    for column in columns[1:]:
        matrix = matrix.arrayCat(column, 1)
    matrix = matrix.toFloat()
    return matrix.toDouble() if nested_float32 else matrix


def _invocations(value, name):
    found = []
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == name:
            found.append(value)
        for child in value.values():
            found.extend(_invocations(child, name))
    elif isinstance(value, (tuple, list)):
        for child in value:
            found.extend(_invocations(child, name))
    return found


def _native_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_matrix_values"]


def _flat_factor(bundle, factor, shape):
    row_labels = [f"r{row}" for row in range(shape[0])]
    column_labels = [f"c{column}" for column in range(shape[1])]
    return bundle.select(factor).arrayFlatten(
        [row_labels, column_labels], separator="_",
    )


@pytest.mark.parametrize(
    ("method", "op", "factor_shapes"),
    [
        ("matrixQRDecomposition", "qr", {"Q": (3, 2), "R": (2, 2)}),
        ("matrixSingularValueDecomposition", "svd",
         {"U": (3, 2), "S": (2, 2), "V": (2, 2)}),
    ],
)
def test_pinned_sdk_rectangular_factor_outputs_share_one_native_producer(
        ee, local, method, op, factor_shapes):
    matrix = _dynamic_matrix(ee).set("factor_tag", op)
    decomposition = getattr(matrix, method)()
    encoded = encode(ee, decomposition)
    calls = _invocations(encoded, f"Image.{method}")
    assert len(calls) == 1
    assert set(calls[0]["arguments"]) == {"image"}

    flattened = [_flat_factor(decomposition, name, shape)
                 for name, shape in factor_shapes.items()]
    output = flattened[0]
    for factor_image in flattened[1:]:
        output = output.addBands(factor_image)
    result = compile_value(ee, output, local)

    expected_bands = [
        f"r{row}_c{column}" + (f"_{factor_index}" if factor_index else "")
        for factor_index, shape in enumerate(factor_shapes.values())
        for row in range(shape[0]) for column in range(shape[1])
    ]
    assert result["bands"] == expected_bands
    assert result["properties"]["factor_tag"] == op
    native = _native_nodes(result)
    assert len(native) == 1
    spec = json.loads(native[0]["arguments"]["spec"])
    assert (spec["v"], spec["op"], spec["rows"], spec["cols"], spec["rhs_cols"]) == (
        1, op, 3, 2, 0,
    )
    assert [operand["band"] for operand in spec["operands"]] == list(range(6))


def test_owned_rectangular_factor_bundle_preserves_one_nested_cast_producer():
    source = Source("sentinel-2-l2a", ("a",), ("y0", "y1", "y2"))
    matrix = _array(np.zeros((3, 2)), cast="to_float", source=source)
    nested = tuple(Pixel("to_double", (cell,)) for cell in matrix.cells)
    matrix = replace(matrix, cells=nested)
    result = invoke_raster_matrix_decomposition(
        Translator([], {}, {}), "Image.matrixSingularValueDecomposition",
        {"image": matrix},
    )

    assert isinstance(result, RasterArrayBands)
    assert [factor.name for factor in result.arrays] == ["U", "S", "V"]
    assert [factor.shape for factor in result.arrays] == [(3, 2), (2, 2), (2, 2)]
    assert all(factor.image is result.image for factor in result.arrays)
    assert result.image.props == {"matrix_tag": "kept"}
    producers = {
        id(cell.args[0].args[0])
        for factor in result.arrays for cell in factor.cells
    }
    assert len(producers) == 1
    producer = result.arrays[0].cells[0].args[0].args[0]
    assert producer.op == "matrix_values"
    assert all(operand.op == "to_double" and operand.args[0].op == "to_float"
               for operand in producer.args[0])
    spec = json.loads(producer.args[1])
    assert (spec["op"], spec["rows"], spec["cols"]) == ("svd", 3, 2)


def test_sdk_nested_float32_then_float64_casts_survive_to_the_native_inputs(ee, local):
    matrix = _dynamic_matrix(ee, nested_float32=True).set("factor_tag", "nested")
    factors = matrix.matrixQRDecomposition()
    flattened = _flat_factor(factors, "Q", (3, 2))
    result = compile_value(ee, flattened, local)

    process_ids = {node["process_id"] for node in result["process_graph"].values()}
    assert {"local_ee_to_float", "local_ee_to_double",
            "local_ee_matrix_values"} <= process_ids
    assert result["properties"]["factor_tag"] == "nested"
    native = _native_nodes(result)
    assert len(native) == 1
    spec = json.loads(native[0]["arguments"]["spec"])
    assert (spec["op"], spec["rows"], spec["cols"]) == ("qr", 3, 2)


def test_sdk_reduced_axis_and_combined_output_boundaries(ee, local):
    def evaluate(value):
        return Translator(local["catalog"], local["items"], {}).evaluate(
            encode(ee, value),
        )

    tall = ee.Image.constant(ee.Array([[row + 1] for row in range(8)])).toFloat()
    qr = evaluate(tall.matrixQRDecomposition())
    assert [factor.shape for factor in qr.arrays] == [(8, 1), (1, 1)]

    wide = ee.Image.constant(ee.Array([
        [row + column + 1 for column in range(4)] for row in range(8)
    ])).toFloat()
    svd = evaluate(wide.matrixSingularValueDecomposition())
    assert sum(len(factor.cells) for factor in svd.arrays) == 64

    too_many = ee.Image.constant(ee.Array(np.ones((5, 5)).tolist())).toFloat()
    with pytest.raises(UnsupportedEEError, match="combined factor outputs"):
        evaluate(too_many.matrixSingularValueDecomposition())


def test_factor_axis_output_and_work_limits_precede_numpy_allocation(monkeypatch):
    matrix = _array(np.ones((5, 5)))
    invalid_axis = _array(np.ones((9, 1)))

    def unexpected(*_args, **_kwargs):
        raise AssertionError("NumPy allocation occurred before preflight")

    monkeypatch.setattr(np, "asarray", unexpected)
    with pytest.raises(UnsupportedEEError, match="combined factor outputs"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixSingularValueDecomposition",
            {"image": matrix},
        )
    with pytest.raises(UnsupportedEEError, match="axes in1..8"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixQRDecomposition",
            {"image": invalid_axis},
        )
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixQRDecomposition",
            {"image": matrix, "unknown": True},
        )
    with pytest.raises(UnsupportedEEError, match="requires the image argument"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixQRDecomposition", {},
        )


def test_reduced_output_boundaries_and_bad_arguments():
    source = Source("sentinel-2-l2a", ("a",), ("y0",))
    qr_max = _array(np.zeros((8, 1)), source=source)
    qr = invoke_raster_matrix_decomposition(
        Translator([], {}, {}), "Image.matrixQRDecomposition", {"image": qr_max},
    )
    assert [array.shape for array in qr.arrays] == [(8, 1), (1, 1)]

    svd_max = _array(np.zeros((8, 4)), source=source)
    svd = invoke_raster_matrix_decomposition(
        Translator([], {}, {}), "Image.matrixSingularValueDecomposition",
        {"image": svd_max},
    )
    assert sum(len(array.cells) for array in svd.arrays) == 64

    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixQRDecomposition",
            {"image": qr_max, "ignored": True},
        )
    with pytest.raises(UnsupportedEEError, match="requires the image argument"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixQRDecomposition", {},
        )
    with pytest.raises(UnsupportedEEError, match="axes in1..8"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixQRDecomposition",
            {"image": _array(np.zeros((9, 1)), source=source)},
        )
