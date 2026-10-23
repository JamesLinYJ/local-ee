"""Fixed per-pixel Cholesky/LU output contracts and producer sharing."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Pixel, Source, UnsupportedEEError, const
from gee.compat.earthengine.matrix_values_graph import compile_matrix_element
from gee.compat.earthengine.raster_matrix_decomposition import (
    invoke_raster_matrix_decomposition,
)
from gee.ee_python_client import configure_local_ee
from gee.matrix_values_spec import prepare_matrix_values_spec
from scripts.ee_python_api.offline import OfflineGuard
from test_ee_raster_matrix_solve import compile_value, encode, first_image, local
from ee_matrix_factor_compiler_helpers import array as _array


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline_only():
    with OfflineGuard() as guard:
        yield
    assert guard.evidence()["attempt_count"] == 0


@pytest.fixture
def ee():
    client = configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )
    assert client.__version__ == "1.7.49"
    return client


def _dynamic_matrix(ee):
    image = first_image(ee)
    first = image.select(["y0", "y1"]).toFloat().toArray().toArray(axis=1)
    second = image.select(["y1", "y2"]).toFloat().toArray().toArray(axis=1)
    return first.arrayCat(second, 1).toFloat()


def _find_invocations(value, name):
    found = []
    if isinstance(value, dict):
        if value.get("type") == "Invocation" and value.get("functionName") == name:
            found.append(value)
        for child in value.values():
            found.extend(_find_invocations(child, name))
    elif isinstance(value, (tuple, list)):
        for child in value:
            found.extend(_find_invocations(child, name))
    return found


def _native_nodes(result):
    return [node for node in result["process_graph"].values()
            if node["process_id"] == "local_ee_matrix_values"]


def _factor_bundle(ee, matrix):
    return matrix.matrixLUDecomposition().set("factor_tag", "kept")


def test_pinned_sdk_signature_and_cholesky_lu_scalar_exports(ee, local):
    matrix = _dynamic_matrix(ee)
    cholesky = matrix.matrixCholeskyDecomposition()
    lu = _factor_bundle(ee, matrix)
    cholesky_call = _find_invocations(encode(ee, cholesky), "Image.matrixCholeskyDecomposition")
    lu_call = _find_invocations(encode(ee, lu), "Image.matrixLUDecomposition")
    assert len(cholesky_call) == len(lu_call) == 1
    assert set(cholesky_call[0]["arguments"]) == {"image"}
    assert set(lu_call[0]["arguments"]) == {"image"}

    cholesky_flat = cholesky.arrayFlatten(
        [["chol_r0", "chol_r1"], ["c0", "c1"]], separator="_",
    )
    cholesky_result = compile_value(ee, cholesky_flat, local)
    assert cholesky_result["bands"] == ["chol_r0_c0", "chol_r0_c1",
                                        "chol_r1_c0", "chol_r1_c1"]
    cholesky_spec = json.loads(_native_nodes(cholesky_result)[0]["arguments"]["spec"])
    assert (cholesky_spec["op"], cholesky_spec["rhs_cols"]) == ("cholesky", 0)

    lu_flat = []
    for factor in ("L", "U", "P"):
        lu_flat.append(lu.select(factor).arrayFlatten(
            [[f"{factor}_r0", f"{factor}_r1"], ["c0", "c1"]],
            separator="_",
        ))
    output = lu_flat[0].addBands(lu_flat[1]).addBands(lu_flat[2])
    result = compile_value(ee, output, local)
    assert result["bands"] == [f"{factor}_r{row}_c{column}"
                               for factor in ("L", "U", "P")
                               for row in range(2) for column in range(2)]
    assert result["properties"]["factor_tag"] == "kept"
    assert result["properties"]["system:index"] == "a"
    assert result["properties"]["system:time_start"] == 1000
    native = _native_nodes(result)
    assert len(native) == 1
    spec = json.loads(native[0]["arguments"]["spec"])
    assert (spec["op"], spec["rows"], spec["cols"], spec["rhs_cols"]) == (
        "lu", 2, 2, 0,
    )
    assert [item["band"] for item in spec["operands"]] == list(range(4))
    assert len(result["process_graph"]) <= 500

    lower, upper, permutation = (lu.select(name) for name in ("L", "U", "P"))
    reconstructed = permutation.matrixMultiply(matrix).arrayFlatten(
        [["r0", "r1"], ["c0", "c1"]],
    )
    triangular_product = lower.matrixMultiply(upper).arrayFlatten(
        [["r0", "r1"], ["c0", "c1"]],
    )
    identity_check = reconstructed.addBands(triangular_product)
    composed = compile_value(ee, identity_check, local)
    assert len(_native_nodes(composed)) == 1
    assert composed["bands"] == (
        [f"r{row}_c{column}" for row in range(2) for column in range(2)]
        + [f"r{row}_c{column}_1" for row in range(2) for column in range(2)]
    )


def test_lu_output_limit_and_dynamic_mask_are_checked_before_materialization():
    source = Source("sentinel-2-l2a", ("a",), ("y0", "y1", "y2"))
    five = _array(np.zeros((5, 5)), source=source)
    with pytest.raises(UnsupportedEEError, match="combined factor outputs"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixLUDecomposition", {"image": five},
        )

    mask = Pixel("lte", (const(1.0), const(2.0)), True)
    matrix = _array(np.zeros((2, 2)), source=source, mask=mask)
    factors = invoke_raster_matrix_decomposition(
        Translator([], {}, {}), "Image.matrixLUDecomposition", {"image": matrix},
    )
    assert all(array.mask is mask for array in factors.arrays)
    assert all(pixel.op == "to_double" for array in factors.arrays for pixel in array.cells)

    allowed_lu = invoke_raster_matrix_decomposition(
        Translator([], {}, {}), "Image.matrixLUDecomposition",
        {"image": _array(np.zeros((4, 4)), source=source)},
    )
    assert sum(len(array.cells) for array in allowed_lu.arrays) == 48
    with pytest.raises(UnsupportedEEError, match="combined factor outputs"):
        invoke_raster_matrix_decomposition(
            Translator([], {}, {}), "Image.matrixLUDecomposition",
            {"image": _array(np.zeros((8, 8)), source=source)},
        )
    allowed_cholesky = invoke_raster_matrix_decomposition(
        Translator([], {}, {}), "Image.matrixCholeskyDecomposition",
        {"image": _array(np.zeros((8, 8)), source=source)},
    )
    assert len(allowed_cholesky.cells) == 64


def test_dynamic_factor_preserves_nested_input_casts():
    source = Source("sentinel-2-l2a", ("a",), ("y0",))
    matrix = _array(np.zeros((2, 2)), source=source)
    nested = tuple(
        Pixel("to_double", (Pixel("to_float", (cell.args[0],)),))
        for cell in matrix.cells
    )
    matrix = replace(matrix, cells=nested)
    factor = invoke_raster_matrix_decomposition(
        Translator([], {}, {}), "Image.matrixCholeskyDecomposition", {"image": matrix},
    )
    producer = factor.cells[0].args[0].args[0]
    input_pixel = producer.args[0][0]
    assert input_pixel.op == "to_double"
    assert input_pixel.args[0].op == "to_float"
    assert input_pixel.args[0].args[0].op == "band"


def _matrix_component(spec, operands, index=0):
    producer = Pixel("matrix_values", (tuple(operands), spec))
    return Pixel("matrix_element", (producer, index))


def _dynamic_cells(source, names=("y0", "y1", "y2", "y0")):
    return tuple(Pixel("to_float", (Pixel("band", (source, name)),))
                 for name in names)


def test_dynamic_factors_reject_unproven_grid_and_mixed_time_inputs(ee, local):
    names = ("y0", "y1", "y2", "y0")
    spec = prepare_matrix_values_spec(
        "cholesky", 2, 2, 0,
        [{"band": index} for index in range(4)],
    )
    catalog = local["catalog"]
    items = {key: [dict(item, properties=dict(item["properties"]))
                   for item in value] for key, value in local["items"].items()}
    for item in items["sentinel-2-l2a"]:
        item["properties"].update({
            "proj:code": "EPSG:32631",
            "proj:transform": [10, 0, 0, 0, -10, 10],
        })
    items["sentinel-2-l2a"][1]["properties"]["proj:transform"] = [
        10, 0, 5, 0, -10, 10,
    ]
    split_source = Source("sentinel-2-l2a", ("a", "b"), names)
    with pytest.raises(UnsupportedEEError, match="common pixel grid"):
        compile_matrix_element(
            Graph(Translator(catalog, items, {})),
            _matrix_component(spec, _dynamic_cells(split_source)),
        )

    single = Source("sentinel-2-l2a", ("a",), names)
    mixed_time = list(_dynamic_cells(single))
    mixed_time[2:] = [
        Pixel("to_float", (Pixel("reduce_t", (
            Pixel("band", (single, name)), "first",
        )),))
        for name in ("y2", "y0")
    ]
    with pytest.raises(UnsupportedEEError, match="matching spatial/temporal dimensions"):
        compile_matrix_element(
            Graph(Translator(local["catalog"], local["items"], {})),
            _matrix_component(spec, tuple(mixed_time)),
        )


def test_internal_factor_components_revalidate_cycles_and_charge_work(ee, local):
    source = Source("sentinel-2-l2a", ("a",), ("y0",))
    operands = _dynamic_cells(source)
    spec = prepare_matrix_values_spec(
        "cholesky", 2, 2, 0,
        [{"band": index} for index in range(4)],
    )
    cycle = Pixel("add", (const(1.0), const(2.0)))
    object.__setattr__(cycle, "args", (cycle,))
    cyclic_operands = (Pixel("to_float", (cycle,)), *operands[1:])
    with pytest.raises(UnsupportedEEError, match="cyclic Pixel operands"):
        compile_matrix_element(
            Graph(Translator(local["catalog"], local["items"], {})),
            _matrix_component(spec, cyclic_operands),
        )

    translator = Translator(local["catalog"], local["items"], {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        compile_matrix_element(
            Graph(translator), _matrix_component(spec, operands),
        )
    assert translator.steps == 49_999
