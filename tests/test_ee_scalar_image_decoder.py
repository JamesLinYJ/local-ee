"""Root ValueRef reuse must not leak Images between callback environments."""
from __future__ import annotations

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.ir import Image, Pixel, Source
from gee.compat.earthengine.scalar_image_snapshot import MAX_SCALAR_IMAGE_SNAPSHOTS


def image(scene="first"):
    source = Source("sentinel-2-l2a", (scene,), ("red", "green", "blue"))
    return Image(
        [(name, Pixel("to_double", (Pixel("band", (source, name)),)))
         for name in source.names],
        {"scene": scene, "nested": ["original"]}, source=source,
    )


def scope_value(method="Image.rgbToHsv"):
    return {"type": "Invocation", "functionName": method, "arguments": {
        "image": {"type": "ArgumentRef", "value": "input"},
    }}


def reference(key="color"):
    return {"type": "ValueRef", "value": key}


@pytest.mark.parametrize("method", ["Image.rgbToHsv", "Image.hsvToRgb"])
def test_actual_color_valueref_owns_metadata_and_is_root_environment_only(monkeypatch, method):
    translator = Translator([], {}, {})
    env = {"input": image()}
    translator._root_env = env
    translator.scope["color"] = scope_value(method)
    calls = []
    invoke = translator.invoke

    def counted(name, arguments):
        calls.append(name)
        return invoke(name, arguments)

    monkeypatch.setattr(translator, "invoke", counted)
    first = translator.evaluate(reference(), env, depth=1)
    first.props["nested"].append("private")
    second = translator.evaluate(reference(), env, depth=1)
    assert calls == [method]
    assert second.props["nested"] == ["original"]
    assert second.source.ids == ("first",)
    assert all(a is b for (_name, a), (_other, b) in zip(first.bands, second.bands))
    for scene in ("callback-a", "callback-b"):
        mapped = translator.evaluate(reference(), {"input": image(scene)}, depth=1)
        assert mapped.source.ids == (scene,)
        assert mapped.props["scene"] == scene
    assert len(calls) == 3
    translator.evaluate(reference(), env, depth=0)
    assert len(calls) == 4
    assert translator._root_scalar_image_snapshots == 1


def test_function_invocations_do_not_reuse_a_root_valueref_in_callback_scope():
    translator = Translator([], {}, {})
    root = {"input": image()}
    translator._root_env = root
    translator.scope["color"] = scope_value()
    translator.evaluate(reference(), root, depth=1)
    for scene in ("callback-a", "callback-b"):
        invocation = {"type": "Invocation", "function": {
            "type": "Function", "argumentNames": ["input"], "body": reference(),
        }, "arguments": {"input": image(scene)}}
        output = translator.evaluate(invocation, root, depth=1)
        assert output.source.ids == (scene,)
    assert translator._root_scalar_image_snapshots == 1


def test_scalar_admissions_stop_at_64_and_do_not_expand_existing_500_limit(monkeypatch):
    translator = Translator([], {}, {})
    env = {"input": image()}
    translator._root_env = env
    # Isolate the decoder capacity policy from the color kernel's own cache.
    monkeypatch.setattr(translator, "invoke", lambda _name, args: args["image"])
    for index in range(MAX_SCALAR_IMAGE_SNAPSHOTS + 1):
        key = f"color-{index}"
        translator.scope[key] = scope_value()
        translator.evaluate(reference(key), env, depth=1)
    assert len(translator._root_value_cache) == 64
    assert translator._root_scalar_image_snapshots == 64
    assert "color-64" not in translator._root_value_cache
    translator._root_value_cache = {f"existing-{index}": None for index in range(500)}
    translator._root_scalar_image_snapshots = 0
    translator.evaluate(reference("color-64"), env, depth=1)
    assert len(translator._root_value_cache) == 500
    assert translator._root_scalar_image_snapshots == 0


def test_non_whitelisted_image_invocation_is_evaluated_each_time(monkeypatch):
    translator = Translator([], {}, {})
    env = {"input": image()}
    translator._root_env = env
    translator.scope["color"] = scope_value("Image.select")
    calls = []

    def invoke(name, args):
        calls.append(name)
        return args["image"]

    monkeypatch.setattr(translator, "invoke", invoke)
    translator.evaluate(reference(), env, depth=1)
    translator.evaluate(reference(), env, depth=1)
    assert calls == ["Image.select", "Image.select"]
    assert not translator._root_value_cache
