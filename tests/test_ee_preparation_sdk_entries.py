"""Every new declaration serializes and computes through the pinned Python SDK."""
from pathlib import Path

import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import compile_expression
from scripts.ee_inventory.feature_preparation import FEATURE_PREPARATION_LIMITS
from scripts.ee_python_api.offline import OfflineGuard


ROOT = Path(__file__).resolve().parents[1]
POINT = {"type": "Point", "coordinates": [110, 30]}


@pytest.fixture
def sdk():
    with OfflineGuard() as guard:
        ee = configure_local_ee(
            "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
            signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
        )
        yield ee
    assert guard.evidence()["attempt_count"] == 0


def _case(ee, name):
    point = ee.Geometry.Point([110, 30])
    feature = ee.Feature(point, {
        "system:index": "a", "v": 7, "name": "A", "arr": ee.Array([1, 2]),
    })
    if name.startswith("Filter."):
        operation = name.split(".", 1)[1]
        arguments = {"leftField": "v", "rightValue": 7}
        counts = {
            "eq": 1, "gt": 1, "gte": 2, "lt": 0, "lte": 1, "neq": 1,
            "notEquals": 1, "greaterThanOrEquals": 2, "lessThanOrEquals": 1,
            "stringStartsWith": 1, "stringEndsWith": 1, "rangeContains": 1,
            "dayOfYear": 1, "always": 2, "never": 0, "hasGeometry": 1,
        }
        if operation in {"stringStartsWith", "stringEndsWith"}:
            arguments = {"leftField": "name", "rightValue": "A"}
        elif operation == "rangeContains":
            arguments = {"field": "v", "minValue": 5, "maxValue": 7}
        elif operation == "dayOfYear":
            arguments = {"start": 60, "end": 60}
        elif operation in {"always", "never", "hasGeometry"}:
            arguments = {}
        # Call the exact signature, including aliases which public helpers
        # usually lower client-side, then consume the actual Filter value.
        predicate = ee.Filter(ee.ApiFunction.call_(name, **arguments))
        rows = ee.FeatureCollection([
            feature.set("system:time_start", ee.Date("2024-02-29").millis()),
            ee.Feature(None, {
                "system:index": "b", "v": 9, "name": "B",
                "system:time_start": ee.Date("2024-03-01").millis(),
            }),
        ])
        return rows.filter(predicate).size(), counts[operation]

    cases = {
        "Element.getNumber": ({"object": feature, "property": "v"}, 7),
        "Element.getString": ({"object": feature, "property": "name"}, "A"),
        "Element.getArray": ({"object": feature, "property": "arr"}, [1, 2]),
        "Element.toDictionary": (
            {"element": feature, "properties": ["v", "name"]}, {"v": 7, "name": "A"},
        ),
        "Element.replaceProperties": (
            {"destination": feature, "source": ee.Feature(None, {"new": 8})},
            {"type": "Feature", "geometry": POINT, "properties": {"new": 8}, "id": "a"},
        ),
        "Feature.id": ({"element": feature}, "a"),
        "Feature.geometry": ({"feature": feature}, POINT),
        "Feature.select": (
            {"input": feature, "propertySelectors": ["v"],
             "newProperties": ["value"], "retainGeometry": False},
            {"type": "Feature", "geometry": None, "properties": {"value": 7}, "id": "a"},
        ),
        "Feature.setGeometry": (
            {"feature": feature, "geometry": ee.Geometry.Point([111, 31])},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [111, 31]},
             "properties": {"system:index": "a", "v": 7, "name": "A", "arr": [1, 2]}},
        ),
        "Feature.toArray": ({"feature": feature, "properties": ["v"]}, [7]),
        "Geometry.type": ({"geometry": point}, "Point"),
        "Geometry.coordinates": ({"geometry": point}, [110, 30]),
        "Geometry.geometries": ({"geometry": point}, [POINT]),
        "Geometry.isUnbounded": ({"geometry": point}, False),
        "Geometry.edgesAreGeodesics": ({"geometry": point}, True),
        "Geometry.geodesic": ({"geometry": point}, True),
        "GeometryConstructors.BBox": (
            {"west": 0, "south": 0, "east": 2, "north": 1},
            {"type": "Polygon", "coordinates": [[[0, 1], [0, 0], [2, 0], [2, 1], [0, 1]]],
             "geodesic": False},
        ),
        "GeometryConstructors.MultiGeometry": (
            {"geometries": [point], "geodesic": False},
            {"type": "GeometryCollection", "geometries": [POINT], "geodesic": False},
        ),
        "GeometryConstructors.LinearRing": (
            {"coordinates": [[0, 0], [2, 0], [2, 2]], "geodesic": False},
            {"type": "LinearRing", "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
             "geodesic": False},
        ),
    }
    arguments, expected = cases[name]
    return ee.ApiFunction.call_(name, **arguments), expected


def _invocations(value):
    if isinstance(value, dict):
        if value.get("type") == "Invocation":
            yield value.get("functionName")
        for child in value.values():
            yield from _invocations(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _invocations(child)


@pytest.mark.parametrize("name", sorted(FEATURE_PREPARATION_LIMITS))
def test_every_preparation_entry_has_real_sdk_serialization_and_finite_result(sdk, name):
    expression, expected = _case(sdk, name)
    encoded = sdk.serializer.encode(expression, for_cloud_api=False)
    assert name in set(_invocations(encoded))
    result = compile_expression(encoded, [], {}, {})
    assert result["kind"] == "value"
    assert result["value"] == expected
