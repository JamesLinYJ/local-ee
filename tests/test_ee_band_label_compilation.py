"""Band-label graph folding checked through the pinned SDK and raster oracle."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest

from gee.ee_python_client import configure_local_ee
from gee.ee_translate import UnsupportedEEError, compile_expression
from gee.graph import validate
from test_ee_raster_linear_fit import local as raster_local
from test_ee_translate import arrays as sample_arrays
from test_ee_translate import evaluate_graph, local as sample_local


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ee():
    return configure_local_ee(
        "http://127.0.0.1:8787/openeo/1.2", "a" * 48,
        signatures_path=ROOT / "vendor/earthengine-js/algorithms.json",
    )


@pytest.fixture
def local(raster_local):
    return raster_local


def compile_value(ee, value, local):
    expression = ee.serializer.encode(value, for_cloud_api=False)
    return compile_expression(expression, local[0], local[1])


def assert_canonical_graph(result):
    assert result["kind"] == "image"
    graph = result["process_graph"]
    validate(graph)
    json.dumps(result, allow_nan=False)
    def check_refs(process_graph):
        node_ids = set(process_graph)

        def visit(value):
            if isinstance(value, dict):
                if set(value) == {"process_graph"}:
                    check_refs(value["process_graph"])
                    return
                if "from_node" in value:
                    assert set(value) == {"from_node"}
                    assert value["from_node"] in node_ids
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(process_graph)

    check_refs(graph)


def depends_on(graph, node_id, process_id, seen=None):
    seen = set() if seen is None else seen
    if node_id in seen:
        return False
    seen.add(node_id)
    node = graph[node_id]
    if node["process_id"] == process_id:
        return True
    dependencies = []

    def collect(value):
        if isinstance(value, dict):
            if set(value) == {"process_graph"}:
                return
            if set(value) == {"from_node"}:
                dependencies.append(value["from_node"])
            else:
                for child in value.values():
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(node["arguments"])
    return any(depends_on(graph, ref, process_id, seen) for ref in dependencies)


def test_shared_arithmetic_pixels_keep_distinct_output_names_and_operand_positions(
    ee, sample_local, sample_arrays,
):
    image = ee.Image("a").select("red")
    shared = image.add(image)
    outputs = (
        shared.rename("twice")
        .addBands(image.add(shared).rename("left_plus_shared"))
        .addBands(shared.subtract(image).rename("shared_minus_right"))
    )
    result = compile_value(ee, outputs, sample_local)
    assert_canonical_graph(result)
    assert result["bands"] == ["twice", "left_plus_shared", "shared_minus_right"]

    values, names, timed = evaluate_graph(result, sample_arrays)
    assert not timed
    assert names == result["bands"]
    np.testing.assert_allclose(values[:, 0], [2, 3, 1], atol=1e-7)
    np.testing.assert_allclose(values[:, 1], [6, 9, 3], atol=1e-7)


def test_rename_chains_preserve_band_order_through_merge_without_label_conflicts(
    ee, sample_local, sample_arrays,
):
    renamed = (
        ee.Image("a").select(["red", "nir"])
        .rename(["old_x", "old_y"])
        .rename(["first", "second"])
    )
    tail = ee.Image("a").select("red").add(4).rename("tail")
    result = compile_value(ee, renamed.addBands(tail), sample_local)
    assert_canonical_graph(result)
    assert result["bands"] == ["first", "second", "tail"]

    values, names, timed = evaluate_graph(result, sample_arrays)
    assert not timed
    assert names == ["first", "second", "tail"]
    # Renaming changes labels only; merge order remains red, nir, then red+4.
    np.testing.assert_allclose(values[:, 0], [1, 1, 5], atol=1e-7)
    np.testing.assert_allclose(values[:, 1], [3, 3, 7], atol=1e-7)


def test_mask_clip_and_float_cast_remain_across_delayed_output_label(ee, local):
    region = {
        "type": "Polygon",
        "coordinates": [[[0, 0], [5, 0], [0, 1], [0, 0]]],
    }
    image = ee.Image("a").select("x").updateMask(
        ee.Image("a").select("y").gt(0)
    ).toFloat().rename("masked_float").clip(region)
    result = compile_value(ee, image, local)
    assert_canonical_graph(result)
    assert result["bands"] == ["masked_float"]

    graph = result["process_graph"]
    named_nodes = [
        key for key, node in graph.items()
        if node["process_id"] == "rename_labels"
        and node["arguments"].get("target") == ["masked_float"]
    ]
    assert len(named_nodes) == 1
    assert depends_on(graph, named_nodes[0], "mask_polygon")
    assert depends_on(graph, named_nodes[0], "local_ee_to_float")

    values, names, timed = evaluate_graph(
        result, local[2], grid=local[3], source_geometries=local[4])
    assert not timed
    assert names == ["masked_float"]
    np.testing.assert_allclose(values[0, :3], [0, 0, 9998.5], atol=2e-3)
    assert np.isnan(values[0, 3:]).all()


def test_explicit_float64_arithmetic_is_still_rejected(ee, local):
    expression = ee.Image("a").select("x").toDouble().add(1).rename("unsupported")
    with pytest.raises(UnsupportedEEError, match="Float64 pixel arithmetic"):
        compile_value(ee, expression, local)


def test_same_day_fit_respects_a_nonrectangular_source_geometry_and_label_chain(
    ee, raster_local,
):
    local = deepcopy(raster_local)
    items, footprints = local[1]["sentinel-2-l2a"], local[4]
    # Keep frame d over pixel 8 while removing it over pixel 3. Three
    # observations have the same timestamp, so the reduction retains all rows
    # and its complete-pair mask is determined by geometry and NoData.
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0, 0], [3, 0], [3, 1], [0, 1], [0, 0]]],
            [[[8, 0], [9, 0], [9, 1], [8, 1], [8, 0]]],
        ],
    }
    items[-1]["geometry"] = geometry
    footprints["d"] = geometry

    fit = ee.ImageCollection("sentinel-2-l2a").reduce(ee.Reducer.linearFit())
    fit = fit.rename(["first", "second"]).rename(["slope", "offset"])
    result = compile_value(ee, fit, local)
    assert_canonical_graph(result)
    assert result["bands"] == ["slope", "offset"]
    assert set(result["source_item_ids"]) == {"a", "b", "c", "d"}

    values, names, timed = evaluate_graph(
        result, local[2], grid=local[3], source_geometries=footprints)
    assert not timed
    assert names == ["slope", "offset"]
    np.testing.assert_allclose(values[:, 0], [2, 1], rtol=1e-7, atol=1e-7)
    # Without d's nonrectangular geometry pixel 3 has two complete pairs and
    # a valid line. Removing d leaves one complete pair, so both outputs mask.
    assert np.isnan(values[:, 3]).all()
    assert np.isnan(values[:, 8]).all()
