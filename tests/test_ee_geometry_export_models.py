"""Bounded model materialization before trusted EE table JSON serialization."""
from __future__ import annotations

import json

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.geometry_values import GeometryValue
from gee.compat.earthengine.ir import UnsupportedEEError
from gee.compat.earthengine.public_values import public_result
from gee.compat.earthengine.spherical_wire import FULL_SPHERE


def line(*, model=True):
    return GeometryValue(
        {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        {"crs": "EPSG:4326", "geodesic": model, "evenOdd": True},
    )


def test_table_output_preserves_effective_model_while_generic_output_keeps_omissions():
    source = line()
    public = public_result({"value": source})
    assert public["value"] == dict(source)
    assert "geodesic" not in public["value"]
    translator = Translator([], {}, {})
    table = public_result({"value": source}, geometry_translator=translator)
    assert table["value"] == {**source, "geodesic": True}
    assert translator.steps > 0
    assert "geodesic" not in source
    assert "geometry_metadata" not in json.dumps(table)
    source["coordinates"][0][0] = 99
    assert table["value"]["coordinates"][0][0] == 0


def test_nested_collection_inheritance_and_explicit_override_survive_json():
    inherited = line(model=False)
    explicit = line(model=False)
    explicit["geodesic"] = False
    polygon = GeometryValue({
        "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]],
    }, {"geodesic": False, "evenOdd": True})
    source = GeometryValue({
        "type": "GeometryCollection", "geometries": [inherited, explicit, polygon],
    }, {"geodesic": True, "evenOdd": False})
    result = public_result(source, geometry_translator=Translator([], {}, {}))
    assert result["geodesic"] is True
    assert "evenOdd" not in result
    assert "geodesic" not in result["geometries"][0]
    assert result["geometries"][1]["geodesic"] is False
    assert result["geometries"][2]["evenOdd"] is False
    assert "geodesic" not in result["geometries"][2]
    assert json.loads(json.dumps(result)) == result


def test_raw_geojson_remains_raw_and_points_get_no_unsupported_flags():
    raw = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    translator = Translator([], {}, {})
    assert public_result(raw, geometry_translator=translator) == raw
    assert translator.steps == 0
    point = GeometryValue({"type": "Point", "coordinates": [1, 2]},
                          {"geodesic": True, "evenOdd": False})
    assert public_result(point, geometry_translator=translator) == dict(point)


def test_output_work_is_reserved_before_mapping_and_each_alias_is_charged(monkeypatch):
    from gee.compat.earthengine import geometry_public

    source = line()
    translator = Translator([], {}, {})
    public_result(source, geometry_translator=translator)
    first_cost = translator.steps
    repeated = Translator([], {}, {})
    public_result([source, source], geometry_translator=repeated)
    assert repeated.steps == 2 * first_cost

    def forbidden(_geometry):
        pytest.fail("mapping ran before its budget was reserved")

    monkeypatch.setattr(geometry_public, "public_geometry_mapping", forbidden)
    exhausted = Translator([], {}, {})
    exhausted.steps = 50000 - first_cost + 1
    with pytest.raises(UnsupportedEEError, match="50000"):
        public_result(source, geometry_translator=exhausted)


def test_mutable_sidecar_and_cycles_are_rechecked_and_full_sphere_stays_private():
    source = line()
    source.geometry_metadata["geodesic"] = 1
    with pytest.raises(UnsupportedEEError, match="boolean"):
        public_result(source, geometry_translator=Translator([], {}, {}))
    cycle = GeometryValue({"type": "GeometryCollection", "geometries": []})
    cycle["geometries"].append(cycle)
    with pytest.raises(UnsupportedEEError, match="cycle"):
        public_result(cycle, geometry_translator=Translator([], {}, {}))
    with pytest.raises(UnsupportedEEError, match="Full-sphere"):
        public_result(FULL_SPHERE, geometry_translator=Translator([], {}, {}))
