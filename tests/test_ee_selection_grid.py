"""Fresh asset-grid proof and temporal-shape boundaries for native selection."""
from copy import deepcopy
import json

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.ir import Pixel, Source, const
from gee.compat.earthengine.pixel_selection_graph import select_float64
from gee.ee_translate import UnsupportedEEError
from test_ee_double_array_solve import _compile_raster, _first_image, ee, local, offline_only


TRANSFORM = [10, 0, 0, 0, -10, 0]


def _asset(transform, crs="EPSG:32649"):
    return {"proj:code": crs, "proj:transform": transform}


@pytest.mark.parametrize("replacement", [
    _asset([10, 0, 5, 0, -10, 0]),
    _asset(TRANSFORM, "EPSG:32650"),
    _asset([20, 0, 0, 0, -20, 0]),
])
def test_same_item_asset_conflicts_reject_before_any_cube_merge(ee, local, replacement):
    item = local["items"]["sentinel-2-l2a"][0]
    item["assets"] = {"y0": _asset(TRANSFORM), "y1": _asset(TRANSFORM), "y2": replacement}
    image = _first_image(ee)
    with pytest.raises(UnsupportedEEError, match="grid|CRS"):
        _compile_raster(ee, image.select("y0").toDouble().where(
            image.select("y1"), image.select("y2").toDouble(),
        ), local)


def test_single_item_integer_pixel_offsets_are_grid_aligned(ee, local):
    item = local["items"]["sentinel-2-l2a"][0]
    item["assets"] = {"y0": _asset(TRANSFORM), "y1": _asset(TRANSFORM),
                      "y2": _asset([10, 0, 10, 0, -10, 0])}
    image = _first_image(ee)
    result, _actual, _names = _compile_raster(ee, image.select("y0").toDouble().where(
        image.select("y1"), image.select("y2").toDouble(),
    ), local)
    assert len(result["process_graph"]) < 500


def _two_sources(local):
    first = local["items"]["sentinel-2-l2a"][0]
    first["properties"].update({"proj:code": "EPSG:32649", "proj:transform": TRANSFORM})
    second = deepcopy(first)
    second["id"] = "other-date"
    second["properties"].update({"system:index": "other-date", "system:time_start": 2000})
    local["items"]["sentinel-2-l2a"].append(second)
    a = Source("sentinel-2-l2a", (first["id"],), ("y0", "y1", "y2"))
    b = Source("sentinel-2-l2a", (second["id"],), ("y0", "y1", "y2"))
    return (Pixel("to_double", (Pixel("band", (a, "y0")),)),
            Pixel("to_double", (Pixel("band", (b, "y1")),)),
            Pixel("to_double", (Pixel("band", (b, "y2")),)))


@pytest.mark.parametrize("operation", ["select", "where_select"])
def test_different_observed_dates_use_native_selection_after_key_union(local, operation):
    operands = _two_sources(local)
    graph = Graph(Translator(local["catalog"], local["items"], {}))
    _reference, _label, timed = select_float64(graph, Pixel("if", operands), operation=operation)
    assert timed is True
    native = [node for node in graph.graph.values() if node["process_id"] == "local_ee_integer_values"]
    assert len(native) == 1
    spec = json.loads(native[0]["arguments"]["spec"])
    assert spec["op"] == operation and spec["operands"] == [{"band": 0}, {"band": 1}, {"band": 2}]
    assert sum(node["process_id"] == "merge_cubes" for node in graph.graph.values()) == 2
    assert not any(node["process_id"] in {"mask", "local_ee_unmask"} for node in graph.graph.values())
    # This checks the public graph shape, not execution of Spark's key union.
    # Separate trusted native fixtures test the padded NoData input cells.


def test_selection_rejects_implicit_spatial_temporal_broadcast(local):
    condition, accept, reject = _two_sources(local)
    graph = Graph(Translator(local["catalog"], local["items"], {}))
    accept = Pixel("reduce_t", (accept, "first"))
    with pytest.raises(UnsupportedEEError, match="spatial/temporal"):
        select_float64(graph, Pixel("if", (condition, accept, reject)))
    assert not any(node["process_id"] == "merge_cubes" for node in graph.graph.values())


def test_asset_grid_changes_revalidate_despite_warm_lineage_cache(local):
    condition, accept, reject = _two_sources(local)
    # One exact source for all operands exercises the formerly skipped item.
    condition = Pixel("gt", (accept, const(0)), True)
    translator = Translator(local["catalog"], local["items"], {})
    pixel = Pixel("if", (condition, accept, reject))
    select_float64(Graph(translator), pixel)
    second = local["items"]["sentinel-2-l2a"][1]
    second["assets"] = {"y1": _asset(TRANSFORM), "y2": _asset([10, 0, 5, 0, -10, 0])}
    graph = Graph(translator)
    with pytest.raises(UnsupportedEEError, match="grid"):
        select_float64(graph, pixel)
    assert not graph.graph
