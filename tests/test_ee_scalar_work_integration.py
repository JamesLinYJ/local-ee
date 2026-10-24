"""A planning credit cannot replace current grid or graph admission checks."""
from __future__ import annotations

from copy import deepcopy

import pytest

from gee.compat.earthengine.decoder import Translator
from gee.compat.earthengine.graph import Graph
from gee.compat.earthengine.image_integer import _float64_pixel
from gee.compat.earthengine.integer_values_graph import compile_numeric_values_pixel
from gee.compat.earthengine.ir import Pixel, Source, const
from gee.compat.earthengine.pixel_selection_graph import select_float64
from gee.ee_translate import UnsupportedEEError


TRANSFORM = [10, 0, 500000, 0, -10, 10]


def state():
    catalog = [{"id": "sentinel-2-l2a", "cube:dimensions": {
        "bands": {"values": ["x", "y"]},
    }}]
    geometry = {"type": "Polygon", "coordinates": [
        [[500000, 0], [500040, 0], [500040, 10], [500000, 10], [500000, 0]],
    ]}
    rows = []
    for index in range(2):
        rows.append({
            "id": f"s{index}", "bbox": [500000, 0, 500040, 10],
            "geometry": deepcopy(geometry),
            "properties": {"system:index": f"s{index}", "system:time_start": index + 1,
                           "proj:code": "EPSG:32649", "proj:transform": list(TRANSFORM)},
        })
    translator = Translator(catalog, {"sentinel-2-l2a": rows}, {})
    sources = [Source("sentinel-2-l2a", (row["id"],), ("x", "y")) for row in rows]
    pixels = [Pixel("to_double", (Pixel("band", (source, "x")),)) for source in sources]
    return translator, rows, sources, pixels


def test_paid_structure_does_not_hide_changed_cross_item_projection():
    translator, rows, _sources, pixels = state()
    graph = Graph(translator)
    pixel = _float64_pixel(translator, "Image.add", "add", tuple(pixels))
    compile_numeric_values_pixel(graph, pixel)
    nodes_before = deepcopy(graph.graph)
    rows[1]["properties"]["proj:transform"][2] += 5
    # Invoke the lowering boundary again to exercise the warm work ledger;
    # Graph.expression's existing result memo is a separate mechanism.
    with pytest.raises(UnsupportedEEError, match="grid"):
        compile_numeric_values_pixel(graph, pixel)
    assert graph.graph == nodes_before


def test_paid_structure_does_not_hide_changed_same_item_asset_projection():
    translator, rows, sources, pixels = state()
    accept = pixels[0]
    reject = Pixel("to_double", (Pixel("band", (sources[0], "y")),))
    condition = Pixel("gt", (accept, const(0)), True)
    selection = Pixel("if", (condition, accept, reject))
    graph = Graph(translator)
    select_float64(graph, selection)
    nodes_before = deepcopy(graph.graph)
    rows[0]["assets"] = {
        "x": {"proj:code": "EPSG:32649", "proj:transform": list(TRANSFORM)},
        "y": {"proj:code": "EPSG:32649", "proj:transform": [10, 0, 500005, 0, -10, 10]},
    }
    with pytest.raises(UnsupportedEEError, match="grid"):
        select_float64(graph, selection)
    assert graph.graph == nodes_before


def test_unchanged_node_preflight_still_rejects_before_operand_compilation():
    translator, _rows, _sources, pixels = state()
    graph = Graph(translator)
    pixel = _float64_pixel(translator, "Image.add", "add", tuple(pixels))
    graph.graph = {f"existing{i}": {} for i in range(499)}
    calls = []
    graph.expression = lambda value: calls.append(value)
    with pytest.raises(UnsupportedEEError, match="500-node"):
        compile_numeric_values_pixel(graph, pixel)
    assert not calls
    assert len(graph.graph) == 499


def test_warm_work_ledger_does_not_admit_spatial_temporal_broadcast():
    translator, _rows, _sources, pixels = state()
    graph = Graph(translator)
    condition = Pixel("gt", (pixels[0], const(0)), True)
    select_float64(graph, Pixel("if", (condition, pixels[0], pixels[1])))
    spatial = Pixel("reduce_t", (pixels[0], "first"))
    with pytest.raises(UnsupportedEEError, match="spatial/temporal"):
        select_float64(graph, Pixel("if", (condition, spatial, pixels[1])))
