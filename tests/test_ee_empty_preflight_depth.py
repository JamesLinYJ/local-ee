"""Memoized empty callbacks still obey every occurrence's expanded depth."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.feature_map_preflight import preflight_empty_feature_map
from gee.compat.earthengine.ir import Function, UnsupportedEEError


def chain(value, count):
    for _ in range(count):
        value = {"type": "Invocation", "functionName": "Number.abs",
                 "arguments": {"input": value}}
    return value


def run(body, scope=None):
    translator = Translator([], {}, {})
    translator.scope.update(scope or {})
    preflight_empty_feature_map(translator, Function(["image", "state"], body, {}))
    return translator.steps


@pytest.mark.parametrize("outer,depth", [(64, 96), (65, 97), (70, 102)])
@pytest.mark.parametrize("deep_first", [False, True])
def test_value_ref_depth_is_independent_of_prior_shallow_visit(outer, depth, deep_first):
    scope = {"shared": chain(1, 30)}
    reference = lambda: {"type": "ValueRef", "value": "shared"}
    fields = [("shallow", reference()), ("deep", chain(reference(), outer))]
    if deep_first:
        fields.reverse()
    body = {"type": "Dictionary", "value": dict(fields)}
    if depth <= 96:
        assert 0 < run(body, scope) < 50_000
    else:
        with pytest.raises(UnsupportedEEError, match="serialized depth limit"):
            run(body, scope)


@pytest.mark.parametrize("outer,accept", [(65, True), (66, False), (71, False)])
def test_shared_container_depth_is_rechecked_without_a_value_ref(outer, accept):
    shared = chain(1, 30)
    body = {"type": "Dictionary", "value": {
        "shallow": shared, "deep": chain(shared, outer),
    }}
    if accept:
        run(body)
    else:
        with pytest.raises(UnsupportedEEError, match="serialized depth limit"):
            run(body)


def test_nested_compound_scope_cannot_reuse_a_different_scope_height():
    # The same reference dictionary resolves to different local definitions.
    # Scope identity is part of the cache key and must remain strongly owned.
    reference = {"type": "ValueRef", "value": "local"}
    shallow = {"type": "CompoundValue", "scope": [["local", 1]], "value": reference}
    deep = {"type": "CompoundValue", "scope": [["local", chain(1, 95)]],
            "value": reference}
    body = [shallow, deep]
    with pytest.raises(UnsupportedEEError, match="serialized depth limit"):
        run(body)


def test_repeated_valid_subtree_keeps_the_existing_work_limit():
    shared = chain(1, 30)
    body = [shared] * 1000
    assert 1000 < run(body) < 5000
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="work budget"):
        preflight_empty_feature_map(translator, Function(["image", "state"], body, {}))
    assert translator.steps <= 50_000


@pytest.mark.parametrize("name,arguments", [
    ("Image.select", {"input": 1}),
    ("Image.rename", {"input": 1}),
    ("Image.addBands", {"dstImg": 1}),
    ("Image.bandNames", {}),
    ("Image.constant", {}),
    ("Collection.iterate", {"collection": []}),
])
def test_empty_iteration_validates_new_band_state_signatures(name, arguments):
    body = {"type": "Invocation", "functionName": name, "arguments": arguments}
    with pytest.raises(UnsupportedEEError, match="missing required arguments"):
        run(body)


def test_empty_iteration_rejects_unknown_add_bands_keyword():
    body = {"type": "Invocation", "functionName": "Image.addBands",
            "arguments": {"dstImg": 1, "srcImg": 2, "overWrite": True}}
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        run(body)
