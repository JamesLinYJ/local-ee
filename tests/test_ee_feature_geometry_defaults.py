"""Pinned SDK defaults and owned Feature.geometry extraction."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_topology import component_model
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from tests.ee_random_split_parity import JAVASCRIPT


ROOT = Path(__file__).resolve().parents[1]
_POLYGON_COORDINATES = [[
    [0, 0], [2, 0], [2, 1], [0, 1], [0, 0],
]]
_POLYGON = {"type": "Polygon", "coordinates": _POLYGON_COORDINATES}


@pytest.fixture
def ee_sdk():
    import ee

    assert ee.__version__ == "1.7.49"
    configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2",
        "a" * 48,
        signatures_path=str(ROOT / "vendor/earthengine-js/algorithms.json"),
    )
    return ee


def _compile_sdk(ee, value):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, [], {})["value"]


def _call_arguments(expression, name="Feature.geometry"):
    calls = [
        value["arguments"] for _, value in expression["scope"]
        if isinstance(value, dict) and value.get("functionName") == name
    ]
    assert len(calls) == 1
    return calls[0]


def _invoke(geometry, *, translator=None, **options):
    active_translator = translator or Translator([], {}, {})
    feature = {"type": "Feature", "geometry": geometry, "properties": {}}
    return active_translator.invoke(
        "Feature.geometry", {"feature": feature, **options},
    )


def _javascript_default_wire():
    startup = JAVASCRIPT.split("const config = JSON.parse")[0]
    source = startup + r"""
const feature = ee.Feature(ee.Geometry.Polygon([[[0,0],[2,0],[2,1],[0,1],[0,0]]]));
const expression = ee.Serializer.encode(feature.geometry());
if (attempts !== 0) throw Error('Default wire probe attempted networking');
process.stdout.write(JSON.stringify({expression, attempts}));
"""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to inspect the pinned JavaScript SDK wire")
    result = subprocess.run(
        [node, "-e", source], cwd=ROOT, check=True,
        capture_output=True, text=True, timeout=30,
    )
    document = json.loads(result.stdout)
    assert document["attempts"] == 0
    return document["expression"]


def test_pinned_python_and_javascript_sdk_defaults_send_only_feature(ee_sdk):
    ee = ee_sdk
    feature = ee.Feature(ee.Geometry.Polygon(_POLYGON_COORDINATES))
    python_wire = ee.serializer.encode(feature.geometry(), for_cloud_api=False)
    javascript_wire = _javascript_default_wire()

    assert _call_arguments(python_wire).keys() == {"feature"}
    assert _call_arguments(javascript_wire).keys() == {"feature"}
    assert _compile_sdk(ee, feature.geometry()) == {
        **_POLYGON, "evenOdd": True,
    }


def test_feature_geometry_defaults_and_no_projection_flag_preserve_spherical_edges(ee_sdk):
    ee = ee_sdk
    feature = ee.Feature(ee.Geometry.Polygon(_POLYGON_COORDINATES))
    expected = {**_POLYGON, "evenOdd": True}

    assert _compile_sdk(ee, feature.geometry()) == expected
    # The fixed SDK documents geodesics as ignored when proj is omitted.
    assert _compile_sdk(ee, feature.geometry(geodesics=True)) == expected
    assert _compile_sdk(ee, feature.geometry(geodesics=False)) == expected
    assert _compile_sdk(ee, feature.geometry(
        proj=ee.Projection("EPSG:4326"), geodesics=True,
    )) == expected
    assert _compile_sdk(ee, ee.Feature(None, {}).geometry()) is None


def test_explicit_same_model_is_supported_but_edge_model_changes_are_rejected():
    spherical = GeometryValue(
        _POLYGON, {"crs": "EPSG:4326", "geodesic": True, "evenOdd": True},
        validated=True,
    )
    planar = GeometryValue(
        {**_POLYGON, "geodesic": False},
        {"crs": "EPSG:4326", "geodesic": False, "evenOdd": True},
        validated=True,
    )

    result = _invoke(spherical, proj="EPSG:4326", geodesics=True)
    assert result is not spherical
    assert component_model(result) is True
    assert component_model(_invoke(planar, proj="EPSG:4326", geodesics=False)) is False
    with pytest.raises(UnsupportedEEError, match="edge-model conversion is unsupported"):
        _invoke(spherical, proj="EPSG:4326", geodesics=False)
    with pytest.raises(UnsupportedEEError, match="edge-model conversion is unsupported"):
        _invoke(planar, proj="EPSG:4326", geodesics=True)


@pytest.mark.parametrize("impostor", [0, 1])
def test_feature_geometry_rejects_unimplemented_parameters_and_bad_boolean_types(ee_sdk, impostor):
    ee = ee_sdk
    feature = ee.Feature(ee.Geometry.Polygon(_POLYGON_COORDINATES))

    with pytest.raises(UnsupportedEEError, match="EPSG:4326"):
        _compile_sdk(ee, feature.geometry(proj=ee.Projection("EPSG:3857")))

    expression = ee.serializer.encode(
        feature.geometry(maxError=ee.ErrorMargin(1)), for_cloud_api=False,
    )
    assert "maxError" in _call_arguments(expression)
    with pytest.raises(UnsupportedEEError, match="maxError reprojection is unsupported"):
        compile_expression(expression, [], {})

    with pytest.raises(UnsupportedEEError, match="geodesics must be a boolean or null"):
        _invoke(_POLYGON, geodesics=impostor)


def test_feature_geometry_returns_an_owned_copy_and_keeps_collection_inheritance():
    source = GeometryValue(
        {
            "type": "GeometryCollection",
            "geometries": [{
                "type": "LineString", "coordinates": [[0, 0], [2, 0]],
            }],
        },
        {"crs": "EPSG:4326", "geodesic": False, "evenOdd": True},
        validated=True,
    )

    result = _invoke(source)

    assert result is not source
    assert result["geometries"][0] is not source["geometries"][0]
    assert result["geometries"][0]["coordinates"] == [[0, 0], [2, 0]]
    assert "geodesic" not in result["geometries"][0]
    assert result.geometry_metadata["geodesic"] is False
    assert component_model(result) is False

    source["geometries"][0]["coordinates"][0][0] = 99
    source.geometry_metadata["geodesic"] = True
    assert result["geometries"][0]["coordinates"] == [[0, 0], [2, 0]]
    assert result.geometry_metadata["geodesic"] is False
    assert component_model(result) is False

    source["geometries"][0]["coordinates"][0][0] = 999
    with pytest.raises(UnsupportedEEError, match="longitude/latitude bounds"):
        _invoke(source)


@pytest.mark.parametrize("options", [
    {},
    {"proj": "EPSG:4326", "geodesics": True},
])
def test_feature_geometry_reuses_the_shared_50000_work_budget(options):
    geometry = GeometryValue(
        _POLYGON,
        {"crs": "EPSG:4326", "geodesic": True, "evenOdd": True},
        validated=True,
    )
    translator = Translator([], {}, {})
    result = _invoke(geometry, translator=translator, **options)
    measured_work = translator.steps
    assert measured_work > 0
    assert translator.steps <= 50000
    assert result is not geometry

    exhausted = Translator([], {}, {})
    exhausted.steps = 50000 - measured_work + 1
    with pytest.raises(UnsupportedEEError, match="50000|compilation limits"):
        _invoke(geometry, translator=exhausted, **options)


def test_feature_geometry_does_not_expose_the_private_full_sphere_value():
    from gee.compat.earthengine.spherical_wire import FULL_SPHERE

    with pytest.raises(UnsupportedEEError, match="Inline Feature geometry"):
        _invoke(FULL_SPHERE)
