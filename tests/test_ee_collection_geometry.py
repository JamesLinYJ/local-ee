"""Pinned Collection.geometry signature, geometry-model, and work contracts."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from gee.compat.earthengine.collection_geometry import (
    COLLECTION_GEOMETRY_ARGUMENTS,
    invoke_collection_geometry,
)
from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.error_margin import ErrorMarginValue
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.public_values import public_value
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/ee-spatial-consumers-wave63-before-v1.json"


@pytest.fixture
def ee_sdk():
    import ee

    with OfflineGuard() as guard:
        configured = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        yield configured
    assert guard.evidence()["attempt_count"] == 0


def _wire(ee, value):
    return json.loads(json.dumps(ee.serializer.encode(value, for_cloud_api=False)))


def _compile_sdk(ee, value):
    return compile_expression(_wire(ee, value), [], {})["value"]


def _rectangle(x1, y1, x2, y2, *, geodesic=None, crs=None):
    value = {
        "type": "Polygon",
        "coordinates": [[[x1, y1], [x2, y1], [x2, y2],
                         [x1, y2], [x1, y1]]],
    }
    if geodesic is not None:
        value["geodesic"] = geodesic
    if crs is not None:
        value["crs"] = crs
    return value


def _inline_collection(*geometries):
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": geometry, "properties": {}}
            for geometry in geometries
        ],
    }


def _collection_geometry(geometries, **arguments):
    translator = Translator([], {}, {})
    return invoke_collection_geometry(
        translator, {"collection": _inline_collection(*geometries), **arguments},
    )


def _algorithm_calls(value, name):
    calls = []
    if type(value) is list:
        for child in value:
            calls.extend(_algorithm_calls(child, name))
    elif type(value) is dict:
        if value.get("functionName") == name:
            calls.append(value)
        for child in value.values():
            calls.extend(_algorithm_calls(child, name))
    return calls


def test_signature_has_only_collection_and_zero_meter_default_max_error(ee_sdk):
    algorithms = json.loads(
        (ROOT / "vendor/earthengine-js/algorithms.json").read_text(encoding="utf-8")
    )["algorithms"]
    signature = next(
        item for item in algorithms if item["name"] == "algorithms/Collection.geometry"
    )
    assert COLLECTION_GEOMETRY_ARGUMENTS == {
        "Collection.geometry": (
            frozenset({"collection"}), frozenset({"maxError"}),
        ),
    }
    assert [
        (arg["argumentName"], arg["type"], arg.get("optional", False),
         arg.get("defaultValue"))
        for arg in signature["arguments"]
    ] == [
        ("collection", "FeatureCollection", False, None),
        ("maxError", "ErrorMargin", True,
         {"type": "ErrorMargin", "unit": "meters", "value": 0.0}),
    ]

    ee = ee_sdk
    collection = ee.FeatureCollection([ee.Feature(ee.Geometry.Point(0, 0))])
    omitted = _wire(ee, collection.geometry())
    explicit_null = _wire(ee, collection.geometry(maxError=None))
    explicit_zero = _wire(ee, collection.geometry(maxError=ee.ErrorMargin(0)))
    assert omitted == explicit_null
    assert set(_algorithm_calls(omitted, "Collection.geometry")[0]["arguments"]) == {
        "collection",
    }
    assert set(_algorithm_calls(explicit_zero, "Collection.geometry")[0]["arguments"]) == {
        "collection", "maxError",
    }

    translator = Translator([], {}, {})
    with pytest.raises(UnsupportedEEError):
        translator.invoke("Collection.geometry", {})
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments.*proj"):
        translator.invoke("Collection.geometry", {
            "collection": {"type": "FeatureCollection", "features": []},
            "proj": "EPSG:4326",
        })


def test_sdk_default_collection_geometry_keeps_homogeneous_s2_edges(ee_sdk):
    ee = ee_sdk
    dateline = ee.Geometry.Polygon([
        [170, -5], [-170, -5], [-170, 5], [170, 5], [170, -5],
    ])
    remote = ee.Geometry.Polygon([
        [100, -2], [110, -2], [110, 2], [100, 2], [100, -2],
    ])
    merged = ee.FeatureCollection([ee.Feature(dateline), ee.Feature(remote)]).geometry()

    result = _compile_sdk(ee, merged)
    assert result["geodesic"] is True
    assert _compile_sdk(ee, merged.contains(ee.Geometry.Point(179, 0))) is True
    assert _compile_sdk(ee, merged.contains(ee.Geometry.Point(0, 0))) is False


def test_explicit_planar_inputs_merge_and_edge_less_points_do_not_change_the_model(ee_sdk):
    ee = ee_sdk
    polygon = ee.Geometry.Polygon(
        [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]], geodesic=False,
    )
    point = ee.Geometry.Point(2, 2)
    merged = ee.FeatureCollection([ee.Feature(polygon), ee.Feature(point)]).geometry()

    result = _compile_sdk(ee, merged)
    assert result["type"] == "Polygon"
    assert result["geodesic"] is False
    assert _compile_sdk(
        ee, merged.contains(point, proj=ee.Projection("EPSG:4326")),
    ) is True


def test_empty_and_null_geometries_produce_no_fabricated_shape(ee_sdk):
    ee = ee_sdk
    empty = ee.FeatureCollection([])
    null_only = ee.FeatureCollection([ee.Feature(None, {"tag": "no geometry"})])
    expected = {"type": "GeometryCollection", "geometries": []}

    assert _compile_sdk(ee, empty.geometry()) == expected
    assert _compile_sdk(ee, null_only.geometry()) == expected


def test_nested_child_flag_overrides_collection_default_when_resolving_actual_edges():
    overridden = {
        "type": "GeometryCollection", "geodesic": False,
        "geometries": [{
            "type": "LineString", "coordinates": [[0, 0], [1, 1]],
            "geodesic": True,
        }],
    }
    default_spherical = {"type": "LineString", "coordinates": [[2, 2], [3, 3]]}

    merged = _collection_geometry([overridden, default_spherical])
    assert merged.geometry_metadata["geodesic"] is True
    assert public_value(merged)["geodesic"] is True


def test_mixed_edge_models_reject_even_when_a_large_error_margin_is_supplied():
    spherical = _rectangle(0, 0, 2, 2)
    planar = _rectangle(3, 0, 4, 1, geodesic=False)
    with pytest.raises(UnsupportedEEError, match="Mixed geodesic edge models"):
        _collection_geometry(
            [spherical, planar], maxError=ErrorMarginValue(None, "infinite"),
        )


def test_same_crs_default_and_explicit_4326_are_merged_without_reprojection():
    named_crs = {"type": "name", "properties": {"name": "EPSG:4326"}}
    first = _rectangle(0, 0, 2, 2)
    second = _rectangle(3, 0, 4, 1, crs=named_crs)

    merged = _collection_geometry([first, second])
    assert merged.geometry_metadata["crs"] == "EPSG:4326"
    assert merged.geometry_metadata["geodesic"] is True


def test_typed_error_margin_is_consumed_on_the_same_model_path_without_transform(ee_sdk):
    ee = ee_sdk
    geometry = ee.Geometry.Polygon([
        [170, -5], [-170, -5], [-170, 5], [170, 5], [170, -5],
    ])
    collection = ee.FeatureCollection([ee.Feature(geometry)])
    plain = _compile_sdk(ee, collection.geometry())
    margin = ee.ErrorMargin(12, "projected")
    encoded = _wire(ee, collection.geometry(maxError=margin))
    bounded = compile_expression(encoded, [], {})["value"]

    assert bounded == plain
    assert "Geometry.transform" not in {
        call.get("functionName")
        for call in _algorithm_calls(encoded, "Geometry.transform")
    }
    assert _algorithm_calls(encoded, "ErrorMargin")


def test_empty_map_preflights_collection_geometry_arguments_without_a_row(ee_sdk):
    ee = ee_sdk
    empty = ee.FeatureCollection([])
    mapped = empty.map(lambda row: ee.Feature(
        ee.FeatureCollection([row]).geometry(maxError=ee.ErrorMargin(1))
    ))
    encoded = _wire(ee, mapped)
    assert compile_expression(encoded, [], {})["value"] == {
        "type": "FeatureCollection", "features": [],
    }

    invalid = copy.deepcopy(encoded)
    calls = _algorithm_calls(invalid, "Collection.geometry")
    assert len(calls) == 1
    calls[0]["arguments"]["proj"] = "EPSG:4326"
    with pytest.raises(UnsupportedEEError, match="Unsupported algorithm arguments.*proj"):
        compile_expression(invalid, [], {})


def test_input_and_output_geometry_mutations_are_not_aliased():
    source = _rectangle(0, 0, 2, 2, geodesic=False)
    merged = _collection_geometry([source])
    result_before = copy.deepcopy(merged["coordinates"])

    source["coordinates"][0][0][0] = 40
    assert merged["coordinates"] == result_before
    merged["coordinates"][0][0][0] = 60
    assert source["coordinates"][0][0][0] == 40


def test_geometry_work_and_feature_count_caps_precede_binary_backend(monkeypatch):
    import gee.compat.earthengine.collection_geometry as collection_geometry
    import gee.compat.earthengine.feature_ops as feature_ops

    too_many = _inline_collection(*([None] * 1001))
    with pytest.raises(UnsupportedEEError, match="at most 1000 features"):
        invoke_collection_geometry(Translator([], {}, {}), {"collection": too_many})

    feature = {
        "type": "Feature", "geometry": _rectangle(0, 0, 1, 1, geodesic=False),
        "properties": {},
    }
    monkeypatch.setattr(feature_ops, "_features", lambda _translator, _value: [feature])
    monkeypatch.setattr(
        collection_geometry, "invoke_geometry_binary",
        lambda *_args, **_kwargs: pytest.fail("binary backend ran after work was exhausted"),
    )
    translator = Translator([], {}, {})
    translator.steps = 49_999
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        invoke_collection_geometry(
            translator, {"collection": _inline_collection(feature["geometry"])},
        )


def test_last_three_wave63_spatial_consumer_records_replay():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    records = fixture["records"][-3:]
    assert [record["name"] for record in records] == [
        "union_dateline", "union_origin", "union_planar",
    ]

    actual = [compile_expression(record["wire"], [], {})["value"] for record in records]
    assert actual == [record["expected"] for record in records]
    assert actual == [True, False, True]
    assert records[-1]["before"]["compiled"] is False
