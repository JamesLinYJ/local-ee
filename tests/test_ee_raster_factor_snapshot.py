"""Shared SDK factor nodes retain scalar identity with owned mutable metadata."""
import numpy as np
import pytest

from ee_matrix_factor_compiler_helpers import array
from gee.compat.earthengine.array_core import StaticArray
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Pixel, Source, UnsupportedEEError
from gee.compat.earthengine.raster_matrix_decomposition import invoke_raster_matrix_decomposition
from gee.compat.earthengine.raster_factor_snapshot import (
    FactorSnapshot, restore_factor, snapshot_factor,
)


def _bundle():
    value = array(np.array([[1.0, 2.0], [3.0, 5.0]]))
    value.image.props = {"nested": {"labels": ["original"]}}
    value.image.footprint = {"type": "Point", "coordinates": [1.0, 2.0]}
    return invoke_raster_matrix_decomposition(
        Translator([], {}, {}), "Image.matrixQRDecomposition", {"image": value},
    )


def test_storage_and_each_restore_own_metadata_but_share_proven_immutable_cells():
    translator = Translator([], {}, {})
    original = _bundle()
    snapshot = snapshot_factor(translator, original)
    assert type(snapshot) is FactorSnapshot
    original.image.props["nested"]["labels"].append("changed")
    original.image.footprint["coordinates"][0] = 999
    first = restore_factor(translator, snapshot)
    assert first.image.props == {"nested": {"labels": ["original"]}}
    assert first.image.footprint["coordinates"] == [1.0, 2.0]
    first.image.props["nested"]["labels"].append("private")
    first.image.footprint["coordinates"][1] = 333
    second = restore_factor(translator, snapshot)
    assert second.image.props == {"nested": {"labels": ["original"]}}
    assert second.image.footprint["coordinates"] == [1.0, 2.0]
    assert first is not second and first.image is not second.image
    assert all(a.image is first.image for a in first.arrays)
    assert all(a.cells is b.cells and a.mask is b.mask
               for a, b in zip(first.arrays, second.arrays))


def test_unknown_or_joined_metadata_is_not_cached():
    original = _bundle()
    original.image.props["typed"] = StaticArray(np.eye(2))
    assert snapshot_factor(Translator([], {}, {}), original) is None
    original.image.props = {}
    original.image.mapped = True
    assert snapshot_factor(Translator([], {}, {}), original) is None


def test_mutable_descendants_and_cycles_prevent_scalar_identity_sharing():
    from dataclasses import replace

    original = _bundle()
    mutable = [Pixel("constant", (1.0,))]
    bad = replace(original.arrays[0], cells=(Pixel("unsafe", (mutable,)), *original.arrays[0].cells[1:]))
    assert snapshot_factor(Translator([], {}, {}), replace(original, arrays=(bad,))) is None
    cycle = []
    cycle.append(cycle)
    original.image.props = {"cycle": cycle}
    assert snapshot_factor(Translator([], {}, {}), original) is None
    original.image.props = {}
    original.image.source = Source("synthetic", ("scene",), ["mutable"])
    assert snapshot_factor(Translator([], {}, {}), original) is None


def test_restore_precharges_before_any_metadata_copy(monkeypatch):
    snapshot = snapshot_factor(Translator([], {}, {}), _bundle())
    translator = Translator([], {}, {})
    translator.steps = 49_999

    def unexpected(*_args, **_kwargs):
        raise AssertionError("metadata copied before work admission")

    monkeypatch.setattr("gee.compat.earthengine.raster_factor_snapshot.copy.deepcopy", unexpected)
    with pytest.raises(UnsupportedEEError, match="work budget"):
        restore_factor(translator, snapshot)
    assert translator.steps == 49_999


def test_factor_valueref_reuse_is_root_only_and_clears_on_next_evaluation(monkeypatch):
    value = array(np.array([[1.0, 2.0], [3.0, 5.0]]))
    translator = Translator([], {}, {})
    env = {"input": value}
    translator._root_env = env
    translator.scope["factor"] = {
        "type": "Invocation", "functionName": "Image.matrixQRDecomposition",
        "arguments": {"image": {"type": "ArgumentRef", "value": "input"}},
    }
    reference = {"type": "ValueRef", "value": "factor"}
    calls = []
    original = translator.invoke

    def invoke(name, arguments):
        calls.append(name)
        return original(name, arguments)

    monkeypatch.setattr(translator, "invoke", invoke)
    first = translator.evaluate(reference, env, depth=1)
    first.image.props["private"] = ["changed"]
    second = translator.evaluate(reference, env, depth=1)
    assert calls == ["Image.matrixQRDecomposition"]
    assert "private" not in second.image.props
    assert first.arrays[0].cells is second.arrays[0].cells
    translator.evaluate(reference, dict(env), depth=1)
    translator.evaluate(reference, dict(env), depth=1)
    assert len(calls) == 3
    translator.evaluate(reference, env, depth=0)
    assert len(calls) == 4
