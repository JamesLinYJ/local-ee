"""Pinned Python SDK notNull serialization and bounded local metadata semantics."""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from gee import ee_python_client
from gee.ee_translate import Translator, UnsupportedEEError, compile_expression


SIGNATURES = Path(__file__).resolve().parents[1] / "vendor/earthengine-js/algorithms.json"


@pytest.fixture
def ee_sdk(monkeypatch):
    import ee

    def reset():
        ee.Reset()
        for name in ("_local_ee_runtime", "Map"):
            if hasattr(ee, name):
                delattr(ee, name)
        if hasattr(ee.data, "_local_ee_tasks_installed"):
            del ee.data._local_ee_tasks_installed
        importlib.reload(ee.data)
        importlib.reload(ee.oauth)
        importlib.reload(ee)

    class OfflineTransport:
        def __init__(self, *_args, **_kwargs):
            pass

        def request(self, *_args, **_kwargs):
            pytest.fail("Metadata filter compilation must not contact a service")

    reset()
    monkeypatch.setattr(ee_python_client, "LocalEETransport", OfflineTransport)
    ee_python_client.configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48, signatures_path=SIGNATURES
    )
    yield ee
    reset()


def local_data():
    catalog = [{
        "id": "sentinel-2-l2a",
        "cube:dimensions": {"bands": {"values": ["red", "nir"]}},
    }]
    values = [
        ("missing", {}),
        ("null", {"value": None}),
        ("zero", {"value": 0}),
        ("false", {"value": False}),
        ("empty-string", {"value": ""}),
        ("empty-list", {"value": []}),
        ("empty-dict", {"value": {}}),
        ("second-missing", {"value": 7}),
        ("second-null", {"value": 8, "other": None}),
    ]
    items = []
    for name, properties in values:
        items.append({
            "id": name,
            "properties": {
                "system:index": name,
                **({"other": 0} if name not in {"second-missing", "second-null"} else {}),
                **properties,
            },
        })
    return catalog, {"sentinel-2-l2a": items}


def compiled_value(ee, expression, local=None):
    serialized = ee.serializer.encode(expression, for_cloud_api=False)
    return compile_expression(serialized, *(local or local_data()))["value"]


@pytest.mark.parametrize(("properties", "expected"), [
    (["value"], ["zero", "false", "empty-string", "empty-list", "empty-dict", "second-missing", "second-null"]),
    (["value", "other"], ["zero", "false", "empty-string", "empty-list", "empty-dict"]),
    (["value", "value"], ["zero", "false", "empty-string", "empty-list", "empty-dict", "second-missing", "second-null"]),
    (["never-present"], []),
    ([], ["missing", "null", "zero", "false", "empty-string", "empty-list", "empty-dict", "second-missing", "second-null"]),
])
def test_pinned_python_not_null_treats_only_missing_and_null_as_absent(ee_sdk, properties, expected):
    ee = ee_sdk
    filtered = ee.ImageCollection("sentinel-2-l2a").filter(ee.Filter.notNull(properties=properties))
    assert compiled_value(ee, filtered.aggregate_array("system:index")) == expected


def test_not_null_after_dynamic_map_reads_each_items_properties(ee_sdk):
    ee = ee_sdk
    mapped = ee.ImageCollection("sentinel-2-l2a").map(
        lambda image: image.set("copied", image.get("value"))
    )
    filtered = mapped.filter(ee.Filter.notNull(["copied", "other"]))
    assert compiled_value(ee, filtered.aggregate_array("system:index")) == [
        "zero", "false", "empty-string", "empty-list", "empty-dict"
    ]


def test_not_null_and_negation_preserve_absent_property_semantics(ee_sdk):
    ee = ee_sdk
    collection = ee.ImageCollection("sentinel-2-l2a")
    present = ee.Filter.notNull(["value"])
    assert compiled_value(ee, collection.filter(present.Not()).aggregate_array("system:index")) == [
        "missing", "null"
    ]
    both = ee.Filter.And(present, ee.Filter.notNull(["other"]))
    assert compiled_value(ee, collection.filter(both).aggregate_array("system:index")) == [
        "zero", "false", "empty-string", "empty-list", "empty-dict"
    ]


@pytest.mark.parametrize("properties", [None, "value", {}, [1], [True], [None], [["value"]]])
def test_invalid_property_lists_have_explicit_errors(properties):
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="properties must be a list of strings"):
        translator.invoke("Filter.notNull", {"properties": properties})


def test_unknown_arguments_and_missing_properties_are_rejected():
    translator = Translator([], {}, None)
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments"):
        translator.invoke("Filter.notNull", {"properties": ["value"], "ignoreMissing": True})
    with pytest.raises(UnsupportedEEError, match="properties must be a list of strings"):
        translator.invoke("Filter.notNull", {})


def test_property_limit_accepts_boundary_and_rejects_excess():
    translator = Translator([], {}, None)
    predicate = translator.invoke("Filter.notNull", {"properties": ["value"] * 1000})
    assert translator.matches(predicate, {"properties": {"value": 0}})
    with pytest.raises(UnsupportedEEError, match="at most 1000 properties"):
        translator.invoke("Filter.notNull", {"properties": ["value"] * 1001})


def test_property_scan_uses_the_total_compilation_budget():
    translator = Translator([], {}, None)
    predicate = translator.invoke("Filter.notNull", {"properties": ["value"] * 1000})
    item = {"properties": {"value": False}}
    for _ in range(49):
        assert translator.matches(predicate, item)
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        translator.matches(predicate, item)


def test_empty_predicate_still_budgets_catalogue_scan():
    translator = Translator([], {}, None)
    predicate = translator.invoke("Filter.notNull", {"properties": []})
    translator.steps = 49999
    assert translator.matches(predicate, {"properties": {}})
    with pytest.raises(UnsupportedEEError, match="compilation limits"):
        translator.matches(predicate, {"properties": {}})
