"""Official Float32 Boolean expressions preserve missing inputs and valid0."""
from __future__ import annotations

import numpy as np
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Image, const
from gee.compat.earthengine.callback_masks import preserve_callback_masks
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from scripts.ee_python_api.offline import OfflineGuard
from scripts.ee_python_api.probe_cases import synthetic_inputs
import test_ee_translate as graph_reference
from test_ee_translate import evaluate_graph


@pytest.mark.parametrize("formula,expected", [
    ("r > 0", [1, 1, None, 0, 0]),
    ("r < 0", [0, 0, None, 1, 0]),
    ("(r > 0) && (n > 0)", [1, None, None, 0, 0]),
    ("(r > 0) || (n > 0)", [1, None, None, 1, 0]),
    ("!(r > 0)", [0, 0, None, 1, 1]),
    ("r == n", [0, None, None, 0, 1]),
    ("r && n", [1, None, None, 1, 0]),
    ("r || n", [1, None, None, 1, 0]),
    ("!r", [0, 0, None, 0, 1]),
])
def test_boolean_inputs_keep_nodata_in_compiled_callback(formula, expected, monkeypatch):
    original = graph_reference.eval_process

    def upstream_local_logic(operation, arguments):
        # The native probe measured bitwise And/Or/Not, including Not(1)=-2.
        # Model that backend behavior here so logical NumPy defaults cannot
        # conceal a missing normalization or a raw Not in the validity guard.
        if operation in {"and", "or", "not"}:
            x = np.nan_to_num(np.asarray(arguments["x"]), nan=0).astype(np.int32)
            if operation == "not":
                return np.bitwise_not(x)
            y = np.nan_to_num(np.asarray(arguments["y"]), nan=0).astype(np.int32)
            return np.bitwise_and(x, y) if operation == "and" else np.bitwise_or(x, y)
        return original(operation, arguments)

    monkeypatch.setattr(graph_reference, "eval_process", upstream_local_logic)
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path="vendor/earthengine-js/algorithms.json",
        )
        metadata, items, _ = synthetic_inputs()
        image = ee.Image("scene-a")
        value = ee.Image().expression(formula, {
            "r": image.select("red"), "n": image.select("nir"),
        })
        compiled = compile_expression(
            ee.serializer.encode(value, for_cloud_api=False), [metadata], items,
        )
    assert guard.evidence()["attempt_count"] == 0
    arrays = {"scene-a": {
        "red": np.asarray([1, 2, np.nan, -1, 0], dtype=float),
        "nir": np.asarray([3, np.nan, 5, 2, 0], dtype=float),
    }}
    values, _names, temporal = evaluate_graph(compiled, arrays)
    assert temporal is False
    reference = [[np.nan if value is None else value for value in expected]]
    np.testing.assert_array_equal(values, reference)


def test_boolean_mask_precharge_rejects_before_changing_callback():
    translator = Translator([], {}, {})
    translator.steps = 49_999
    callback = {}
    with pytest.raises(UnsupportedEEError, match="50000"):
        preserve_callback_masks(Graph(translator), "gt", callback, [1, 0],
                                [(0, (None, "red", False))], "gt", {"x": 1, "y": 0})
    assert callback == {}
    assert translator.steps == 49_999
