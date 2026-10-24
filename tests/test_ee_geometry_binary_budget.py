"""Pre-GEOS admission and reservation checks for binary geometry work."""
import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_binary import invoke_geometry_binary
from gee.compat.earthengine.geometry_preflight import measure_geometry
from gee.ee_translate import UnsupportedEEError


def translator(steps=0):
    result = Translator([], {}, {})
    result.steps = steps
    return result


def rectangle(x1, y1, x2, y2):
    return {
        "type": "Polygon",
        "coordinates": [[[x1, y1], [x2, y1], [x2, y2],
                         [x1, y2], [x1, y1]]],
        "geodesic": False,
    }


def line(*coordinates):
    return {"type": "LineString", "coordinates": [list(item) for item in coordinates],
            "geodesic": False}


def call(name, left, right, translator_value=None):
    return invoke_geometry_binary(translator_value or translator(), name, {
        "left": left, "right": right, "proj": "EPSG:4326",
    })


def test_growth_and_compiler_budget_reject_before_decode_or_geos(monkeypatch):
    import shapely.geometry
    import gee.compat.earthengine.geometry_binary as binary

    called = []
    decoded = []
    monkeypatch.setattr(binary, "shape", lambda value: called.append(value))
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: called.append(value))
    monkeypatch.setattr(binary, "decode_geometry_bounded",
                        lambda *args: decoded.append(args))
    too_complex = line(*[(index, 0) for index in range(102)])
    with pytest.raises(UnsupportedEEError, match="10000 coordinate positions"):
        call("Geometry.intersection", too_complex, too_complex)
    assert not called and not decoded

    left, right = rectangle(0, 0, 2, 2), rectangle(1, 1, 3, 3)
    left_cost, right_cost = measure_geometry(left), measure_geometry(right)
    scan_work = 2 * (left_cost.nodes + left_cost.positions
                     + right_cost.nodes + right_cost.positions)
    decode_work = (left_cost.nodes + left_cost.positions + 3 * left_cost.ring_closures
                   + right_cost.nodes + right_cost.positions + 3 * right_cost.ring_closures)
    budgeted = translator(50_000 - scan_work - decode_work + 1)
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        call("Geometry.intersection", left, right, translator_value=budgeted)
    assert not called and not decoded
    assert budgeted.steps < 50_000


def test_point_only_pair_work_rejects_before_decode_or_geos(monkeypatch):
    import shapely.geometry
    import gee.compat.earthengine.geometry_binary as binary

    called = []
    decoded = []
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: called.append(value))
    monkeypatch.setattr(binary, "decode_geometry_bounded",
                        lambda *args: decoded.append(args))
    points = {"type": "MultiPoint", "coordinates": [[index / 1000, 0]
                                                       for index in range(200)]}
    with pytest.raises(UnsupportedEEError, match="50000-step"):
        call("Geometry.intersects", points, points)
    assert not called and not decoded


def test_overlay_child_limit_rejects_before_decode_or_geos(monkeypatch):
    import shapely.geometry
    import gee.compat.earthengine.geometry_binary as binary

    called = []
    decoded = []
    monkeypatch.setattr(shapely.geometry, "shape", lambda value: called.append(value))
    monkeypatch.setattr(binary, "decode_geometry_bounded",
                        lambda *args: decoded.append(args))
    points = {"type": "MultiPoint", "coordinates": [[index / 10000, 0]
                                                       for index in range(510)]}
    with pytest.raises(UnsupportedEEError, match="1000 GeometryCollection children"):
        call("Geometry.union", points, points)
    assert not called and not decoded


def test_worst_case_output_reservation_remains_charged_after_overlay():
    budget = translator()
    result = call("Geometry.intersection", rectangle(0, 0, 2, 2),
                  rectangle(1, 1, 3, 3), translator_value=budget)
    assert result["type"] == "Polygon"
    assert budget.steps > 2_000
