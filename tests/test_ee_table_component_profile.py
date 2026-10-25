"""Fixed EE CSV component semantics do not weaken shared geometry consumers."""
from __future__ import annotations

from copy import deepcopy
import csv
import io
import json

import pytest

from gee.planar_geometry_validation import PlanarGeometryError, planar_component_bounds
from gee.table_component_validation import EE_COMPONENTS, reserve_component_table_work
from gee.table_geometry import TableGeometryError
from gee.table_graph import table_input_graph, validate_table_graph
from gee.table_values import TableValueError, columns, render_csv


def _geometry(*, flagged=True):
    ring = [[0, 0], [4, 0], [4, 2], [0, 2], [0, 0]]
    geometry = {"type": "MultiPolygon", "coordinates": [[ring], [deepcopy(ring)]]}
    if flagged:
        geometry["geodesic"] = False
    return geometry


def _table(geometry=None):
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "id": "duplicate", "geometry": geometry,
        "properties": {"label": "original", "nested": {"keep": [1, 2]}},
    }]}


@pytest.mark.parametrize("flagged", [True, False])
def test_default_table_sampling_and_rf_boundaries_stay_strict(flagged):
    from gee.sampling_spec import _validate_regions
    from gee.rf_validation_spec import prepare_feature_rows, decode_feature_rows

    table = _table(_geometry(flagged=flagged))
    wire = json.dumps(table, sort_keys=True, separators=(",", ":"))
    for invoke in (lambda: columns(table), lambda: render_csv(table),
                   lambda: _validate_regions(table), lambda: prepare_feature_rows(table),
                   lambda: decode_feature_rows(wire)):
        with pytest.raises(TableValueError, match="topology"):
            invoke()


@pytest.mark.parametrize("flagged", [True, False])
def test_component_transfer_keeps_polygons_and_nested_metadata(flagged):
    table = _table(_geometry(flagged=flagged))
    before = deepcopy(table)
    text = render_csv(table, geometry_profile=EE_COMPONENTS)
    row, = csv.DictReader(io.StringIO(text))
    assert json.loads(row[".geo"]) == table["features"][0]["geometry"]
    assert row["system:index"] == "duplicate"
    assert json.loads(row["nested"]) == {"keep": [1, 2]}
    assert table == before
    assert planar_component_bounds(table["features"][0]["geometry"]) == (0, 0, 4, 2)


def test_worker_revalidates_json_without_a_data_selected_profile():
    table = _table(_geometry())
    graph = table_input_graph(table, ["system:index", "nested", ".geo"])
    graph["gee_table"].pop("result")
    graph["save"] = {"process_id": "save_result", "arguments": {
        "data": {"from_node": "gee_table"}, "format": "CSV",
    }, "result": True}
    wire = json.loads(json.dumps(graph))
    actual, selectors = validate_table_graph(wire)
    assert actual == table and selectors == ["system:index", "nested", ".geo"]
    wire["gee_table"]["arguments"]["geometry_profile"] = EE_COMPONENTS
    with pytest.raises(ValueError, match="literal data and columns"):
        validate_table_graph(wire)
    table["geometry_profile"] = EE_COMPONENTS
    with pytest.raises(TableValueError, match="topology"):
        columns(table)


@pytest.mark.parametrize("polygon", [
    [[[0, 0], [4, 4], [0, 4], [4, 0], [0, 0]]],
    [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
     [[10, 10], [11, 10], [11, 11], [10, 10]]],
    [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]],
     [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]],
     [[2, 2], [3.5, 2], [3.5, 3.5], [2, 2]]],
])
def test_component_profile_never_repairs_an_invalid_atomic_polygon(polygon):
    geometry = _geometry()
    geometry["coordinates"].append(polygon)
    with pytest.raises(PlanarGeometryError, match="component topology"):
        planar_component_bounds(geometry)
    with pytest.raises(TableValueError, match="component topology"):
        render_csv(_table(geometry), geometry_profile=EE_COMPONENTS)


def test_nested_components_keep_bbox_checks_and_reject_null_children():
    child = _geometry(flagged=False)
    geometry = {"type": "GeometryCollection", "geometries": [child],
                "geodesic": False, "bbox": [0, 0, 4, 2]}
    assert columns(_table(geometry), geometry_profile=EE_COMPONENTS)
    child["bbox"] = [0, 0, 1, 1]
    with pytest.raises(TableValueError, match="bbox"):
        columns(_table(geometry), geometry_profile=EE_COMPONENTS)
    geometry["geometries"] = [None]
    with pytest.raises(TableValueError, match="geometry objects"):
        columns(_table(geometry), geometry_profile=EE_COMPONENTS)


def _budget_table(extra_empty=False):
    # For the whole-table counter: 6 geometry visits +6250 list visits
    # +6249*7 position/copy visits =49999. A null second row makes50000.
    line = {"type": "LineString", "coordinates": [[index % 2, 0] for index in range(6249)]}
    table = _table(line)
    table["features"].append(_table()["features"][0])
    if extra_empty:
        table["features"].append(_table()["features"][0])
    return table


def test_exact_shared_geometry_budget_accepts_and_next_row_rejects_before_geos(monkeypatch):
    table = _budget_table()
    assert reserve_component_table_work(table["features"]) == 50000
    assert columns(table, geometry_profile=EE_COMPONENTS)
    from gee import planar_geometry_validation

    def forbidden(_):
        raise AssertionError("GEOS was entered before whole-table rejection")

    monkeypatch.setattr(planar_geometry_validation, "shape", forbidden)
    with pytest.raises(TableValueError, match="shared 50000"):
        columns(_budget_table(extra_empty=True), geometry_profile=EE_COMPONENTS)


def test_component_worker_profile_preserves_empty_multipolygon():
    geometry = {"type": "MultiPolygon", "coordinates": [], "geodesic": False}
    row, = csv.DictReader(io.StringIO(render_csv(_table(geometry), geometry_profile=EE_COMPONENTS)))
    assert json.loads(row[".geo"]) == geometry
    with pytest.raises(TableValueError, match="non-empty"):
        columns(_table(geometry))


@pytest.mark.parametrize("profile", [None, True, {}, "permissive"])
def test_invalid_internal_profile_is_not_silently_selected(profile):
    with pytest.raises(TableValueError, match="profile"):
        columns(_table(_geometry()), geometry_profile=profile)


def test_preflight_rejects_cycles_and_malformed_position_shapes():
    geometry = {"type": "GeometryCollection", "geometries": []}
    geometry["geometries"].append(geometry)
    with pytest.raises(TableGeometryError, match="cycle"):
        reserve_component_table_work(_table(geometry)["features"])
    with pytest.raises(TableGeometryError, match="two-dimensional"):
        reserve_component_table_work(_table({"type": "Point", "coordinates": [1, 2, 3]})["features"])


def _mixed_budget_table(planar_positions):
    planar = {"type": "LineString", "coordinates": [[i % 2, 0] for i in range(planar_positions)]}
    sphere = {"type": "LineString", "geodesic": True,
              "coordinates": [[i, 0] for i in range(20)]}
    table = _table(planar)
    table["features"].extend(_table(sphere)["features"])
    return table


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_planar_and_spherical_costs_share_one_ledger_before_any_kernel(monkeypatch, reverse):
    from gee import planar_geometry_validation, table_values

    # 5768 planar positions:46151;20 spherical positions:168+3681 native.
    exact = _mixed_budget_table(5768)
    assert reserve_component_table_work(exact["features"]) == 50000
    assert columns(exact, geometry_profile=EE_COMPONENTS)

    def forbidden(*args):
        raise AssertionError("Kernel entered before combined-budget rejection")

    monkeypatch.setattr(planar_geometry_validation, "shape", forbidden)
    monkeypatch.setattr(table_values, "validate_spherical_component", forbidden)
    for table in (_mixed_budget_table(6000), deepcopy(exact)):
        if len(table["features"][0]["geometry"]["coordinates"]) == 5768:
            table["features"].extend(_table()["features"])  #50001 total.
        if reverse:
            table["features"].reverse()
        with pytest.raises(TableValueError, match="shared 50000"):
            columns(table, geometry_profile=EE_COMPONENTS)


def test_preflight_native_calls_match_inherited_models_and_empty_collections(monkeypatch):
    from gee import table_component_validation, table_values
    from gee.compat.earthengine.geometry_values import GeometryValue

    line = {"type": "LineString", "coordinates": [[0, 0], [1, 0]]}
    empty = {"type": "GeometryCollection", "geometries": []}
    planar = {**deepcopy(line), "geodesic": False}
    geometry = GeometryValue({"type": "GeometryCollection",
                              "geometries": [line, empty, planar]}, {"geodesic": True})
    planned, observed = [], []
    native_work = table_component_validation.native_work

    def reserve(value):
        planned.append(value)
        return native_work(value)

    monkeypatch.setattr(table_component_validation, "native_work", reserve)
    monkeypatch.setattr(table_values, "validate_spherical_component",
                        lambda value, parity: observed.append(value))
    assert columns(_table(geometry), geometry_profile=EE_COMPONENTS)
    assert planned == observed == [line, empty]
